import asyncio
import difflib
import json
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from skills.uexcorp.uexcorp.helper import Helper

class Message:

    ROLE_SYSTEM = "system"
    ROLE_ASSISTANT = "assistant"
    ROLE_USER = "user"

    def __init__(
        self,
        content: str,
        role: str,
    ):
        self.content = content
        if role not in [Message.ROLE_SYSTEM, Message.ROLE_ASSISTANT, Message.ROLE_USER]:
            raise ValueError(f"Invalid role '{role}'")
        self.role = role

    def get_message(self) -> dict[str, any]:
        return {
            "content": self.content,
            "role": self.role,
        }

class MessageHistory:

        def __init__(self):
            self.messages = []

        def add_direct(self, content: str, role: str):
            self.messages.append(Message(content, role))

        def add_message(self, message: Message):
            self.messages.append(message)

        def get_messages(self) -> list[dict[str, any]]:
            return [message.get_message() for message in self.messages]

class Llm:

    MAX_RETRIES = 3

    def __init__(
        self,
        helper: "Helper",
    ):
        self.__helper = helper
        self.__cache_search = {}
        self.__name_vectors: dict[str, "np.ndarray"] = {}
        self.__embedding_lock = threading.Lock()

    async def call(self, message_history: MessageHistory, expect_json: bool = False) -> str | dict[str, any] | list | None:
        answer = None
        request_count = 0

        while answer is None and request_count < Llm.MAX_RETRIES:
            request_count += 1
            try:
                answer = await self.__helper.get_handler_config().get_wingman().ai.generate(
                    messages=message_history.get_messages()
                )
            except Exception as e:
                self.__helper.get_handler_debug().write(
                    f"Error while calling ai.generate: {e}", True
                )
                self.__helper.get_handler_error().write(
                    "Llm.call", [message_history.get_messages(), expect_json], e
                )

            if answer and expect_json:
                message_history.add_direct(answer, Message.ROLE_ASSISTANT)
                try:
                    answer = json.loads(answer)
                except Exception as e:
                    self.__helper.get_handler_debug().write(
                        f"Error while parsing OpenAI response to JSON: {e}", True
                    )
                    self.__helper.get_handler_error().write(
                        "Llm.call", [message_history.get_messages(), expect_json], e
                    )
                    error_message = "Output was invalid json. Try again and make sure to return pure json without comments or formatting like markdown"
                    self.__helper.get_handler_debug().write(f"Adding note for llm: {error_message}")
                    message_history.add_direct(
                        error_message,
                        Message.ROLE_USER,
                    )
                    answer = None

            if answer is None:
                self.__helper.get_handler_debug().write(
                    f"LLM did not answer correctly. Retrying request #{request_count}/{self.MAX_RETRIES} ..."
                )

        return answer

    # Embeddings (Core's local nomic model) find names difflib can't: other word order
    # ("Stanton-Nyx Jump Point" -> "Nyx Gateway (Stanton)") or spacing ("Grim Hex" -> "GrimHEX").
    # Measured on the 1,036 trading locations: the meant name was in the top two for every test
    # term, ~3 s to embed the list once, a few ms per search after that.
    EMBEDDING_CANDIDATES = 5
    # Larger lists (e.g. all items) would take too long to embed
    EMBEDDING_MAX_NAMES = 3000
    EMBEDDING_BATCH = 64

    def embed_names(self, names: list[str] | set[str]) -> bool:
        """Embeds names not embedded yet. Blocking: call it from a thread. False without embedding model."""
        import numpy as np

        if len(names) > self.EMBEDDING_MAX_NAMES:
            return False
        local_ai = self.__helper.get_handler_config().get_wingman().local_ai
        with self.__embedding_lock:
            missing = [name for name in dict.fromkeys(names) if name and name not in self.__name_vectors]
            for start in range(0, len(missing), self.EMBEDDING_BATCH):
                chunk = missing[start:start + self.EMBEDDING_BATCH]
                vectors = local_ai.embed_sync(chunk)
                if not vectors or len(vectors) != len(chunk):
                    return False
                for name, vector in zip(chunk, vectors):
                    vector = np.asarray(vector, dtype=np.float32)
                    self.__name_vectors[name] = vector / (np.linalg.norm(vector) or 1.0)
        return True

    async def __embedding_matches(self, search: str, names: list[str] | set[str]) -> list[str]:
        """Names closest in meaning to the search term, [] without embedding model."""
        import numpy as np

        try:
            if not await asyncio.to_thread(self.embed_names, names):
                return []
            query = await self.__helper.get_handler_config().get_wingman().local_ai.embed([search])
            if not query:
                return []
            query = np.asarray(query[0], dtype=np.float32)
            candidates = [name for name in names if name in self.__name_vectors]
            scores = np.stack([self.__name_vectors[name] for name in candidates]) @ query
            return [candidates[i] for i in np.argsort(-scores)[:self.EMBEDDING_CANDIDATES]]
        except Exception as e:
            self.__helper.get_handler_debug().write(f"Embedding search failed for '{search}': {e}", True)
            return []

    # difflib hands over ten, the embeddings five, but the substring pass after it is unbounded: a
    # short search term can pull in hundreds. A choice takes 255 options, and
    # a list that long is not a disambiguation anyway.
    SYSTEM_ONE_MAX_OPTIONS = 60

    # Below this the answer is a guess between near-equals. The prompt this
    # replaces asked for the same thing in words ("if more than one match is
    # very likely, prefer not to match at all"); here it is a number.
    SYSTEM_ONE_MIN_CONFIDENCE = 0.5

    # Not sure, but one name far ahead of the rest ('Leske': Levski 0.29, next 0.02): almost always the
    # meant one. Used as a guess with a note and the other names, which saves asking the user first.
    SYSTEM_ONE_GUESS_MIN = 0.15
    SYSTEM_ONE_GUESS_LEAD = 5  # times the next name

    async def __system_one_match(
        self, search: str, close_matches: list[str], same_place: Callable[[list[str]], str | None] | None = None
    ) -> tuple[str | None, list[str] | None]:
        """(closest name, None), or (None, its best guesses) when System One was not sure enough or
        said none fit: then the user has to say which one, the main model would only guess.
        (None, None) when it was not asked (switched off, no access, list too long, no answer),
        so the main model decides as before.
        """
        if len(close_matches) > self.SYSTEM_ONE_MAX_OPTIONS:
            return None, None
        wingman = self.__helper.get_handler_config().get_wingman()
        system_one = getattr(wingman, "system_one", None)
        if not system_one or not system_one.available:
            return None, None

        criteria = {name: None for name in close_matches}
        criteria["none_of_these"] = "none of the names above is what was meant"
        answers = await system_one.decide(
            state={"heard": search, "context": "Star Citizen, spoken to a ship assistant"},
            questions={
                "match": system_one.choice(
                    "Which name from the list did the speaker mean? It comes "
                    "from speech recognition, so it may be misspelled, "
                    "shortened, have words in a different order, or be a word "
                    "that merely SOUNDS like part of the right name. Prefer a "
                    "longer name whose extra part sounds like what was heard "
                    "over a shorter name that is only a prefix of it.",
                    criteria,
                    examples=[
                        "'Hercules A2' with A2/C2/M2 Hercules in the list -> A2 Hercules",
                        "'Connie Taurus' -> Constellation Taurus",
                    ],
                )
            },
        )
        if not answers.ok:
            self.__helper.get_handler_debug().write(f"System One gave no answer for '{search}': {answers.error}", True)
            return None, None
        picked = answers.choice("match", min_confidence=self.SYSTEM_ONE_MIN_CONFIDENCE)
        if picked is None or picked == "none_of_these":
            probabilities = answers.probabilities("match")
            ranked = sorted((name for name in probabilities if name != "none_of_these"), key=probabilities.get, reverse=True)
            scores = ", ".join(f"{name} {probabilities[name]:.2f}" for name in ranked[:3])
            first = probabilities.get(ranked[0], 0) if ranked else 0
            second = probabilities.get(ranked[1], 0) if len(ranked) > 1 else 0
            if first >= self.SYSTEM_ONE_GUESS_MIN and first >= self.SYSTEM_ONE_GUESS_LEAD * second:
                self.__helper.get_handler_debug().write(
                    f"System One guessed '{search}' is '{ranked[0]}': {scores} "
                    f"(none of these {probabilities.get('none_of_these', 0):.2f}).",
                    True,
                )
                others = ranked[1:4]
                self.__helper.get_handler_tool().add_note(
                    f"'{search}' was taken as '{ranked[0]}' (best guess). If the user meant something else, "
                    "ask and search again" + (f", e.g. {', '.join(others)}." if others else ".")
                )
                return ranked[0], None
            # Unsure between two names for the same place (a terminal and its station): no need to ask
            place = same_place(ranked[:2]) if same_place and len(ranked) > 1 else None
            if place:
                self.__helper.get_handler_debug().write(
                    f"System One not sure about '{search}' ({scores}), but '{ranked[0]}' and '{ranked[1]}' are the same place: '{place}'."
                )
                return place, None
            self.__helper.get_handler_debug().write(
                f"System One not sure about '{search}': {scores}"
                f" (none of these {probabilities.get('none_of_these', 0):.2f}, needs {self.SYSTEM_ONE_MIN_CONFIDENCE})",
                True,
            )
            return None, ranked[:3] or close_matches[:3]
        self.__helper.get_handler_debug().write(
            f"System One matched '{search}' to '{picked}' "
            f"(confidence {answers.confidence('match'):.2f}, {answers.seconds * 1000:.0f} ms)."
        )
        return picked, None

    async def find_closest_match(
        self, search: str | None, lst: list[str] | set[str], same_place: Callable[[list[str]], str | None] | None = None
    ) -> (str | None, list[str] | set[str]):
        """The name in lst meant by search. same_place(names) may return the one name that stands
        for the place all of them mean, so the user isn't asked to choose between them."""
        if not search or search == "None":
            return None, None

        self.__helper.get_handler_debug().write(f"Searching for closest match for '{search}' in list.")

        checksum = f"{hash(frozenset(lst))}-{hash(search)}"
        if checksum in self.__cache_search:
            match = self.__cache_search[checksum]
            self.__helper.get_handler_debug().write(f"Found closest match for '{search}' in cache: '{match}'")
            return match, None

        if search in lst:
            self.__helper.get_handler_debug().write(f"Found exact match for '{search}' in list.")
            return search, None

        # make a list of possible matches
        close_matches = await self.__embedding_matches(search, lst)
        close_matches.extend(item for item in difflib.get_close_matches(search, lst, n=10, cutoff=0.4) if item not in close_matches)
        close_matches.extend(item for item in lst if search.lower() in item.lower() and item not in close_matches)
        self.__helper.get_handler_debug().write(
            f"Creating a list of close matches for search term '{search}': {', '.join(close_matches)}"
        )

        if not close_matches:
            self.__helper.get_handler_debug().write(
                f"No close matches found for '{search}' in list. Returning None.", True
            )
            return None, "No approximate matches found, given name too abstract."

        # A System One model decides this better than a prompt can: it cannot
        # answer outside the list, and its confidence says "more than one fits"
        # without being asked to phrase that in prose. Measured 2026-09-20 on
        # twelve misheard ship names against a pool with the real variant
        # collisions: 11/12 against difflib's own 10/12, ~500 ms against a full
        # main-model roundtrip. Off, or unavailable, and the prompt below runs
        # exactly as before.
        picked, guesses = await self.__system_one_match(search, close_matches, same_place)
        if guesses:
            return None, f"{', '.join(guesses)} (not sure which one, ask the user)"
        if picked is not None:
            self.__helper.add_context(f"Note for function parameters: Use '{picked}' instead of '{search}'.")
            self.__cache_search[checksum] = picked
            return picked, None

        messages = MessageHistory()
        messages.add_direct(
            f"""
                I'll give you just a string value.
                You will figure out, what value in this list represents this value best: {', '.join(close_matches)}
                Keep in mind that the given string value can be misspelled or has missing words as it has its origin in a speech to text process.
                You must only return the value of the closest match to the given value from the defined list, nothing else.
                For example if "Hercules A2" is given and the list contains of "A2, C2, M2", you will return "A2" as string.
                Or if "C2" is given and the list contains of "A2 Hercules Star Lifter, C2 Monster Truck, M2 Extreme cool ship", you will return "C2 Monster Truck" as string.
                On longer search terms, prefer the exact match, if it is in the list.
                If more than one match is very likely, prefer not to match at all.
                The response must not contain anything else, than the exact value of the closest match from the list.
                If you can't find a match, return 'None'. Do never return the given search value.
            """,
            Message.ROLE_SYSTEM,
        )
        messages.add_direct(search, Message.ROLE_USER)
        answer = await self.call(messages)

        if not answer:
            dumb_match = difflib.get_close_matches(search, close_matches, n=1, cutoff=0.8)
            if dumb_match:
                self.__helper.get_handler_debug().write(
                    f"LLM did not answer for '{search}'. Using dumb match '{dumb_match}'",
                    True,
                )
                return dumb_match[0], None
            else:
                self.__helper.get_handler_debug().write(
                    f"LLM did not answer for '{search}' and dumb match to inaccurate.",
                    True,
                )
                return None, ', '.join(close_matches[:3])

        if answer == "None" or answer not in close_matches:
            self.__helper.get_handler_debug().write(
                f"LLM said no match possible for '{search}' in list.", False
            )
            return None, ', '.join(close_matches[:3])

        self.__helper.get_handler_debug().write(f"LLM said '{answer}' is closest match to '{search}' in list.")
        self.__helper.add_context(f"Note for function parameters: Use '{answer}' instead of '{search}'.")
        self.__cache_search[checksum] = answer
        return answer, None

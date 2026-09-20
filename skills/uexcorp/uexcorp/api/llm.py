import difflib
import json
from typing import TYPE_CHECKING

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

    # difflib hands over ten, but the substring pass after it is unbounded: a
    # short search term can pull in hundreds. A choice takes 255 options, and
    # a list that long is not a disambiguation anyway.
    SYSTEM_ONE_MAX_OPTIONS = 60

    # Below this the answer is a guess between near-equals. The prompt this
    # replaces asked for the same thing in words ("if more than one match is
    # very likely, prefer not to match at all"); here it is a number.
    SYSTEM_ONE_MIN_CONFIDENCE = 0.5

    async def __system_one_match(self, search: str, close_matches: list[str]) -> str | None:
        """The closest name, or None to let the main model decide as before.

        None covers every way this does not produce an answer: the user
        switched System One off, the plan has no access, the shortlist is too
        long to ask about, the model was not sure enough, or it said none of
        them fit. All of those fall through to the prompt below.
        """
        if len(close_matches) > self.SYSTEM_ONE_MAX_OPTIONS:
            return None
        wingman = self.__helper.get_handler_config().get_wingman()
        system_one = getattr(wingman, "system_one", None)
        if not system_one or not system_one.available:
            return None

        criteria = {name: None for name in close_matches}
        criteria["none_of_these"] = "none of the names above is what was meant"
        answers = await system_one.decide(
            state={"heard": search, "context": "Star Citizen, spoken to a ship assistant"},
            questions={
                "match": system_one.choice(
                    "Which name from the list did the speaker mean? It comes from "
                    "speech recognition, so it may be misspelled, shortened or "
                    "have words in a different order.",
                    criteria,
                    examples=[
                        "'Hercules A2' with A2/C2/M2 Hercules in the list -> A2 Hercules",
                        "'Connie Taurus' -> Constellation Taurus",
                    ],
                )
            },
        )
        picked = answers.choice("match", min_confidence=self.SYSTEM_ONE_MIN_CONFIDENCE)
        if picked is None or picked == "none_of_these":
            return None
        self.__helper.get_handler_debug().write(
            f"System One matched '{search}' to '{picked}' "
            f"(confidence {answers.confidence('match'):.2f}, {answers.seconds * 1000:.0f} ms)."
        )
        return picked

    async def find_closest_match(
        self, search: str | None, lst: list[str] | set[str]
    ) -> (str | None, list[str] | set[str]):
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
        close_matches = difflib.get_close_matches(search, lst, n=10, cutoff=0.4)
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
        picked = await self.__system_one_match(search, close_matches)
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

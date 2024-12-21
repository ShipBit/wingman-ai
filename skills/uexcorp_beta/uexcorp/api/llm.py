import difflib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.uexcorp_beta.uexcorp.helper import Helper

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
        completion = await self.__helper.get_handler_config().get_wingman().actual_llm_call(message_history.get_messages())
        answer = None
        request_count = 0

        while answer is None and request_count < Llm.MAX_RETRIES:
            request_count += 1
            try:
                answer = completion.choices[0].message.content
            except Exception as e:
                self.__helper.get_handler_debug().write(
                    f"Error while parsing OpenAI response: {e}", True
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

    async def find_closest_match(
        self, search: str | None, lst: list[str] | set[str]
    ) -> str | None:
        if not search or search == "None":
            return None

        self.__helper.get_handler_debug().write(f"Searching for closest match for '{search}' in list.")

        checksum = f"{hash(frozenset(lst))}-{hash(search)}"
        if checksum in self.__cache_search:
            match = self.__cache_search[checksum]
            self.__helper.get_handler_debug().write(f"Found closest match for '{search}' in cache: '{match}'")
            return match

        if search in lst:
            self.__helper.get_handler_debug().write(f"Found exact match for '{search}' in list.")
            return search

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
            return None

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
                return dumb_match[0]
            else:
                self.__helper.get_handler_debug().write(
                    f"LLM did not answer for '{search}' and dumb match to inaccurate.",
                    True,
                )
                return None

        if answer == "None" or answer not in close_matches:
            self.__helper.get_handler_debug().write(
                f"LLM said no match possible for '{search}' in list.", True
            )
            return None

        self.__helper.get_handler_debug().write(f"LLM said '{answer}' is closest match to '{search}' in list.")
        self.__helper.add_context(f"Note for function parameters: Use '{answer}' instead of '{search}'.")
        self.__cache_search[checksum] = answer
        return answer

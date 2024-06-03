from os import path
import json
import datetime
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    WingmanConfig,
    SkillConfig,
    WingmanInitializationError,
)
from api.enums import (
    LogType,
)
from services.file import get_writable_dir
from services.printr import Printr
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()


class InstantActivationLearning(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:

        # get file paths
        self.data_path = get_writable_dir(
            path.join("skills", "instant_activation_learning", "data")
        )
        self.file_ipl = path.join(self.data_path, "instant_phrase_learning.json")

        # learning data
        self.learning_blacklist = []
        self.learning_data = {}
        self.learning_learned = {}

        # rules
        self.rule_count = 3

        super().__init__(
            config=config,
            wingman_config=wingman_config,
            settings=settings,
            wingman=wingman,
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.rule_count = self.retrieve_custom_property_value(
            "quick_commands_learning_rule_count", errors
        )
        if not self.rule_count or self.rule_count < 0:
            self.rule_count = 3

        self.threaded_execution(self._init_skill)
        return errors

    async def _init_skill(self) -> None:
        """Initialize the skill."""
        await self._load_learning_data()
        await self._cleanup_learning_data()
        for phrase, command in self.learning_learned.items():
            await self._add_instant_activation_phrase(phrase, command)

    async def _add_instant_activation_phrase(self, phrase: str, command: str) -> None:
        """Add an instant activation phrase."""
        command = self.wingman.get_command(command)
        if not command.instant_activation:
            command.instant_activation = []

        if phrase not in command.instant_activation:
            command.instant_activation.append(phrase)

    async def on_add_user_message(self, message: str) -> None:
        """Hook to start learning process. (Currently one message behind)"""
        self.threaded_execution(self._process_messages, self.wingman.messages.copy())

    async def _process_messages(self, messages) -> None:
        """Process messages to learn phrases and commands."""
        phrase = ""
        command_name = ""
        if not messages:
            return
        messages.reverse()
        for message in messages:
            role = (
                message.role if hasattr(message, "role") else message.get("role", False)
            )
            if role == "assistant":
                tool_calls = (
                    message.tool_calls
                    if hasattr(message, "tool_calls")
                    else message.get("tool_calls", False)
                )
                # if no function calls, ignore
                if not tool_calls:
                    continue
                # if more than one tool call, ignore
                if len(tool_calls) != 1:
                    return
                # if the tool call is not a command call, ignore
                if tool_calls[0].function.name != "execute_command":
                    return
                command_name = json.loads(tool_calls[0].function.arguments)[
                    "command_name"
                ]
            elif role == "user":
                content = (
                    message.content
                    if hasattr(message, "content")
                    else message.get("content", False)
                )
                phrase = content
                break

        if not phrase or not command_name:
            return

        await self._learn_phrase(phrase, command_name)

    async def _cleanup_learning_data(self) -> None:
        """Cleanup learning data. (Remove for commands that are no loner available)"""
        pops = []
        for phrase, command in self.learning_learned.items():
            if not self.wingman.get_command(command):
                pops.append(phrase)
        if pops:
            for phrase in pops:
                self.learning_learned.pop(phrase)

        pops = []
        finished = []
        for phrase in self.learning_data.keys():
            if not self.wingman.get_command(self.learning_data[phrase]["command"]):
                pops.append(phrase)
            elif self.learning_data[phrase]["count"] >= self.rule_count:
                finished.append(phrase)

        if pops:
            for phrase in pops:
                self.learning_data.pop(phrase)
        if finished:
            for phrase in finished:
                self._finish_learning(phrase, self.learning_data[phrase]["command"])

        await self._save_learning_data()

    async def _learn_phrase(self, phrase: str, command_name: str) -> None:
        """Learn a phrase and the tool calls that should be executed for it."""
        # load the learning data
        await self._load_learning_data()

        # check if the phrase is on the blacklist
        if phrase in self.learning_blacklist:
            return

        # get and check the command
        command = self.wingman.get_command(command_name)
        if not command:
            # AI probably hallucinated
            return

        # add / increase count of the phrase
        if phrase in self.learning_data:
            if self.learning_data[phrase]["command"] != command.name:
                # phrase is ambiguous, add to blacklist
                await self._add_to_blacklist(phrase)
                return

            self.learning_data[phrase]["count"] += 1
        else:
            self.learning_data[phrase] = {"command": command.name, "count": 1}

        if self.learning_data[phrase]["count"] >= self.rule_count:
            await self._finish_learning(phrase, command.name)

        # save the learning data
        await self._save_learning_data()

    async def _finish_learning(self, phrase: str, command: str) -> None:
        """Finish learning a phrase.
        A gpt call will be made to check if the phrase makes sense.
        This will add the phrase to the learned phrases."""
        messages = [
            {
                "role": "system",
                "content": """
                    I'll give you a command and a phrase. You have to decide, if the commands fits to the phrase or not.
                    Return 'yes' if the command fits to the phrase and 'no' if it does not.

                    Samples:
                    - Phrase: "What is the weather like?" Command: "checkWeather" -> yes
                    - Phrase: "What is the weather like?" Command: "playMusic" -> no
                    - Phrase: "Please do that." Command: "enableShields" -> no
                    - Phrase: "Yes, please." Command: "enableShields" -> no
                    - Phrase: "We are being attacked by rockets." Command: "throwCountermessures" -> yes
                    - Phrase: "Its way too dark in here." Command: "toggleLight" -> yes
                """,
            },
            {
                "role": "user",
                "content": f"Phrase: '{phrase}' Command: '{command}'",
            },
        ]
        completion = await self.gpt_call(messages)
        answer = completion.choices[0].message.content or ""
        if answer.lower() == "yes":
            await printr.print_async(
                f"Instant activation phrase for {command} learned.", color=LogType.INFO
            )
            self.learning_learned[phrase] = command
            self.learning_data.pop(phrase)
            await self._add_instant_activation_phrase(phrase, command)
        else:
            await self._add_to_blacklist(phrase)

        await self._save_learning_data()

    async def _add_to_blacklist(self, phrase: str) -> None:
        """Add a phrase to the blacklist."""
        self.learning_blacklist.append(phrase)
        self.learning_data.pop(phrase)
        await self._save_learning_data()

    async def _is_phrase_on_blacklist(self, phrase: str) -> bool:
        """Check if a phrase is on the blacklist."""
        if phrase in self.learning_blacklist:
            return True
        return False

    async def _load_learning_data(self):
        """Load the learning data file."""

        # create the file if it does not exist
        if not path.exists(self.file_ipl):
            return

        # load the learning data
        with open(self.file_ipl, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                await printr.print_async(
                    "Could not read learning data file. Resetting learning data..",
                    color=LogType.ERROR,
                )
                # if file wasnt empty, save it as backup
                if file.read():
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
                    with open(
                        self.file_ipl + f"_{timestamp}.backup", "w", encoding="utf-8"
                    ) as backup_file:
                        backup_file.write(file.read())
                # reset learning data
                with open(self.file_ipl, "w", encoding="utf-8") as file:
                    file.write("{}")
                data = {}

            self.learning_data = (
                data["learning_data"] if "learning_data" in data else {}
            )
            self.learning_blacklist = (
                data["learning_blacklist"] if "learning_blacklist" in data else []
            )
            self.learning_learned = (
                data["learning_learned"] if "learning_learned" in data else {}
            )

    async def _save_learning_data(self) -> None:
        """Save the learning data."""

        learning_data = {
            "learning_data": self.learning_data,
            "learning_blacklist": self.learning_blacklist,
            "learning_learned": self.learning_learned,
        }

        with open(self.file_ipl, "w", encoding="utf-8") as file:
            json.dump(learning_data, file, indent=4)

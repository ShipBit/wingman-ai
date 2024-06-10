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


class QuickCommands(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:

        # get file paths
        self.data_path = get_writable_dir(
            path.join("skills", "quick_commands", "data")
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
        for phrase, commands in self.learning_learned.items():
            await self._add_instant_activation_phrase(phrase, commands)

    async def _add_instant_activation_phrase(self, phrase: str, commands: list[str]) -> None:
        """Add an instant activation phrase."""
        for command in commands:
            command = self.wingman.get_command(command)
            if not command.instant_activation:
                command.instant_activation = []

            if phrase not in command.instant_activation:
                command.instant_activation.append(phrase)

    async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
        """Hook to start learning process."""
        if tool_calls:
            self.threaded_execution(self._process_messages, tool_calls, self.wingman.messages[-1])

    async def _process_messages(self, tool_calls, last_message) -> None:
        """Process messages to learn phrases and commands."""
        phrase = ""
        command_names = []

        for tool_call in tool_calls:
            if tool_call.function.name == "execute_command":
                if isinstance(tool_call.function.arguments, dict):
                    arguments = tool_call.function.arguments
                else:
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        return
                if "command_name" in arguments:
                    command_names.append(arguments["command_name"])
                else:
                    return
            else:
                return

        role = (
            last_message.role if hasattr(last_message, "role") else last_message.get("role", False)
        )
        if role != "user":
            return
        phrase = (
            last_message.content
            if hasattr(last_message, "content")
            else last_message.get("content", False)
        )

        if not phrase or not command_names:
            return

        await self._learn_phrase(phrase.lower(), command_names)

    async def _cleanup_learning_data(self) -> None:
        """Cleanup learning data. (Remove for commands that are no loner available)"""
        pops = []
        for phrase, commands in self.learning_learned.items():
            for command in commands:
                if not self.wingman.get_command(command):
                    pops.append(phrase)
        if pops:
            for phrase in pops:
                self.learning_learned.pop(phrase)

        pops = []
        finished = []
        for phrase in self.learning_data.keys():
            commands = self.learning_data[phrase]["commands"]
            for command in commands:
                if not self.wingman.get_command(command):
                    pops.append(phrase)
                elif self.learning_data[phrase]["count"] >= self.rule_count:
                    finished.append(phrase)

        if pops:
            for phrase in pops:
                self.learning_data.pop(phrase)
        if finished:
            for phrase in finished:
                await self._finish_learning(phrase)

        await self._save_learning_data()

    async def _learn_phrase(self, phrase: str, command_names: list[str]) -> None:
        """Learn a phrase and the tool calls that should be executed for it."""
        # load the learning data
        await self._load_learning_data()

        # check if the phrase is on the blacklist
        if phrase in self.learning_blacklist:
            return

        # get and check the command
        for command_name in command_names:
            command = self.wingman.get_command(command_name)
            if not command:
                # AI probably hallucinated
                return

        # add / increase count of the phrase
        if phrase in self.learning_data:
            if len(self.learning_data[phrase]["commands"]) != len(command_names):
                # phrase is ambiguous, add to blacklist
                await self._add_to_blacklist(phrase)
                return

            for command_name in command_names:
                if command_name not in self.learning_data[phrase]["commands"]:
                    # phrase is ambiguous, add to blacklist
                    await self._add_to_blacklist(phrase)
                    return

            self.learning_data[phrase]["count"] += 1
        else:
            self.learning_data[phrase] = {"commands": command_names, "count": 1}

        if self.learning_data[phrase]["count"] >= self.rule_count:
            await self._finish_learning(phrase)

        # save the learning data
        await self._save_learning_data()

    async def _finish_learning(self, phrase: str) -> None:
        """Finish learning a phrase.
        A gpt call will be made to check if the phrases makes sense.
        This will add the phrase to the learned phrases."""

        commands = self.learning_data[phrase]["commands"]

        messages = [
            {
                "role": "system",
                "content": """
                    I'll give you one or multiple commands and a phrase. You have to decide, if the commands fit to the phrase or not.
                    Return 'yes' if the commands fit to the phrase and 'no' if they dont.

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
                "content": f"Phrase: '{phrase}' Commands: '{', '.join(commands)}'",
            },
        ]
        completion = await self.llm_call(messages)
        answer = completion.choices[0].message.content or ""
        if answer.lower() == "yes":
            await printr.print_async(
                f"Instant activation phrase for '{', '.join(commands)}' learned.", color=LogType.INFO
            )
            self.learning_learned[phrase] = commands
            self.learning_data.pop(phrase)
            await self._add_instant_activation_phrase(phrase, commands)
        else:
            await self._add_to_blacklist(phrase)

        await self._save_learning_data()

    async def _add_to_blacklist(self, phrase: str) -> None:
        """Add a phrase to the blacklist."""
        await printr.print_async(
            f"Added phrase to blacklist: '{phrase if len(phrase) <= 25 else phrase[:25]+'...'}'", color=LogType.INFO
        )
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

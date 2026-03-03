import traceback
from copy import deepcopy
import random
import time
import difflib
import asyncio
import threading
from typing import (
    Any,
    Dict,
    Optional,
    TYPE_CHECKING,
)
import keyboard.keyboard as keyboard
import mouse.mouse as mouse
from api.interface import (
    CommandConfig,
    SettingsConfig,
    SkillConfig,
    SoundConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import (
    CommandTag,
    LogSource,
    LogType,
    WingmanInitializationErrorType,
)
from providers.faster_whisper import FasterWhisper
from providers.whispercpp import Whispercpp
from providers.xvasynth import XVASynth
from providers.pocket_tts import PocketTTS
from services.audio_player import AudioPlayer
from services.benchmark import Benchmark
from services.module_manager import ModuleManager
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.audio_library import AudioLibrary
from skills.skill_base import Skill

if TYPE_CHECKING:
    from services.tower import Tower

printr = Printr()


def _get_skill_folder_from_module(module: str) -> str:
    """Extract folder name from module path like 'skills.star_head.main' -> 'star_head'"""
    return module.replace(".main", "").replace(".", "/").split("/")[1]


class Wingman:
    """The "highest" Wingman base class in the chain. It does some very basic things but is meant to be 'virtual', and so are most its methods, so you'll probably never instantiate it directly.

    Instead, you'll create a custom wingman that inherits from this (or a another subclass of it) and override its methods if needed.
    """

    def __init__(
        self,
        name: str,
        config: WingmanConfig,
        settings: SettingsConfig,
        audio_player: AudioPlayer,
        audio_library: AudioLibrary,
        whispercpp: Whispercpp,
        fasterwhisper: FasterWhisper,
        xvasynth: XVASynth,
        pocket_tts: PocketTTS,
        tower: "Tower",
    ):
        """The constructor of the Wingman class. You can override it in your custom wingman.

        Args:
            name (str): The name of the wingman. This is the key you gave it in the config, e.g. "atc"
            config (WingmanConfig): All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here.
        """

        self.config = config
        """All "general" config entries merged with the specific Wingman config settings. The Wingman takes precedence and overrides the general config. You can just add new keys to the config and they will be available here."""

        self.settings = settings
        """The general user settings."""

        self.secret_keeper = SecretKeeper()
        """A service that allows you to store and retrieve secrets like API keys. It can prompt the user for secrets if necessary."""
        self.secret_keeper.secret_events.subscribe(
            "secrets_saved", self.handle_secret_saved
        )

        self.name = name
        """The name of the wingman. This is the key you gave it in the config, e.g. "atc"."""

        self.audio_player = audio_player
        """A service that allows you to play audio files and add sound effects to them."""

        self.audio_library = audio_library
        """A service that allows you to play and manage audio files from the audio library."""

        self.execution_start: None | float = None
        """Used for benchmarking executon times. The timer is (re-)started whenever the process function starts."""

        self.whispercpp = whispercpp
        """A class that handles the communication with the Whispercpp server for transcription."""

        self.fasterwhisper = fasterwhisper
        """A class that handles local transcriptions using FasterWhisper."""

        self.xvasynth = xvasynth
        """A class that handles the communication with the XVASynth server for TTS."""
        
        self.pocket_tts = pocket_tts
        """A class that handles the communication with the PocketTTS server for TTS."""

        self.tower = tower
        """The Tower instance that manages all Wingmen in the same config dir."""

        self.skills: list[Skill] = []

    def get_record_key(self) -> str | int:
        """Returns the activation or "push-to-talk" key for this Wingman."""
        return self.config.record_key_codes or self.config.record_key

    def get_record_mouse_button(self) -> str:
        """Returns the activation or "push-to-talk" mouse button for this Wingman."""
        return self.config.record_mouse_button

    def get_record_joystick_button(self) -> str:
        """Returns the activation or "push-to-talk" joystick button for this Wingman."""
        if not self.config.record_joystick_button:
            return None
        return f"{self.config.record_joystick_button.guid}{self.config.record_joystick_button.button}"

    async def handle_secret_saved(self, _secrets: Dict[str, Any]):
        await printr.print_async(
            text="Secret saved",
            source_name=self.name,
            command_tag=CommandTag.SECRET_SAVED,
        )
        await self.validate()

    # ──────────────────────────────────── Hooks ─────────────────────────────────── #

    async def validate(self) -> list[WingmanInitializationError]:
        """Use this function to validate params and config before the Wingman is started.
        If you add new config sections or entries to your custom wingman, you should validate them here.

        It's a good idea to collect all errors from the base class and not to swallow them first.

        If you return MISSING_SECRET errors, the user will be asked for them.
        If you return other errors, your Wingman will not be loaded by Tower.

        Returns:
            list[WingmanInitializationError]: A list of errors or an empty list if everything is okay.
        """
        return []

    async def retrieve_secret(self, secret_name, errors):
        """Use this method to retrieve secrets like API keys from the SecretKeeper.
        If the key is missing, the user will be prompted to enter it.
        """
        try:
            api_key = await self.secret_keeper.retrieve(
                requester=self.name,
                key=secret_name,
                prompt_if_missing=True,
            )
            if not api_key:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=f"Missing secret '{secret_name}'.",
                        error_type=WingmanInitializationErrorType.MISSING_SECRET,
                        secret_name=secret_name,
                    )
                )
        except Exception as e:
            printr.print(
                f"Error retrieving secret ''{secret_name}: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message=f"Could not retrieve secret '{secret_name}': {str(e)}",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name=secret_name,
                )
            )
            api_key = None

        return api_key

    async def prepare(self):
        """This method is called only once when the Wingman is instantiated by Tower.
        It is run AFTER validate() and AFTER init_skills() so you can access validated params safely here.

        You can override it if you need to load async data from an API or file."""

    async def unload(self):
        """This method is called when the Wingman is unloaded by Tower. You can override it if you need to clean up resources."""
        # Unsubscribe from secret events to prevent duplicate handlers
        self.secret_keeper.secret_events.unsubscribe(
            "secrets_saved", self.handle_secret_saved
        )
        await self.unload_skills()

    async def unload_skills(self):
        """Call this to trigger unload for skills that were actually prepared/used."""
        for skill in self.skills:
            # Only unload skills that were actually prepared (activated)
            # Skills that were never used don't need cleanup
            if not skill.is_prepared:
                continue
            try:
                await skill.unload()
            except Exception as e:
                await printr.print_async(
                    f"Error unloading skill '{skill.name}': {str(e)}",
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )

    async def init_skills(self) -> list[WingmanInitializationError]:
        """Load all available skills with lazy validation.

        Skills are loaded but NOT validated during init. Validation happens
        on first activation via the SkillRegistry. User config overrides from
        self.config.skills are merged with default configs.

        Platform-incompatible skills are skipped entirely.
        """
        import sys

        current_platform = sys.platform  # 'win32', 'darwin', 'linux'
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        if self.skills:
            await self.unload_skills()

        errors = []
        self.skills = []

        # Build a lookup of user config overrides by skill folder name
        # The key must be the folder name (e.g., 'star_head') not the class name (e.g., 'StarHead')
        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        # Get all available skill configs
        available_skills = ModuleManager.read_available_skill_configs()

        # Get discoverable skills list (whitelist)
        discoverable_skills = self.config.discoverable_skills

        for skill_folder_name, skill_config_path, _is_custom, _is_local in available_skills:
            try:
                # Load default skill config first to get the display name
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                # Import SkillConfig here to avoid circular imports
                from api.interface import SkillConfig

                # Check if user has overrides for this skill
                if skill_folder_name in user_skill_configs:
                    # Merge user overrides into default config
                    user_config = user_skill_configs[skill_folder_name]
                    # User config takes precedence - merge custom_properties especially
                    if user_config.custom_properties:
                        skill_config_dict["custom_properties"] = [
                            prop.model_dump() for prop in user_config.custom_properties
                        ]
                    if user_config.prompt:
                        skill_config_dict["prompt"] = user_config.prompt

                skill_config = SkillConfig(**skill_config_dict)

                # Check if skill is discoverable for this wingman (whitelist - must be in list)
                if skill_config.name not in discoverable_skills:
                    continue

                # Check platform compatibility BEFORE loading the module
                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        printr.print(
                            f"Skipping skill '{skill_config.name}' - not supported on {normalized_platform}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                        continue

                # Load the skill module
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=self,
                )
                if skill:
                    # Set up skill methods
                    skill.threaded_execution = self.threaded_execution

                    # Add to skills list WITHOUT validation
                    # Validation will happen lazily on first activation
                    self.skills.append(skill)
                    await self.prepare_skill(skill)

            except Exception as e:
                skill_name = skill_folder_name
                error_msg = f"Error loading skill '{skill_name}': {str(e)}"
                await printr.print_async(
                    error_msg,
                    color=LogType.ERROR,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=error_msg,
                        error_type=WingmanInitializationErrorType.SKILL_INITIALIZATION_FAILED,
                    )
                )

        # Log summary of discoverable skills for this wingman
        if self.skills:
            skill_names = [s.config.name for s in self.skills]
            await printr.print_async(
                f"Discoverable skills ({len(skill_names)}): {', '.join(skill_names)}",
                color=LogType.WINGMAN,
                source=LogSource.WINGMAN,
                source_name=self.name,
                server_only=not self.settings.debug_mode,
            )

        return errors

    async def prepare_skill(self, skill: Skill):
        """This method is called only once when the Skill is instantiated.
        It is run AFTER validate() so you can access validated params safely here.

        You can override it if you need to react on data of this skill."""

    async def unprepare_skill(self, skill: Skill):
        """Remove a skill's registration. Called when a skill is disabled.

        Override in subclass to clean up skill-specific registrations."""
        pass

    async def enable_skill(self, skill_name: str) -> tuple[bool, str]:
        """Enable a single skill without reinitializing all skills.

        Args:
            skill_name: The display name of the skill to enable

        Returns:
            (success, message) tuple
        """
        import sys

        current_platform = sys.platform
        platform_map = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
        normalized_platform = platform_map.get(current_platform, current_platform)

        # Check if skill is already enabled
        for existing_skill in self.skills:
            if existing_skill.config.name == skill_name:
                return True, f"Skill '{skill_name}' is already enabled."

        # Find the skill config
        available_skills = ModuleManager.read_available_skill_configs()

        # Build user config lookup by skill folder name
        user_skill_configs: dict[str, "SkillConfig"] = {}
        if self.config.skills:
            for skill_config in self.config.skills:
                folder_name = _get_skill_folder_from_module(skill_config.module)
                user_skill_configs[folder_name] = skill_config

        for skill_folder_name, skill_config_path, _is_custom, _is_local in available_skills:
            try:
                skill_config_dict = ModuleManager.read_config(skill_config_path)
                if not skill_config_dict:
                    continue

                from api.interface import SkillConfig

                # Apply user overrides
                if skill_folder_name in user_skill_configs:
                    user_config = user_skill_configs[skill_folder_name]
                    if user_config.custom_properties:
                        skill_config_dict["custom_properties"] = [
                            prop.model_dump() for prop in user_config.custom_properties
                        ]
                    if user_config.prompt:
                        skill_config_dict["prompt"] = user_config.prompt

                skill_config = SkillConfig(**skill_config_dict)

                if skill_config.name != skill_name:
                    continue

                # Check platform compatibility
                if skill_config.platforms:
                    if normalized_platform not in skill_config.platforms:
                        return (
                            False,
                            f"Skill '{skill_name}' is not supported on {normalized_platform}.",
                        )

                # Load and register the skill
                skill = ModuleManager.load_skill(
                    config=skill_config,
                    settings=self.settings,
                    wingman=self,
                )
                if skill:
                    skill.threaded_execution = self.threaded_execution
                    self.skills.append(skill)
                    await self.prepare_skill(skill)

                    printr.print(
                        f"Skill '{skill_name}' activated (loaded and made discoverable).",
                        color=LogType.POSITIVE,
                        server_only=True,
                    )
                    return True, f"Skill '{skill_name}' activated successfully."

            except Exception as e:
                error_msg = f"Error activating skill '{skill_name}': {str(e)}"
                await printr.print_async(error_msg, color=LogType.ERROR)
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                return False, error_msg

        return False, f"Skill '{skill_name}' not found."

    async def disable_skill(self, skill_name: str) -> tuple[bool, str]:
        """Disable a single skill without reinitializing all skills.

        Args:
            skill_name: The display name of the skill to disable

        Returns:
            (success, message) tuple
        """
        # Find the skill in our list
        skill_to_remove = None
        for skill in self.skills:
            if skill.config.name == skill_name:
                skill_to_remove = skill
                break

        if not skill_to_remove:
            return True, f"Skill '{skill_name}' is already deactivated."

        try:
            # Unload the skill (cleanup resources, unsubscribe events)
            await skill_to_remove.unload()

            # Remove from skill list
            self.skills.remove(skill_to_remove)

            # Remove skill-specific registrations (tools, registry, etc.)
            await self.unprepare_skill(skill_to_remove)

            printr.print(
                f"Skill '{skill_name}' deactivated (unloaded and removed from discoverable skills).",
                color=LogType.WARNING,
                server_only=True,
            )
            return True, f"Skill '{skill_name}' deactivated successfully."

        except Exception as e:
            error_msg = f"Error deactivating skill '{skill_name}': {str(e)}"
            await printr.print_async(error_msg, color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False, error_msg

    def reset_conversation_history(self):
        """This function is called when the user triggers the ResetConversationHistory command.
        It's a global command that should be implemented by every Wingman that keeps a message history.
        """

    # ──────────────────────────── The main processing loop ──────────────────────────── #

    async def process(self, audio_input_wav: str = None, transcript: str = None):
        """The main method that gets called when the wingman is activated. This method controls what your wingman actually does and you can override it if you want to.

        The base implementation here triggers the transcription and processing of the given audio input.
        If you don't need even transcription, you can just override this entire process method. If you want transcription but then do something in addition, you can override the listed hooks.

        Async so you can do async processing, e.g. send a request to an API.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Hooks:
            - async _transcribe: transcribe the audio to text
            - async _get_response_for_transcript: process the transcript and return a text response
            - async play_to_user: do something with the response, e.g. play it as audio
        """

        try:
            process_result = None

            benchmark_transcribe = None
            if not transcript:
                # transcribe the audio.
                benchmark_transcribe = Benchmark(label="Voice transcription")
                transcript = await self._transcribe(audio_input_wav)

            interrupt = None
            if transcript:
                await printr.print_async(
                    f"{transcript}",
                    color=LogType.USER,
                    source_name="User",
                    source=LogSource.USER,
                    benchmark_result=(
                        benchmark_transcribe.finish() if benchmark_transcribe else None
                    ),
                )

                # Further process the transcript.
                # Return a string that is the "answer" to your passed transcript.

                benchmark_llm = Benchmark(label="Command/AI Processing")
                process_result, instant_response, skill, interrupt = (
                    await self._get_response_for_transcript(
                        transcript=transcript, benchmark=benchmark_llm
                    )
                )

                actual_response = instant_response or process_result

                if actual_response:
                    await printr.print_async(
                        f"{actual_response}",
                        color=LogType.POSITIVE,
                        source=LogSource.WINGMAN,
                        source_name=self.name,
                        skill_name=skill.name if skill else "",
                        benchmark_result=benchmark_llm.finish(),
                    )

            if process_result:
                if self.settings.streamer_mode:
                    self.tower.save_last_message(self.name, process_result)

                # the last step in the chain. You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.
                await self.play_to_user(str(process_result), not interrupt)
        except Exception as e:
            await printr.print_async(
                f"Error during processing of Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    # ───────────────── virtual methods / hooks ───────────────── #

    async def _transcribe(self, audio_input_wav: str) -> str | None:
        """Transcribes the audio to text. You can override this method if you want to use a different transcription service.

        Args:
            audio_input_wav (str): The path to the audio file that contains the user's speech. This is a recording of what you you said.

        Returns:
            str | None: The transcript of the audio file and the detected language as locale (if determined).
        """
        return None

    async def _get_response_for_transcript(
        self, transcript: str, benchmark: Benchmark
    ) -> tuple[str | None, str | None, Skill | None, bool | None]:
        """Processes the transcript and return a response as text. This where you'll do most of your work.
        Pass the transcript to AI providers and build a conversation. Call commands or APIs. Play temporary results to the user etc.


        Args:
            transcript (str): The user's spoken text transcribed as text.

        Returns:
            A tuple of strings representing the response to a function call and/or an instant response.
        """
        return "", "", None, None

    async def play_to_user(
        self,
        text: str,
        no_interrupt: bool = False,
        sound_config: Optional[SoundConfig] = None,
    ):
        """You'll probably want to play the response to the user as audio using a TTS provider or mechanism of your choice.

        Args:
            text (str): The response of your _get_response_for_transcript. This is usually the "response" from conversation with the AI.
            no_interrupt (bool): prevent interrupting the audio playback
            sound_config (SoundConfig): An optional sound configuration to use for the playback. If unset, the Wingman's sound config is used.
        """
        pass

    # ───────────────────────────────── Commands ─────────────────────────────── #

    def get_command(self, command_name: str) -> CommandConfig | None:
        """Extracts the command with the given name

        Args:
            command_name (str): the name of the command you used in the config

        Returns:
            {}: The command object from the config
        """
        if self.config.commands is None:
            return None

        command = next(
            (item for item in self.config.commands if item.name == command_name),
            None,
        )
        return command

    def _select_command_response(self, command: CommandConfig) -> str | None:
        """Returns one of the configured responses of the command. This base implementation returns a random one.

        Args:
            command (dict): The command object from the config

        Returns:
            str: A random response from the command's responses list in the config.
        """
        command_responses = command.responses
        if (command_responses is None) or (len(command_responses) == 0):
            return None

        return random.choice(command_responses)

    async def _execute_instant_activation_command(
        self, transcript: str
    ) -> list[CommandConfig] | None:
        """Uses a fuzzy string matching algorithm to match the transcript to a configured instant_activation command and executes it immediately.

        Args:
            transcript (text): What the user said, transcripted to text. Needs to be similar to one of the defined instant_activation phrases to work.

        Returns:
            {} | None: The executed instant_activation command.
        """

        try:
            # create list with phrases pointing to commands
            commands_by_instant_activation = {}
            for command in self.config.commands:
                if command.instant_activation:
                    for phrase in command.instant_activation:
                        if phrase.lower() in commands_by_instant_activation:
                            commands_by_instant_activation[phrase.lower()].append(
                                command
                            )
                        else:
                            commands_by_instant_activation[phrase.lower()] = [command]

            # find best matching phrase
            phrase = difflib.get_close_matches(
                transcript.lower(),
                commands_by_instant_activation.keys(),
                n=1,
                cutoff=1,
            )

            # if no phrase found, return None
            if not phrase:
                return None

            # execute all commands for the phrase
            commands = commands_by_instant_activation[phrase[0]]
            for command in commands:
                await self._execute_command(command, True)

            # return the executed command
            return commands
        except Exception as e:
            await printr.print_async(
                f"Error during instant activation in Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def _execute_command(self, command: CommandConfig, is_instant=False) -> str:
        """Triggers the execution of a command. This base implementation executes the keypresses defined in the command.

        Args:
            command (dict): The command object from the config to execute

        Returns:
            str: the selected response from the command's responses list in the config. "Ok" if there are none.
        """

        if not command:
            return "Command not found"

        try:
            if len(command.actions or []) == 0:
                await printr.print_async(
                    f"No actions found for command: {command.name}",
                    color=LogType.WARNING,
                )
            else:
                await self.execute_action(command)
                await printr.print_async(
                    f"Executed {'instant' if is_instant else 'AI'} command: {command.name}",
                    color=LogType.COMMAND,
                )

            # handle the global special commands:
            if command.name == "ResetConversationHistory":
                self.reset_conversation_history()
                await printr.print_async(
                    f"Executed command: {command.name}", color=LogType.COMMAND
                )

            return self._select_command_response(command) or "Ok"
        except Exception as e:
            await printr.print_async(
                f"Error executing command '{command.name}' for Wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return "ERROR DURING PROCESSING"  # hints to AI that there was an Error

    async def execute_action(self, command: CommandConfig):
        """Executes the actions defined in the command (in order).

        Args:
            command (dict): The command object from the config to execute
        """
        if not command or not command.actions:
            return

        def contains_numpad_key(hotkey: str) -> bool:
            """Check if the hotkey string contains a numpad key anywhere in the chord.

            Args:
                hotkey: The hotkey string (e.g., 'num 1', 'ctrl+num 1', 'alt+num 2')

            Returns:
                True if any token in the chord is a numpad key (num 0 - num 9)
            """
            if not hotkey:
                return False
            tokens = hotkey.lower().split('+')
            return any(token.startswith('num ') for token in tokens)

        try:
            for action in command.actions:
                if action.keyboard:
                    if action.keyboard.hotkey_codes and not contains_numpad_key(action.keyboard.hotkey):
                        code = action.keyboard.hotkey_codes
                    else:
                        code = action.keyboard.hotkey

                    if action.keyboard.press == action.keyboard.release:
                        # compressed key events
                        hold = action.keyboard.hold or 0.1
                        if (
                            action.keyboard.hotkey_codes
                            and len(action.keyboard.hotkey_codes) == 1
                            and not contains_numpad_key(action.keyboard.hotkey)
                        ):
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                0 + (1 if action.keyboard.hotkey_extended else 0),
                            )
                            time.sleep(hold)
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                2 + (1 if action.keyboard.hotkey_extended else 0),
                            )
                        else:
                            keyboard.press(code)
                            time.sleep(hold)
                            keyboard.release(code)
                    else:
                        # single key events
                        if (
                            action.keyboard.hotkey_codes
                            and len(action.keyboard.hotkey_codes) == 1
                            and not contains_numpad_key(action.keyboard.hotkey)
                        ):
                            keyboard.direct_event(
                                action.keyboard.hotkey_codes[0],
                                (0 if action.keyboard.press else 2)
                                + (1 if action.keyboard.hotkey_extended else 0),
                            )
                        else:
                            keyboard.send(
                                code,
                                action.keyboard.press,
                                action.keyboard.release,
                            )

                if action.mouse:
                    if action.mouse.move_to:
                        x, y = action.mouse.move_to
                        mouse.move(x, y)

                    if action.mouse.move:
                        x, y = action.mouse.move
                        mouse.move(x, y, absolute=False, duration=0.5)

                    if action.mouse.scroll:
                        mouse.wheel(action.mouse.scroll)

                    if action.mouse.button:
                        if action.mouse.hold:
                            mouse.press(button=action.mouse.button)
                            time.sleep(action.mouse.hold)
                            mouse.release(button=action.mouse.button)
                        else:
                            mouse.click(button=action.mouse.button)

                if action.write:
                    keyboard.write(action.write)

                if action.wait:
                    time.sleep(action.wait)

                if action.audio:
                    await self.audio_library.handle_action(
                        action.audio, self.config.sound.volume
                    )
        except Exception as e:
            await printr.print_async(
                f"Error executing actions of command '{command.name}' for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

    def threaded_execution(self, function, *args) -> threading.Thread | None:
        """Execute a function in a separate thread."""
        try:

            def start_thread(function, *args):
                if asyncio.iscoroutinefunction(function):
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(function(*args))
                    new_loop.close()
                else:
                    function(*args)

            thread = threading.Thread(target=start_thread, args=(function, *args))
            thread.name = function.__name__
            thread.daemon = True  # Mark as daemon so it dies when main process exits
            thread.start()
            return thread
        except Exception as e:
            printr.print(
                f"Error starting threaded execution: {str(e)}", color=LogType.ERROR
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return None

    async def update_config(
        self, config: WingmanConfig, skip_config_validation: bool = True
    ) -> bool:
        """Update the config of the Wingman.

        This method should always be called if the config of the Wingman has changed.

        Args:
            config: The new wingman configuration
            skip_config_validation: If False, validate the config and rollback on error

        Returns:
            True if config was updated successfully, False otherwise
        """
        try:
            if not skip_config_validation:
                old_config = deepcopy(self.config)

            self.config = config

            # Propagate skill config changes to loaded skills
            await self._update_skill_configs(config)

            if not skip_config_validation:
                errors = await self.validate()

                for error in errors:
                    if (
                        error.error_type
                        != WingmanInitializationErrorType.MISSING_SECRET
                    ):
                        self.config = old_config
                        return False

            return True
        except Exception as e:
            await printr.print_async(
                f"Error updating config for wingman '{self.name}': {str(e)}",
                color=LogType.ERROR,
            )
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False

    async def _update_skill_configs(self, wingman_config: WingmanConfig) -> None:
        """Propagate skill config changes to loaded skills.

        When the wingman config changes (e.g., user updates custom_properties for a skill),
        we need to update the SkillConfig on each loaded skill instance so they see the new values.
        """
        if not self.skills or not wingman_config.skills:
            return

        # Build lookup of new skill configs by folder name
        new_skill_configs: dict[str, "SkillConfig"] = {}
        for skill_config in wingman_config.skills:
            try:
                folder_name = _get_skill_folder_from_module(skill_config.module)
            except Exception:
                printr.print(
                    f"Skipping skill config override with unexpected module format: '{skill_config.module}'",
                    color=LogType.WARNING,
                    server_only=True,
                )
                continue
            new_skill_configs[folder_name] = skill_config

        # Update each loaded skill if its config changed
        for skill in self.skills:
            # Get the folder name for this skill
            try:
                skill_folder = _get_skill_folder_from_module(skill.config.module)
            except Exception:
                printr.print(
                    f"Skipping loaded skill with unexpected module format: '{skill.config.module}'",
                    color=LogType.WARNING,
                    server_only=True,
                )
                continue

            if skill_folder in new_skill_configs:
                user_override = new_skill_configs[skill_folder]

                fields_set = getattr(user_override, "model_fields_set", None)
                if fields_set is None:
                    # Pydantic v1 fallback
                    fields_set = getattr(user_override, "__fields_set__", set())

                # Create updated config by copying current and applying overrides
                # This preserves all default values while applying user overrides
                updated_config = deepcopy(skill.config)

                # Apply overrides even if they're explicitly empty.
                # This allows users to clear custom properties/prompt in the UI.
                if "custom_properties" in fields_set:
                    updated_config.custom_properties = user_override.custom_properties
                if "prompt" in fields_set:
                    updated_config.prompt = user_override.prompt

                # Let the skill handle the config update (will compare old vs new)
                await skill.update_config(updated_config)

    async def save_config(self):
        """Save the config of the Wingman."""
        self.tower.save_wingman(self.name)

    async def save_commands(self):
        """Save only the commands section of this wingman's config.

        This performs a partial YAML update - only the commands field is modified
        in the config file, avoiding full config serialization. This is much safer
        than save_config() for command-only changes as it won't accidentally
        overwrite other fields.

        Use this instead of save_config() when you only changed command definitions,
        instant_activation phrases, or other command-related fields.

        Example use cases:
        - QuickCommands learning instant activation phrases
        - Skills dynamically adding/modifying commands
        - Skills updating command responses or actions
        """
        self.tower.save_wingman_commands(self.name)

    async def update_settings(self, settings: SettingsConfig):
        """Update the settings of the Wingman. This method should always be called when the user Settings have changed.
        """
        self.settings = settings

        # Propagate settings changes to already-loaded skills
        for skill in self.skills:
            skill.settings = settings

        printr.print(f"Wingman {self.name}'s settings changed", server_only=True)

import json
import re
import time
import hashlib
import threading
import math
from dataclasses import dataclass, field
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any, Optional

from openai import OpenAI, AzureOpenAI, APIStatusError

from services.audio_player import AudioPlayer
from services.printr import Printr
from wingmen.star_citizen_services.ai_context_enum import AIContext
from wingmen.star_citizen_services.function_manager import FunctionManager

try:
    import pydirectinput as key_module
except Exception:
    import pyautogui as key_module

try:
    import pygetwindow
except Exception:
    pygetwindow = None

try:
    import sounddevice as sd
except Exception:
    sd = None


printr = Printr()


@dataclass
class MacroRuntimeJob:
    name: str
    stop_event: threading.Event
    thread: threading.Thread
    started_at: float = field(default_factory=time.time)


class MacroManager(FunctionManager):
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = (
        "Manages named macros, including interval keypress sequences, countdowns, reminders and beep tickers."
    )
    MANAGER_CAPABILITIES = [
        "Create and update named macros",
        "Activate/deactivate macros by tool call or command phrase",
        "Run interval key sequences with modifiers and wait steps",
        "Run countdown announcements and reminder speech",
    ]

    PHRASE_MATCH_THRESHOLD = 0.88
    SUPPORTED_MODIFIERS = {
        "alt": "alt",
        "altleft": "altleft",
        "altright": "altright",
        "lalt": "altleft",
        "ralt": "altright",
        "shift": "shift",
        "shiftleft": "shiftleft",
        "shiftright": "shiftright",
        "lshift": "shiftleft",
        "rshift": "shiftright",
        "ctrl": "ctrl",
        "control": "ctrl",
        "ctrlleft": "ctrlleft",
        "ctrlright": "ctrlright",
        "lctrl": "ctrlleft",
        "rctrl": "ctrlright",
    }
    VALID_MACRO_TYPES = {"interval_sequence", "countdown", "reminder", "beep_ticker"}
    ONE_SHOT_TYPES = {"countdown", "reminder"}
    RUNTIME_COUNTDOWN_JOB_NAME = "__runtime_countdown__"
    DEFAULT_AFK_MACRO_NAME = "AFK"
    DEFAULT_AFK_SOURCE_FILE = "default_afk.json"
    DEFAULT_RELOAD_COMMAND_PHRASES = [
        "makros neu laden",
        "makros neu einlesen",
        "reload makros",
        "reload macros",
        "macro reload",
        "macro manager reload",
    ]
    TIMER_KEYWORDS = ("timer", "countdown")
    DURATION_HINT = "Use duration format like '1m 20s', '45s', or '2h 5m'."

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config
        self.debug_mode = False

        feature_entry = self.config.get("features", {}).get(self.__class__.__name__, {})
        self.macro_feature_config = feature_entry if isinstance(feature_entry, dict) else {}
        global_debug_mode = bool(self.config.get("features", {}).get("debug_mode", False))
        self.debug_mode = bool(
            self.macro_feature_config.get(
                "debug_mode",
                global_debug_mode,
            )
        )
        self.dry_run_key_actions = bool(
            self.macro_feature_config.get(
                "dry_run_key_actions",
                global_debug_mode,
            )
        )

        sc_keybind_mappings = self.config.get("sc-keybind-mappings", {})
        raw_key_mappings = (
            sc_keybind_mappings.get("key-mappings", {})
            if isinstance(sc_keybind_mappings, dict)
            else {}
        )
        self.sc_key_mappings: dict[str, str] = {}
        if isinstance(raw_key_mappings, dict):
            for source_key, target_key in raw_key_mappings.items():
                source = str(source_key).strip().lower()
                target = str(target_key).strip()
                if source and target:
                    self.sc_key_mappings[source] = target

        self.default_play_beep = bool(self.macro_feature_config.get("default_play_beep", True))
        self.min_interval_seconds = max(float(self.macro_feature_config.get("min_interval_seconds", 1.0)), 0.1)
        self.max_active_macros = max(int(self.macro_feature_config.get("max_active_macros", 20)), 1)
        self.auto_activate_on_create = bool(self.macro_feature_config.get("auto_activate_on_create", True))
        self.default_timer_duration_seconds = max(
            int(float(self.macro_feature_config.get("default_timer_duration_seconds", 120))),
            1,
        )
        self.default_afk_interval_seconds = max(
            float(self.macro_feature_config.get("default_afk_interval_seconds", 120)),
            self.min_interval_seconds,
        )
        configured_reload_phrases = self.macro_feature_config.get(
            "reload_command_phrases",
            self.DEFAULT_RELOAD_COMMAND_PHRASES,
        )
        if isinstance(configured_reload_phrases, str):
            configured_reload_phrases = [configured_reload_phrases]
        if not isinstance(configured_reload_phrases, list):
            configured_reload_phrases = list(self.DEFAULT_RELOAD_COMMAND_PHRASES)
        self.reload_command_phrases = self._dedupe_phrases([str(item) for item in configured_reload_phrases])

        data_root_directory = self.config.get("data-root-directory", "star_citizen_data")
        macro_data_directory = self.macro_feature_config.get("data_directory", "macro-data")
        self.macro_data_path = Path(data_root_directory) / macro_data_directory
        self.macros_path = self.macro_data_path / "macros"
        self.tts_cache_path = self.macro_data_path / "tts_cache"
        self.tts_text_cache_file = self.tts_cache_path / "spoken_text_cache.json"
        self.macros_path.mkdir(parents=True, exist_ok=True)
        self.tts_cache_path.mkdir(parents=True, exist_ok=True)

        self.audio_player = AudioPlayer(sound_config=self.config.get("sound", {}))
        self.beep_file = Path(__file__).resolve().parents[4] / "audio_samples" / "beep.wav"
        self._beep_audio_bytes: Optional[bytes] = None

        self._openai_tts_client: Optional[OpenAI] = None
        self._azure_tts_client: Optional[AzureOpenAI] = None
        self._openai_api_key = None
        self._azure_tts_api_key = None

        self.macros: dict[str, dict[str, Any]] = {}
        self.active_jobs: dict[str, MacroRuntimeJob] = {}
        self._lock = threading.RLock()
        self._tts_text_cache_lock = threading.RLock()
        self._spoken_text_cache: dict[str, str] = {}
        self._runtime_countdown_duration_seconds: Optional[int] = None

        self._load_spoken_text_cache()
        self.load_macro_definitions()

    def on_manager_enabled(self, source: str = "manual"):
        self.load_macro_definitions()
        self._activate_enabled_macros_from_disk()

    def on_manager_disabled(self, source: str = "manual"):
        self.stop_all_macros(persist_state=False)

    def get_context_mapping(self) -> AIContext:
        return AIContext.CORA

    def register_functions(self, function_register):
        function_register[self.manage_macro.__name__] = self.manage_macro

    def get_function_prompt(self) -> str:
        return (
            f"Use {self.manage_macro.__name__} for creating, managing and toggling named macros. "
            "Use duration strings in format like '1m 20s', '45s', or '2h 5m' for all timing values. "
            "For timer or countdown requests, use action 'start_countdown' instead of creating a new macro. "
            "Use action 'stop_countdown' to stop the currently running countdown. "
            "Use action 'get_countdown_remaining' when the player asks for the remaining countdown time. "
            "A default AFK macro (Y every two minutes) already exists. "
            "For interval keypress macros, use steps of type key_press, key_hold and wait. "
            "Always provide a macro name when creating a new macro. "
            "When creating a macro, provide command_phrases in natural spoken language based on what the macro does. "
            "Prefer short, everyday variants and include at least one very short alias. "
        )

    def get_function_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": self.manage_macro.__name__,
                    "description": (
                        "Create/update/list/activate/deactivate named macros, start countdowns, and run reminders or beeps."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "list_macros",
                                    "get_macro",
                                    "reload_macros",
                                    "start_countdown",
                                    "stop_countdown",
                                    "get_countdown_remaining",
                                    "activate_macro",
                                    "deactivate_macro",
                                    "stop_all_macros",
                                    "delete_macro",
                                    "create_interval_macro",
                                    "create_reminder_macro",
                                    "create_metronome_beep_ticker_macro",
                                ],
                                "description": "Macro operation to perform.",
                            },
                            "name": {
                                "type": "string",
                                "description": "Macro name. Required for all operations except list/reload/stop_all. Use a human-friendly name describing the behavior.",
                            },
                            "activate": {
                                "type": "boolean",
                                "description": "Only for create actions. If true, macro starts immediately.",
                            },
                            "play_beep": {
                                "type": "boolean",
                                "description": "If true, the macro plays a beep on execution.",
                            },
                            "command_phrases": {
                                "type": "object",
                                "properties": {
                                    "activate": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "deactivate": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "description": (
                                    "Spoken intuitive trigger phrases for this macro. Provide english phrases and phrases in the player's language if different. These are used to activate/deactivate the macro by voice command. "
                                    "Write colloquial phrases based on macro behavior, not technical identifiers. "
                                    "Include short variants. Example for an AFK macro: activate ['start afk', 'enable afk', 'afk on', 'I'm afk'], deactivate ['stop afk', 'disable afk', 'I'm back']."
                                ),
                            },
                            "interval_compact_duration_format": {
                                "type": "string",
                                "description": "Required for interval and beep ticker creation. Expects compact duration format '1m 20s', '45s', '2h 5m'. Defines how often the steps are executed for interval macros, and how often the beep plays for beep ticker macros.",
                            },
                            "total_duration_compact_duration_format": {
                                "type": "string",
                                "description": "Optional total runtime for interval/beep ticker macros. Expects compact duration format '1m 20s', '45s', '2h 5m'. If not provided, the macro will run indefinitely until deactivated. Example if the player says 'start an interval macro that presses Y every 2 minutes for 10 minutes', the total_duration would be '10m'.",
                            },
                            "steps": {
                                "type": "array",
                                "description": "Only for interval macros.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["key_press", "key_hold", "wait"],
                                        },
                                        "key": {"type": "string"},
                                        "hold_ms": {"type": "integer"},
                                        "wait_ms": {"type": "integer"},
                                        "modifiers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["type"],
                                },
                            },
                            "duration_compact_duration_format": {
                                "type": "string",
                                "description": "Required for start_countdown. Expects compact duration format '1m 20s', '45s', '2h 5m'. Example if the player says 'start countdown for 1 minute 20 seconds', the duration would be '1m 20s'.",
                            },
                            "delay_compact_duration_format": {
                                "type": "string",
                                "description": "Required for reminder creation. Expects compact duration format '1m 20s', '45s', '2h 5m'. Example if the player says 'remind me in 1 minute 20 seconds', the delay would be '1m 20s'.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Reminder text or final countdown message.",
                            },
                        },
                        "required": ["action"],
                    },
                },
            }
        ]

    def manage_macro(self, function_args):
        action = function_args.get("action")
        self._debug_log("manage_macro.call", action=action, function_args=function_args)

        if action == "list_macros":
            return self._response_success(
                action,
                "Macro overview created.",
                macros=self._list_macro_overview(),
            )

        if action == "reload_macros":
            return self._reload_macros(source="tool_call")

        if action == "start_countdown":
            duration_seconds = self._parse_duration_to_seconds(function_args.get("duration_compact_duration_format"))
            self._debug_log(
                "manage_macro.start_countdown.parsed",
                raw_duration=function_args.get("duration_compact_duration_format"),
                parsed_seconds=duration_seconds,
            )
            if duration_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="duration_compact_duration_format",
                    detail="Missing or invalid countdown duration.",
                )
            return self._start_countdown(
                duration_seconds=duration_seconds,
                text=function_args.get("text"),
                play_beep=function_args.get("play_beep"),
            )

        if action == "stop_countdown":
            return self._stop_runtime_countdown_job()

        if action == "get_countdown_remaining":
            return self.get_countdown_remaining()

        if action == "stop_all_macros":
            stopped = self.stop_all_macros(persist_state=True)
            return self._response_success(
                action,
                f"Stopped {stopped} active macro(s).",
                macros=self._list_macro_overview(),
            )

        macro_name = function_args.get("name")
        if action not in {
            "list_macros",
            "reload_macros",
            "stop_all_macros",
            "start_countdown",
            "stop_countdown",
            "get_countdown_remaining",
        }:
            if not isinstance(macro_name, str) or not macro_name.strip():
                return self._response_error(action, "Please provide a valid macro name.")
            macro_name = macro_name.strip()

        if action == "get_macro":
            macro = self._get_macro(macro_name)
            if not macro:
                return self._response_error(action, f"Macro '{macro_name}' not found.")
            return self._response_success(action, f"Macro '{macro_name}' loaded.", macro=macro)

        if action == "activate_macro":
            return self.activate_macro(macro_name, persist_state=True)

        if action == "deactivate_macro":
            return self.deactivate_macro(macro_name, persist_state=True)

        if action == "delete_macro":
            return self.delete_macro(macro_name)

        if action == "create_interval_macro":
            steps = function_args.get("steps")
            interval_seconds = self._parse_duration_to_seconds(function_args.get("interval_compact_duration_format"))
            total_duration_raw = function_args.get("total_duration_compact_duration_format")
            total_duration_seconds = None
            if total_duration_raw is not None:
                total_duration_seconds = self._parse_duration_to_seconds(total_duration_raw)
            self._debug_log(
                "manage_macro.create_interval_macro.parsed",
                raw_interval=function_args.get("interval_compact_duration_format"),
                parsed_interval_seconds=interval_seconds,
                raw_total_duration=total_duration_raw,
                parsed_total_duration_seconds=total_duration_seconds,
                steps_count=len(steps) if isinstance(steps, list) else None,
            )
            if not isinstance(steps, list) or not steps:
                return self._response_error(action, "Please provide at least one step for the interval macro.")
            if interval_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="interval_compact_duration_format",
                    detail="Missing or invalid interval.",
                )
            if total_duration_raw is not None and total_duration_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="total_duration_compact_duration_format",
                    detail="Invalid total duration.",
                )

            macro_definition = {
                "name": macro_name,
                "type": "interval_sequence",
                "interval_seconds": interval_seconds,
                "total_duration_seconds": total_duration_seconds,
                "steps": steps,
                "play_beep": function_args.get("play_beep", self.default_play_beep),
                "enabled": bool(function_args.get("activate", self.auto_activate_on_create)),
                "command_phrases": function_args.get("command_phrases", {}),
            }
            return self._create_or_update_macro(action, macro_definition)

        if action == "create_reminder_macro":
            delay_seconds = self._parse_duration_to_seconds(function_args.get("delay_compact_duration_format"))
            text = function_args.get("text")
            self._debug_log(
                "manage_macro.create_reminder_macro.parsed",
                raw_delay=function_args.get("delay_compact_duration_format"),
                parsed_delay_seconds=delay_seconds,
                has_text=bool(text),
            )
            if delay_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="delay_compact_duration_format",
                    detail="Missing or invalid reminder delay.",
                )
            if not text:
                return self._response_error(action, "Please provide 'text' for reminder macros.")
            macro_definition = {
                "name": macro_name,
                "type": "reminder",
                "delay_seconds": delay_seconds,
                "text": text,
                "play_beep": function_args.get("play_beep", self.default_play_beep),
                "enabled": bool(function_args.get("activate", self.auto_activate_on_create)),
                "command_phrases": function_args.get("command_phrases", {}),
            }
            return self._create_or_update_macro(action, macro_definition)

        if action == "create_metronome_beep_ticker_macro":
            interval_seconds = self._parse_duration_to_seconds(function_args.get("interval_compact_duration_format"))
            total_duration_raw = function_args.get("total_duration_compact_duration_format")
            total_duration_seconds = None
            if total_duration_raw is not None:
                total_duration_seconds = self._parse_duration_to_seconds(total_duration_raw)
            self._debug_log(
                "manage_macro.create_beep_ticker_macro.parsed",
                raw_interval=function_args.get("interval_compact_duration_format"),
                parsed_interval_seconds=interval_seconds,
                raw_total_duration=total_duration_raw,
                parsed_total_duration_seconds=total_duration_seconds,
            )
            if interval_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="interval_compact_duration_format",
                    detail="Missing or invalid interval.",
                )
            if total_duration_raw is not None and total_duration_seconds is None:
                return self._duration_input_error(
                    action=action,
                    field_name="total_duration_compact_duration_format",
                    detail="Invalid total duration.",
                )
            macro_definition = {
                "name": macro_name,
                "type": "beep_ticker",
                "interval_seconds": interval_seconds,
                "total_duration_seconds": total_duration_seconds,
                "play_beep": True,
                "enabled": bool(function_args.get("activate", self.auto_activate_on_create)),
                "command_phrases": function_args.get("command_phrases", {}),
            }
            return self._create_or_update_macro(action, macro_definition)

        self._debug_log("manage_macro.unsupported_action", action=action, function_args=function_args)
        return self._response_error(action, f"Unsupported action '{action}'.")

    def _reload_macros(self, source: str = "runtime"):
        self.stop_all_macros(persist_state=False)
        self.load_macro_definitions()
        self._activate_enabled_macros_from_disk()
        return self._response_success(
            "reload_macros",
            "Macros reloaded from disk.",
            source=source,
            macros=self._list_macro_overview(),
        )

    def _start_countdown(self, duration_seconds: Any, text: Any = None, play_beep: Any = None):
        resolved_duration = self._coerce_positive_seconds(duration_seconds)
        if resolved_duration is None:
            return self._duration_input_error(
                action="start_countdown",
                field_name="duration_compact_duration_format",
                detail="Missing or invalid countdown duration.",
            )

        runtime_macro = self._build_runtime_countdown_macro(
            duration_seconds=resolved_duration,
            text=text,
            play_beep=play_beep,
        )
        return self._start_runtime_countdown_job(runtime_macro, resolved_duration)

    def _build_runtime_countdown_macro(
        self,
        duration_seconds: int,
        text: Any = None,
        play_beep: Any = None,
    ) -> dict[str, Any]:
        final_text = self._clean_optional_text(text) or self._countdown_finished_text(self._get_player_language_code())
        return {
            "name": "Runtime Countdown",
            "type": "countdown",
            "duration_seconds": int(duration_seconds),
            "text": final_text,
            "play_beep": bool(self.default_play_beep if play_beep is None else play_beep),
            "enabled": False,
        }

    def _start_runtime_countdown_job(self, runtime_macro: dict[str, Any], duration_seconds: int):
        self._stop_runtime_countdown_job()

        with self._lock:
            if len(self.active_jobs) >= self.max_active_macros:
                return self._response_error(
                    "start_countdown",
                    f"Cannot start countdown. Maximum of {self.max_active_macros} active macros reached.",
                )

            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_macro_worker,
                args=(self.RUNTIME_COUNTDOWN_JOB_NAME, stop_event, runtime_macro),
                daemon=True,
                name=f"Macro-{self.RUNTIME_COUNTDOWN_JOB_NAME}",
            )
            job = MacroRuntimeJob(
                name=self.RUNTIME_COUNTDOWN_JOB_NAME,
                stop_event=stop_event,
                thread=thread,
            )
            self.active_jobs[self.RUNTIME_COUNTDOWN_JOB_NAME] = job
            self._runtime_countdown_duration_seconds = int(duration_seconds)

        thread.start()
        return self._response_success(
            "start_countdown",
            f"Countdown started ({self._format_duration_text(duration_seconds)}).",
            instructions="Inform the player in his language that the countdown has started by confirming the duration in a natural spoken format. Example: '1m 20s' becomes 'one minute and twenty seconds'.",
            do_not_cache=True,
        )

    def _stop_runtime_countdown_job(self):
        job: Optional[MacroRuntimeJob] = None
        with self._lock:
            job = self.active_jobs.get(self.RUNTIME_COUNTDOWN_JOB_NAME)

        if not job:
            return self._response_success(
                "stop_countdown",
                "In player language: Countdown is already inactive.",
                do_not_cache=True,
            )

        job.stop_event.set()
        if job.thread.is_alive():
            job.thread.join(timeout=1.5)
        with self._lock:
            self.active_jobs.pop(self.RUNTIME_COUNTDOWN_JOB_NAME, None)
            self._runtime_countdown_duration_seconds = None

        return self._response_success(
            "stop_countdown",
            "Countdown stopped.",
            instructions="Inform the player in his language",
            do_not_cache=True,
        )

    def get_countdown_remaining(self):
        with self._lock:
            job = self.active_jobs.get(self.RUNTIME_COUNTDOWN_JOB_NAME)
            duration_seconds = self._runtime_countdown_duration_seconds

        if not job or not duration_seconds:
            return self._response_error(
                "get_countdown_remaining",
                "No countdown is currently running.",
                hints=[
                    "Start a countdown first with action 'start_countdown'.",
                    self.DURATION_HINT,
                ],
                instructions="Inform the player in his language"
            )

        elapsed = max(0.0, time.time() - job.started_at)
        remaining_seconds = max(0, int(math.ceil(duration_seconds - elapsed)))
        remaining_compact = self._format_duration_compact(remaining_seconds)

        return self._response_success(
            "get_countdown_remaining",
            f"In player language: Remaining time: {remaining_compact}.",
            instructions="Transform to spoken format based on player language. Example: '1m 20s' becomes 'one minute and twenty seconds'.",
            do_not_cache=True,
        )

    def _duration_input_error(self, action: str, field_name: str, detail: str):
        self._debug_log(
            "manage_macro.duration_input_error",
            action=action,
            field_name=field_name,
            detail=detail,
        )
        return self._response_error(
            action,
            detail,
            field=field_name,
            hints=[
                self.DURATION_HINT,
                f"Example: set '{field_name}' to '1m 20s' or '45s'.",
            ],
            instructions="Inform the player in his language"
        )

    def _create_or_update_macro(self, action: str, raw_definition: dict[str, Any]):
        sanitized = self._sanitize_macro_definition(raw_definition)
        if not sanitized:
            return self._response_error(action, "Invalid macro definition.")

        existing_name = self._resolve_macro_name(sanitized["name"])
        if existing_name and existing_name != sanitized["name"]:
            raw = self._get_macro(existing_name)
            if raw and raw.get("source_file"):
                sanitized["source_file"] = raw["source_file"]

        try:
            warmup_stats = self._warmup_macro_tts_cache(sanitized)
        except Exception as e:
            return self._response_error(
                action,
                f"In player language: TTS preparation failed. Macro '{sanitized['name']}' was not saved: {e}",
                instructions="Inform the player in his language"
            )

        self._save_macro_definition(sanitized)
        creation_notice = ""
        if warmup_stats.get("audio_generated", 0) > 0 or warmup_stats.get("spoken_text_generated", 0) > 0:
            creation_notice = (
                f"Macro '{sanitized['name']}' is being created and speech files are prepared "
                f"({warmup_stats.get('audio_generated', 0)} new audio files)."
            )

        if sanitized.get("enabled", False):
            activate_result = self.activate_macro(sanitized["name"], persist_state=True)
            activate_result["macro"] = self._get_macro(sanitized["name"])
            activate_result["tts_warmup"] = warmup_stats
            if creation_notice:
                activate_result["creation_notice"] = creation_notice
                activate_result["instructions"] = (
                    "First tell the user immediately that the macro is being created and speech files are prepared. "
                    "Then confirm activation."
                )
            return activate_result

        response = self._response_success(
            action,
            f"Macro '{sanitized['name']}' saved.",
            macro=self._get_macro(sanitized["name"]),
            tts_warmup=warmup_stats,
            do_not_cache=True,
        )
        if creation_notice:
            response["creation_notice"] = creation_notice
            response["instructions"] = (
                "First tell the user immediately that the macro is being created and speech files are prepared. "
                "Then confirm the macro details."
            )
        return response

    def _sanitize_macro_definition(self, macro: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not isinstance(macro, dict):
            return None

        name = str(macro.get("name", "")).strip()
        if not name:
            return None

        macro_type = str(macro.get("type", "")).strip()
        if macro_type not in self.VALID_MACRO_TYPES:
            return None

        command_phrases = self._build_macro_command_phrases(
            name=name,
            custom_phrases=macro.get("command_phrases", {}),
        )

        sanitized = {
            "name": name,
            "type": macro_type,
            "enabled": bool(macro.get("enabled", False)),
            "play_beep": bool(macro.get("play_beep", self.default_play_beep)),
            "command_phrases": command_phrases,
            "source_file": macro.get("source_file"),
        }

        if macro_type == "interval_sequence":
            interval_seconds = max(float(macro.get("interval_seconds", self.min_interval_seconds)), self.min_interval_seconds)
            total_duration_seconds = macro.get("total_duration_seconds")
            if total_duration_seconds is not None:
                total_duration_seconds = max(float(total_duration_seconds), 0.1)
            steps = self._sanitize_steps(macro.get("steps", []))
            if not steps:
                return None
            sanitized["interval_seconds"] = interval_seconds
            sanitized["total_duration_seconds"] = total_duration_seconds
            sanitized["steps"] = steps

        elif macro_type == "countdown":
            dynamic_duration = bool(macro.get("dynamic_duration", False))
            raw_duration = macro.get("duration_seconds", self.default_timer_duration_seconds)
            try:
                duration_seconds = int(float(raw_duration))
            except (TypeError, ValueError):
                duration_seconds = 0
            if duration_seconds <= 0:
                if dynamic_duration:
                    duration_seconds = self.default_timer_duration_seconds
                else:
                    return None
            sanitized["dynamic_duration"] = dynamic_duration
            sanitized["duration_seconds"] = duration_seconds
            sanitized["text"] = self._clean_optional_text(macro.get("text")) or "Countdown finished."

        elif macro_type == "reminder":
            delay_seconds = int(float(macro.get("delay_seconds", 0)))
            if delay_seconds <= 0:
                return None
            reminder_text = self._clean_optional_text(macro.get("text"))
            if not reminder_text:
                return None
            sanitized["delay_seconds"] = delay_seconds
            sanitized["text"] = reminder_text

        elif macro_type == "beep_ticker":
            interval_seconds = max(float(macro.get("interval_seconds", self.min_interval_seconds)), self.min_interval_seconds)
            total_duration_seconds = macro.get("total_duration_seconds")
            if total_duration_seconds is not None:
                total_duration_seconds = max(float(total_duration_seconds), 0.1)
            sanitized["interval_seconds"] = interval_seconds
            sanitized["total_duration_seconds"] = total_duration_seconds
            sanitized["play_beep"] = True

        return sanitized

    def _sanitize_steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list):
            return []

        sanitized_steps = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue

            step_type = str(raw_step.get("type", "")).strip()
            if step_type not in ("key_press", "key_hold", "wait"):
                continue

            if step_type == "wait":
                wait_ms = raw_step.get("wait_ms", raw_step.get("duration_ms", 0))
                try:
                    wait_ms = int(float(wait_ms))
                except (TypeError, ValueError):
                    wait_ms = 0
                if wait_ms <= 0:
                    continue
                sanitized_steps.append({"type": "wait", "wait_ms": wait_ms})
                continue

            key = str(raw_step.get("key", "")).strip().lower()
            if not key:
                continue
            modifiers = raw_step.get("modifiers", [])
            if isinstance(modifiers, str):
                modifiers = [modifiers]
            if not isinstance(modifiers, list):
                modifiers = []
            normalized_modifiers = []
            for modifier in modifiers:
                normalized = self._normalize_modifier(modifier)
                if normalized:
                    normalized_modifiers.append(normalized)

            if step_type == "key_press":
                sanitized_steps.append(
                    {
                        "type": "key_press",
                        "key": key,
                        "modifiers": normalized_modifiers,
                    }
                )
                continue

            hold_ms = raw_step.get("hold_ms", raw_step.get("duration_ms", 0))
            try:
                hold_ms = int(float(hold_ms))
            except (TypeError, ValueError):
                hold_ms = 0
            if hold_ms <= 0:
                continue
            sanitized_steps.append(
                {
                    "type": "key_hold",
                    "key": key,
                    "hold_ms": hold_ms,
                    "modifiers": normalized_modifiers,
                }
            )

        return sanitized_steps

    def _save_macro_definition(self, macro_definition: dict[str, Any]):
        macro_to_store = dict(macro_definition)
        source_file = macro_to_store.get("source_file")
        if not source_file:
            source_file = f"{self._slugify(macro_definition['name'])}.json"
            macro_to_store["source_file"] = source_file

        file_path = self.macros_path / source_file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(macro_to_store, f, ensure_ascii=False, indent=2)

        with self._lock:
            self.macros[macro_to_store["name"]] = macro_to_store

    def load_macro_definitions(self):
        loaded_macros: dict[str, dict[str, Any]] = {}
        for macro_file in sorted(self.macros_path.glob("*.json")):
            try:
                with open(macro_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    raw["source_file"] = macro_file.name
                sanitized = self._sanitize_macro_definition(raw)
                if not sanitized:
                    printr.print_warn(f"Skipping invalid macro file: {macro_file.name}")
                    continue
                loaded_macros[sanitized["name"]] = sanitized
            except Exception as e:
                printr.print_warn(f"Could not load macro file '{macro_file.name}': {e}")

        created_defaults = self._ensure_default_macros(loaded_macros)
        with self._lock:
            self.macros = loaded_macros
        for macro in created_defaults:
            self._save_macro_definition(macro)

    def _ensure_default_macros(self, loaded_macros: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        created_defaults: list[dict[str, Any]] = []
        known_names = {self._normalize_text(name) for name in loaded_macros.keys()}

        for macro in self._default_macros():
            normalized_name = self._normalize_text(macro.get("name", ""))
            if not normalized_name or normalized_name in known_names:
                continue

            sanitized = self._sanitize_macro_definition(macro)
            if not sanitized:
                continue

            loaded_macros[sanitized["name"]] = sanitized
            known_names.add(normalized_name)
            created_defaults.append(sanitized)

        return created_defaults

    def _default_macros(self) -> list[dict[str, Any]]:
        afk_macro = {
            "name": self.DEFAULT_AFK_MACRO_NAME,
            "type": "interval_sequence",
            "interval_seconds": self.default_afk_interval_seconds,
            "total_duration_seconds": None,
            "steps": [
                {
                    "type": "key_press",
                    "key": "y",
                    "modifiers": [],
                }
            ],
            "play_beep": False,
            "enabled": False,
            "source_file": self.DEFAULT_AFK_SOURCE_FILE,
            "command_phrases": {
                "activate": [
                    "start afk",
                    "enable afk",
                    "afk on",
                ],
                "deactivate": [
                    "stop afk",
                    "disable afk",
                    "afk off",
                ],
            },
        }
        return [afk_macro]

    def _activate_enabled_macros_from_disk(self):
        macro_names = []
        with self._lock:
            for macro_name, macro in self.macros.items():
                if macro.get("enabled", False):
                    macro_names.append(macro_name)

        for macro_name in macro_names:
            self.activate_macro(macro_name, persist_state=False)

    def _list_macro_overview(self) -> list[dict[str, Any]]:
        with self._lock:
            overview = []
            for name, macro in self.macros.items():
                overview.append(
                    {
                        "name": name,
                        "type": macro.get("type"),
                        "enabled": bool(macro.get("enabled", False)),
                        "active": name in self.active_jobs,
                        "play_beep": bool(macro.get("play_beep", self.default_play_beep)),
                        "dynamic_duration": bool(macro.get("dynamic_duration", False)),
                        "command_phrases": macro.get("command_phrases", {}),
                    }
                )
            return sorted(overview, key=lambda item: item["name"].lower())

    def _get_macro(self, macro_name: str) -> Optional[dict[str, Any]]:
        resolved = self._resolve_macro_name(macro_name)
        if not resolved:
            return None
        with self._lock:
            macro = self.macros.get(resolved)
            return dict(macro) if macro else None

    def _resolve_macro_name(self, macro_name: str) -> Optional[str]:
        normalized = self._normalize_text(macro_name)
        if not normalized:
            return None
        with self._lock:
            for known_name in self.macros.keys():
                if self._normalize_text(known_name) == normalized:
                    return known_name
        return None

    def activate_macro(
        self,
        macro_name: str,
        persist_state: bool = True,
        runtime_macro: Optional[dict[str, Any]] = None,
    ):
        resolved_name = self._resolve_macro_name(macro_name)
        if not resolved_name:
            return self._response_error(
                "activate_macro",
                f"Macro '{macro_name}' not found.",
                instructions="Inform the player in his language"
            )

        with self._lock:
            if resolved_name in self.active_jobs:
                return self._response_success(
                    "activate_macro",
                    "Macro is already active.",
                    macro_name=resolved_name,
                    instructions="Inform the player in his language"
                )
            if len(self.active_jobs) >= self.max_active_macros:
                return self._response_error(
                    "activate_macro",
                    f"Cannot start macro. Maximum of {self.max_active_macros} active macros reached.",
                    instructions="Inform the player in his language"
                )
            macro = self.macros.get(resolved_name)
            if not macro:
                return self._response_error(
                    "activate_macro",
                    f"Macro '{resolved_name}' not found.",
                    instructions="Inform the player in his language"
                )

            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_macro_worker,
                args=(resolved_name, stop_event, runtime_macro),
                daemon=True,
                name=f"Macro-{resolved_name}",
            )
            self.active_jobs[resolved_name] = MacroRuntimeJob(
                name=resolved_name,
                stop_event=stop_event,
                thread=thread,
            )
            if persist_state:
                macro["enabled"] = True
                self._save_macro_definition(macro)

        thread.start()
        return self._response_success(
            "activate_macro",
            "Macro activated.",
            macro_name=resolved_name,
            instructions="Inform the player in his language"
        )

    def deactivate_macro(self, macro_name: str, persist_state: bool = True):
        resolved_name = self._resolve_macro_name(macro_name)
        if not resolved_name:
            with self._lock:
                active_named_macros = sorted(
                    [name for name in self.active_jobs.keys() if name in self.macros],
                    key=lambda item: item.lower(),
                )
                available_macros = sorted(self.macros.keys(), key=lambda item: item.lower())

            return self._response_error(
                "deactivate_macro",
                f"Macro '{macro_name}' not found.",
                requested_macro_name=macro_name,
                active_named_macros=active_named_macros,
                available_macros=available_macros,
                next_steps=[
                    "Inspect 'active_named_macros' and 'available_macros' from this tool response.",
                    "If exactly one suitable macro exists, call action 'deactivate_macro' for that macro.",
                    "If multiple suitable macros exist, ask the player which one should be deactivated.",
                ],
                instructions=(
                    "Respond in the player's language."
                ),
            )

        job: Optional[MacroRuntimeJob] = None
        with self._lock:
            job = self.active_jobs.get(resolved_name)
            macro = self.macros.get(resolved_name)
            if persist_state and macro:
                macro["enabled"] = False
                self._save_macro_definition(macro)

        if job:
            job.stop_event.set()
            if job.thread.is_alive():
                job.thread.join(timeout=1.5)
            with self._lock:
                self.active_jobs.pop(resolved_name, None)
            return self._response_success(
                "deactivate_macro",
                "Macro deactivated.",
                macro_name=resolved_name,
                instructions="Inform the player in his language",
                do_not_cache=True
            )

        return self._response_success(
            "deactivate_macro",
            "Macro is already inactive.",
            macro_name=resolved_name,
            instructions="Inform the player in his language",
            do_not_cache=True
        )

    def stop_all_macros(self, persist_state: bool = True) -> int:
        with self._lock:
            active_names = list(self.active_jobs.keys())
            if persist_state:
                macros_to_update = list(self.macros.values())
                for macro in macros_to_update:
                    macro["enabled"] = False
                    self._save_macro_definition(macro)

        for macro_name in active_names:
            if macro_name == self.RUNTIME_COUNTDOWN_JOB_NAME:
                self._stop_runtime_countdown_job()
            else:
                self.deactivate_macro(macro_name, persist_state=False)
        return len(active_names)

    def delete_macro(self, macro_name: str):
        resolved_name = self._resolve_macro_name(macro_name)
        if not resolved_name:
            return self._response_error("delete_macro", f"Macro '{macro_name}' not found.", instructions="Inform the player in his language")

        self.deactivate_macro(resolved_name, persist_state=False)

        macro = self._get_macro(resolved_name)
        if macro and macro.get("source_file"):
            file_path = self.macros_path / macro["source_file"]
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError as e:
                return self._response_error("delete_macro", f"Could not delete '{file_path.name}': {e}", instructions="Inform the player in his language")

        with self._lock:
            self.macros.pop(resolved_name, None)
        return self._response_success("delete_macro", f"Macro '{resolved_name}' deleted.", instructions="Inform the player in his language")

    def _run_macro_worker(
        self,
        macro_name: str,
        stop_event: threading.Event,
        runtime_macro: Optional[dict[str, Any]] = None,
    ):
        completed = False
        auto_disable_on_completion = False
        try:
            macro = dict(runtime_macro) if isinstance(runtime_macro, dict) else self._get_macro(macro_name)
            if not macro:
                return

            macro_type = macro.get("type")
            if macro_type in self.ONE_SHOT_TYPES:
                auto_disable_on_completion = True
            elif macro_type in ("interval_sequence", "beep_ticker") and macro.get("total_duration_seconds") is not None:
                auto_disable_on_completion = True

            if macro_type == "interval_sequence":
                completed = self._run_interval_sequence(macro, stop_event)
            elif macro_type == "countdown":
                if macro.get("play_beep", self.default_play_beep):
                    self._play_beep()
                completed = self._run_countdown(macro, stop_event)
            elif macro_type == "reminder":
                if macro.get("play_beep", self.default_play_beep):
                    self._play_beep()
                completed = self._run_reminder(macro, stop_event)
            elif macro_type == "beep_ticker":
                completed = self._run_beep_ticker(macro, stop_event)
        except Exception as e:
            printr.print_err(f"Macro '{macro_name}' failed: {e}")
        finally:
            with self._lock:
                self.active_jobs.pop(macro_name, None)
                if macro_name == self.RUNTIME_COUNTDOWN_JOB_NAME:
                    self._runtime_countdown_duration_seconds = None

            if completed and auto_disable_on_completion:
                with self._lock:
                    macro = self.macros.get(macro_name)
                    if macro:
                        macro["enabled"] = False
                        self._save_macro_definition(macro)

    def _run_interval_sequence(self, macro: dict[str, Any], stop_event: threading.Event) -> bool:
        interval_seconds = max(float(macro.get("interval_seconds", self.min_interval_seconds)), self.min_interval_seconds)
        total_duration_seconds = macro.get("total_duration_seconds")
        if total_duration_seconds is not None:
            total_duration_seconds = max(float(total_duration_seconds), 0.1)
        play_beep = bool(macro.get("play_beep", self.default_play_beep))
        contains_key_steps = self._macro_contains_key_steps(macro)

        started_at = time.monotonic()
        while not stop_event.is_set():
            if total_duration_seconds is not None:
                elapsed_total = time.monotonic() - started_at
                if elapsed_total >= total_duration_seconds:
                    return True

            loop_started_at = time.monotonic()
            if contains_key_steps and not self._is_star_citizen_window_active():
                if self.debug_mode:
                    printr.print_warn(
                        f"Macro '{macro.get('name', 'unknown')}' skipped one sequence because Star Citizen is not in foreground (debug_mode)."
                    )
                else:
                    printr.print_warn(
                        f"Macro '{macro.get('name', 'unknown')}' stopped: Star Citizen is not in foreground."
                    )
                    self._persist_macro_enabled_state(macro_name=macro.get("name"), enabled=False)
                    return False
                sleep_duration = interval_seconds
                if total_duration_seconds is not None:
                    remaining = max(0.0, total_duration_seconds - (time.monotonic() - started_at))
                    sleep_duration = min(sleep_duration, remaining)
                    if sleep_duration <= 0:
                        return True
                if not self._sleep_interruptible(sleep_duration, stop_event):
                    return False
                continue

            if play_beep:
                self._play_beep()
            self._execute_steps(macro.get("steps", []), stop_event)
            if stop_event.is_set():
                return False

            if total_duration_seconds is not None:
                elapsed_total = time.monotonic() - started_at
                if elapsed_total >= total_duration_seconds:
                    return True

            elapsed = time.monotonic() - loop_started_at
            sleep_duration = max(0.0, interval_seconds - elapsed)
            if total_duration_seconds is not None:
                remaining = max(0.0, total_duration_seconds - (time.monotonic() - started_at))
                sleep_duration = min(sleep_duration, remaining)
                if sleep_duration <= 0:
                    return True
            if not self._sleep_interruptible(sleep_duration, stop_event):
                return False
        return False

    def _run_countdown(self, macro: dict[str, Any], stop_event: threading.Event) -> bool:
        duration_seconds = int(macro.get("duration_seconds", 0))
        if duration_seconds <= 0:
            return False

        language_code = self._get_player_language_code()
        announcement_plan = self._build_countdown_announcement_plan(
            duration_seconds=duration_seconds,
            language_code=language_code,
        )

        end_timestamp = time.time() + duration_seconds
        last_remaining = duration_seconds
        announced_seconds = set()
        while not stop_event.is_set():
            remaining = max(0, int(end_timestamp - time.time()))

            # If timing drifts due to audio playback, still emit any missed announcements once.
            for second in range(last_remaining, remaining - 1, -1):
                if second in announced_seconds:
                    continue
                plan_entry = announcement_plan.get(second)
                if not plan_entry:
                    continue
                announced_seconds.add(second)
                self._speak_text(
                    text=plan_entry["text"],
                    priority=bool(plan_entry.get("priority", False)),
                )

            last_remaining = remaining
            if remaining <= 0:
                break

            if not self._sleep_interruptible(0.2, stop_event):
                return False

        if stop_event.is_set():
            return False

        final_text = self._clean_optional_text(macro.get("text")) or self._countdown_finished_text(language_code)
        self._speak_text(final_text, priority=False)
        return True

    def _run_reminder(self, macro: dict[str, Any], stop_event: threading.Event) -> bool:
        delay_seconds = int(macro.get("delay_seconds", 0))
        if delay_seconds <= 0:
            return False
        if not self._sleep_interruptible(delay_seconds, stop_event):
            return False
        reminder_text = self._clean_optional_text(macro.get("text"))
        if reminder_text:
            self._speak_text(reminder_text, priority=False)
        return True

    def _run_beep_ticker(self, macro: dict[str, Any], stop_event: threading.Event) -> bool:
        interval_seconds = max(float(macro.get("interval_seconds", self.min_interval_seconds)), self.min_interval_seconds)
        total_duration_seconds = macro.get("total_duration_seconds")
        if total_duration_seconds is not None:
            total_duration_seconds = max(float(total_duration_seconds), 0.1)
        started_at = time.monotonic()

        while not stop_event.is_set():
            if total_duration_seconds is not None:
                elapsed_total = time.monotonic() - started_at
                if elapsed_total >= total_duration_seconds:
                    return True
            self._play_beep()
            sleep_duration = interval_seconds
            if total_duration_seconds is not None:
                remaining = max(0.0, total_duration_seconds - (time.monotonic() - started_at))
                sleep_duration = min(sleep_duration, remaining)
                if sleep_duration <= 0:
                    return True
            if not self._sleep_interruptible(sleep_duration, stop_event):
                return False
        return False

    def _execute_steps(self, steps: list[dict[str, Any]], stop_event: threading.Event):
        for step in steps:
            if stop_event.is_set():
                return
            step_type = step.get("type")

            if step_type == "wait":
                wait_seconds = max(float(step.get("wait_ms", 0)) / 1000.0, 0.0)
                self._sleep_interruptible(wait_seconds, stop_event)
                continue

            if step_type in ("key_press", "key_hold"):
                hold_ms = int(step.get("hold_ms", 0)) if step_type == "key_hold" else 0
                self._execute_key_action(
                    key=str(step.get("key", "")).lower(),
                    modifiers=step.get("modifiers", []),
                    hold_ms=hold_ms,
                )

    def _execute_key_action(self, key: str, modifiers: list[str], hold_ms: int = 0):
        if not key:
            return

        if self.debug_mode:
            printr.print(
                f"[debug_mode] Macro key action: key={key}, modifiers={modifiers}, hold_ms={hold_ms}",
                tags="info",
            )
        if self.dry_run_key_actions:
            if self.debug_mode:
                printr.print(
                    "[debug_mode] Skipping physical key action because dry_run_key_actions is enabled.",
                    tags="info",
                )
            return

        normalized_modifiers = []
        for modifier in modifiers or []:
            normalized = self._normalize_modifier(modifier)
            if normalized:
                normalized_modifiers.append(normalized)

        mapped_key = self._normalize_key(key)
        if not mapped_key:
            return

        active_modifiers = []
        try:
            for modifier in normalized_modifiers:
                key_module.keyDown(modifier)
                active_modifiers.append(modifier)

            is_mouse, mouse_button = self._resolve_mouse_button(mapped_key)
            if is_mouse:
                if hold_ms > 0:
                    key_module.mouseDown(button=mouse_button)
                    time.sleep(hold_ms / 1000.0)
                    key_module.mouseUp(button=mouse_button)
                else:
                    key_module.click(button=mouse_button, duration=0.08)
                return

            if hold_ms > 0:
                key_module.keyDown(mapped_key)
                time.sleep(hold_ms / 1000.0)
                key_module.keyUp(mapped_key)
            else:
                key_module.press(mapped_key)
        except Exception as e:
            printr.print_warn(f"Macro key action failed for '{mapped_key}': {e}")
        finally:
            for modifier in reversed(active_modifiers):
                try:
                    key_module.keyUp(modifier)
                except Exception:
                    pass

    def _is_star_citizen_window_active(self) -> bool:
        if pygetwindow is None:
            return False
        try:
            active_window = pygetwindow.getActiveWindow()
            if not active_window:
                return False
            title = (active_window.title or "").lower()
            return "star citizen" in title
        except Exception:
            return False

    def _sleep_interruptible(self, seconds: float, stop_event: threading.Event) -> bool:
        if seconds <= 0:
            return not stop_event.is_set()
        interrupted = stop_event.wait(timeout=seconds)
        return not interrupted

    def _play_beep(self):
        if not self.beep_file.exists():
            return
        try:
            if self._beep_audio_bytes is None:
                with open(self.beep_file, "rb") as f:
                    self._beep_audio_bytes = f.read()
            if self._beep_audio_bytes:
                self.audio_player.play(self._beep_audio_bytes)
        except Exception as e:
            printr.print_warn(f"Could not play macro beep: {e}")

    def _speak_text(self, text: str, priority: bool = False):
        clean_text = (text or "").strip()
        if not clean_text:
            return False

        if not priority and self._is_audio_output_busy():
            printr.print_info(f"Skipping non-priority macro speech while other audio is playing: '{clean_text[:48]}'")
            return False

        if priority and self._is_audio_output_busy() and sd is not None:
            try:
                sd.stop()
            except Exception:
                pass

        audio_data = self._get_or_generate_tts_audio(clean_text)
        if not audio_data:
            printr.print_warn("Macro speech failed: no audio generated.")
            return False

        try:
            self.audio_player.stream_with_effects(audio_data, self.config, wait=True)
            return True
        except Exception as e:
            printr.print_warn(f"Could not play macro speech: {e}")
            return False

    @staticmethod
    def _countdown_step_seconds(duration_seconds: int) -> int:
        if duration_seconds < 5 * 60:
            return 60
        if duration_seconds < 15 * 60:
            return 5 * 60
        if duration_seconds < 30 * 60:
            return 10 * 60
        if duration_seconds < 60 * 60:
            return 30 * 60
        return 30 * 60

    def _build_countdown_announcement_plan(self, duration_seconds: int, language_code: str) -> dict[int, dict[str, Any]]:
        plan: dict[int, dict[str, Any]] = {}
        minute_step = self._countdown_step_seconds(duration_seconds)

        # Planned interval announcements, excluding the initial "full duration" to avoid overlap with start responses.
        for remaining in range(duration_seconds - 1, 0, -1):
            if remaining < 60:
                continue
            if remaining % minute_step != 0:
                continue
            minutes_left = remaining // 60
            plan[remaining] = {
                "text": self._countdown_minutes_left_text(minutes_left, language_code),
                "priority": False,
            }

        if duration_seconds > 30:
            plan[30] = {
                "text": self._countdown_thirty_seconds_text(language_code),
                "priority": False,
            }

        for number in range(10, -1, -1):
            if duration_seconds >= number:
                plan[number] = {
                    "text": self._countdown_number_text(number, language_code),
                    "priority": True,
                }

        return plan

    def _countdown_minutes_left_text(self, minutes_left: int, language_code: str) -> str:
        suffix = "minute" if minutes_left == 1 else "minutes"
        return f"{minutes_left} {suffix} remaining."

    def _countdown_thirty_seconds_text(self, language_code: str) -> str:
        return "30 seconds remaining."

    def _countdown_number_text(self, number: int, language_code: str) -> str:
        words_en = {
            0: "zero",
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine",
            10: "ten",
        }
        return words_en.get(number, str(number))

    def _countdown_finished_text(self, language_code: str) -> str:
        return "Countdown finished."

    def _get_player_language_code(self) -> str:
        player_language = str(self.config.get("openai", {}).get("player_language", "en_G")).strip().lower()
        if not player_language:
            return "en"
        return player_language.split("_")[0].split("-")[0] or "en"

    def _collect_tts_texts_for_macro(self, macro: dict[str, Any]) -> list[str]:
        macro_type = macro.get("type")
        language_code = self._get_player_language_code()

        if macro_type == "countdown":
            if bool(macro.get("dynamic_duration", False)):
                return []
            duration_seconds = int(macro.get("duration_seconds", 0))
            if duration_seconds <= 0:
                return []
            plan = self._build_countdown_announcement_plan(duration_seconds, language_code)
            ordered_seconds = sorted(plan.keys(), reverse=True)
            texts = [plan[second]["text"] for second in ordered_seconds if plan.get(second, {}).get("text")]
            final_text = self._clean_optional_text(macro.get("text")) or self._countdown_finished_text(language_code)
            texts.append(final_text)
            return texts

        if macro_type == "reminder":
            reminder_text = self._clean_optional_text(macro.get("text"))
            return [reminder_text] if reminder_text else []

        return []

    def _warmup_macro_tts_cache(self, macro: dict[str, Any]):
        texts = self._collect_tts_texts_for_macro(macro)
        if not texts:
            return {
                "total_texts": 0,
                "audio_generated": 0,
                "spoken_text_generated": 0,
            }

        # Keep order stable, dedupe exact text entries.
        seen = set()
        unique_texts = []
        for text in texts:
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            unique_texts.append(text)

        stats = {
            "total_texts": len(unique_texts),
            "audio_generated": 0,
            "spoken_text_generated": 0,
        }
        for text in unique_texts:
            _, audio_generated, spoken_text_generated = self._get_or_generate_tts_audio_meta(text)
            stats["audio_generated"] += int(bool(audio_generated))
            stats["spoken_text_generated"] += int(bool(spoken_text_generated))
        return stats

    def _is_audio_output_busy(self) -> bool:
        if sd is None:
            return False
        try:
            stream = sd.get_stream()
            return bool(stream and getattr(stream, "active", False))
        except Exception:
            return False

    def _get_or_generate_tts_audio(self, text: str) -> bytes:
        audio_data, _, _ = self._get_or_generate_tts_audio_meta(text)
        if not audio_data:
            raise RuntimeError("No TTS audio generated.")
        return audio_data

    def _get_or_generate_tts_audio_meta(self, text: str) -> tuple[Optional[bytes], bool, bool]:
        provider = str(self.config.get("features", {}).get("tts_provider", "openai")).lower()
        model = self._resolve_tts_model(provider)
        voice = self._resolve_tts_voice(provider)
        player_language = self.config.get("openai", {}).get("player_language", "de_DE")
        language_code = self._get_player_language_code()

        spoken_text, spoken_text_generated = self._get_or_prepare_spoken_text(
            text=text,
            language_code=language_code,
        )

        cache_key_source = f"{provider}|{model}|{voice}|{player_language}|{spoken_text}"
        cache_key = hashlib.sha256(cache_key_source.encode("utf-8")).hexdigest()
        cache_file = self.tts_cache_path / f"{cache_key}.wav"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return f.read(), False, spoken_text_generated
            except OSError:
                pass

        audio_data = self._generate_tts_audio(
            provider=provider,
            model=model,
            voice=voice,
            player_language=player_language,
            text=spoken_text,
        )
        if not audio_data:
            raise RuntimeError("TTS provider returned no audio data.")

        try:
            with open(cache_file, "wb") as f:
                f.write(audio_data)
        except OSError as e:
            printr.print_warn(f"Could not write macro TTS cache file '{cache_file.name}': {e}")
        return audio_data, True, spoken_text_generated

    def _get_or_prepare_spoken_text(self, text: str, language_code: str) -> tuple[str, bool]:
        clean_text = (text or "").strip()
        if not clean_text:
            return "", False

        cache_key_source = f"macro_spoken_text_v2|{language_code}|{clean_text}"
        cache_key = hashlib.sha256(cache_key_source.encode("utf-8")).hexdigest()
        with self._tts_text_cache_lock:
            cached = self._spoken_text_cache.get(cache_key)
            if cached:
                return cached, False

        spoken_text = self._prepare_spoken_text_with_model(clean_text, language_code).strip()
        if not spoken_text:
            raise RuntimeError("Spoken text generation returned empty output.")

        with self._tts_text_cache_lock:
            self._spoken_text_cache[cache_key] = spoken_text
            self._save_spoken_text_cache()
        return spoken_text, True

    def _prepare_spoken_text_with_model(self, text: str, language_code: str) -> str:
        system_prompt = (
            "You translate input text into a pronunciation safe script for TTS. "
            "Return only plain text, no quotes. "
            f"Target language: {language_code}. "
            "Rules: use only the target language and never mix languages. "
            "Spell numbers as words in target language. Example: '42' becomes 'forty-two' in English, 'zweiundvierzig' in German. "
            "Do not output any Arabic numerals (0-9). "
            "Spell isolated letters and key labels phonetically in target language. "
            "Keep sentence meaning unchanged and concise."
        )
        user_prompt = f"Input text:\n{text}"

        try:
            completion = self.ask_ai(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=256,
                temperature=0,
                response_format=None,
                llm_call="spoken_text_generation",
            )
            if completion is None:
                raise RuntimeError("Model returned no completion for spoken-text generation.")
            content = (completion.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Model returned empty spoken-text content.")
            return content
        except Exception as e:
            raise RuntimeError(f"Macro spoken-text generation failed: {e}") from e

    def _load_spoken_text_cache(self):
        if not self.tts_text_cache_file.exists():
            self._spoken_text_cache = {}
            return
        try:
            with open(self.tts_text_cache_file, "r", encoding="utf-8") as f:
                content = json.load(f)
            if isinstance(content, dict):
                self._spoken_text_cache = {str(key): str(value) for key, value in content.items()}
            else:
                self._spoken_text_cache = {}
        except Exception:
            self._spoken_text_cache = {}

    def _save_spoken_text_cache(self):
        try:
            with open(self.tts_text_cache_file, "w", encoding="utf-8") as f:
                json.dump(self._spoken_text_cache, f, ensure_ascii=False, indent=2)
        except OSError as e:
            printr.print_warn(f"Could not save spoken-text cache: {e}")

    def _resolve_tts_model(self, provider: str) -> str:
        if provider == "azure":
            return self.config.get("azure", {}).get("tts", {}).get("deployment_name", "tts-1")
        return self.config.get("openai", {}).get("tts_model", "tts-1")

    def _resolve_tts_voice(self, provider: str) -> str:
        if provider == "azure":
            return self.config.get("azure", {}).get("tts", {}).get("voice", "nova")
        return self.config.get("openai", {}).get("tts_voice", "nova")

    def _generate_tts_audio(
        self,
        provider: str,
        model: str,
        voice: str,
        player_language: str,
        text: str,
    ) -> bytes:
        if provider == "azure":
            return self._generate_azure_tts_audio(model=model, voice=voice, text=text)
        return self._generate_openai_tts_audio(model=model, voice=voice, player_language=player_language, text=text)

    def _generate_openai_tts_audio(self, model: str, voice: str, player_language: str, text: str) -> bytes:
        if self._openai_tts_client is None:
            self._openai_api_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="openai",
                friendly_key_name="OpenAI API key",
                prompt_if_missing=False,
            )
            if not self._openai_api_key:
                raise RuntimeError("OpenAI API key is required for macro TTS.")
            self._openai_tts_client = OpenAI(
                api_key=self._openai_api_key,
                organization=self.config.get("openai", {}).get("organization"),
                base_url=self.config.get("openai", {}).get("base_url"),
            )

        try:
            if model == "gpt-4o-mini-tts":
                instructions = self.config.get("openai", {}).get("tts_voice_instructions", "")
                instructions = (instructions or "") + f" You have to speak in the language with language-code: {player_language}."
                response = self._openai_tts_client.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=text,
                    instructions=instructions,
                )
            else:
                response = self._openai_tts_client.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=text,
                )
            audio_content = response.content if response else None
            if not audio_content:
                raise RuntimeError("OpenAI TTS returned empty audio.")
            return audio_content
        except APIStatusError as e:
            raise RuntimeError(f"OpenAI macro TTS failed ({e.status_code}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"OpenAI macro TTS failed: {e}") from e

    def _generate_azure_tts_audio(self, model: str, voice: str, text: str) -> bytes:
        if self._azure_tts_client is None:
            self._azure_tts_api_key = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_tts",
                friendly_key_name="Azure TTS API key",
                prompt_if_missing=False,
            )
            if not self._azure_tts_api_key:
                raise RuntimeError("Azure TTS API key is required for macro TTS.")
            azure_tts = self.config.get("azure", {}).get("tts", {})
            self._azure_tts_client = AzureOpenAI(
                api_key=self._azure_tts_api_key,
                azure_endpoint=azure_tts.get("api_base_url"),
                api_version=azure_tts.get("api_version"),
                azure_deployment=azure_tts.get("deployment_name"),
            )

        try:
            response = self._azure_tts_client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
            )
            audio_content = response.content if response else None
            if not audio_content:
                raise RuntimeError("Azure TTS returned empty audio.")
            return audio_content
        except APIStatusError as e:
            raise RuntimeError(f"Azure macro TTS failed ({e.status_code}): {e}") from e
        except Exception as e:
            raise RuntimeError(f"Azure macro TTS failed: {e}") from e

    def match_and_toggle_macro_by_phrase(self, transcript: str):
        normalized_transcript = self._normalize_text(transcript)
        if not normalized_transcript:
            return None
        self._debug_log(
            "phrase_match.begin",
            transcript=transcript,
            normalized_transcript=normalized_transcript,
        )

        if self._is_reload_phrase(normalized_transcript):
            self._debug_log("phrase_match.reload_detected", normalized_transcript=normalized_transcript)
            return self._reload_macros(source="instant_phrase")

        action_hint = self._extract_action_hint(normalized_transcript)

        if self._is_countdown_remaining_query(normalized_transcript):
            result = self.get_countdown_remaining()
            result["intent"] = "runtime_countdown_remaining"
            self._debug_log("phrase_match.countdown_remaining_query", result=result)
            return result

        best_match = None
        best_score = 0.0

        with self._lock:
            macros_snapshot = list(self.macros.values())

        for macro in macros_snapshot:
            macro_name = macro.get("name")
            phrase_config = macro.get("command_phrases", {})
            for action_name in ("activate", "deactivate"):
                if action_hint and action_name != action_hint:
                    continue
                for phrase in phrase_config.get(action_name, []):
                    normalized_phrase = self._normalize_text(phrase)
                    if not normalized_phrase:
                        continue

                    score = 0.0
                    if normalized_transcript == normalized_phrase:
                        score = 1.0
                    elif f" {normalized_phrase} " in f" {normalized_transcript} ":
                        score = 0.98
                    else:
                        score = SequenceMatcher(None, normalized_transcript, normalized_phrase).ratio()

                    if score >= self.PHRASE_MATCH_THRESHOLD and score > best_score:
                        best_score = score
                        best_match = {
                            "action": action_name,
                            "macro_name": macro_name,
                            "phrase": phrase,
                            "score": round(score, 4),
                        }

        if not best_match:
            self._debug_log("phrase_match.no_match", normalized_transcript=normalized_transcript)
            return None

        if best_match["action"] == "activate":
            result = self.activate_macro(best_match["macro_name"], persist_state=True)
        else:
            result = self.deactivate_macro(best_match["macro_name"], persist_state=True)

        result["match"] = best_match
        self._debug_log("phrase_match.match_applied", best_match=best_match, result=result)
        return result

    def _is_reload_phrase(self, normalized_transcript: str) -> bool:
        padded_transcript = f" {normalized_transcript} "
        for phrase in self.reload_command_phrases:
            normalized_phrase = self._normalize_text(phrase)
            if not normalized_phrase:
                continue
            if normalized_phrase == normalized_transcript:
                return True
            if f" {normalized_phrase} " in padded_transcript:
                return True

        has_macro_term = any(token in padded_transcript for token in (" macro ", " macros ", " makro ", " makros "))
        has_reload_term = any(token in padded_transcript for token in (" reload ", " neu laden ", " neu einlesen "))
        return has_macro_term and has_reload_term

    def _contains_timer_keyword(self, normalized_transcript: str) -> bool:
        padded_transcript = f" {normalized_transcript} "
        return any(f" {keyword} " in padded_transcript for keyword in self.TIMER_KEYWORDS)

    def _is_countdown_remaining_query(self, normalized_transcript: str) -> bool:
        padded = f" {normalized_transcript} "
        query_markers = (
            " remaining time ",
            " time left ",
            " how much time ",
        )
        has_query_marker = any(marker in padded for marker in query_markers)
        has_timer_context = self._contains_timer_keyword(normalized_transcript) or " countdown " in padded
        return has_query_marker and has_timer_context

    def _parse_duration_to_seconds(self, value: Any) -> Optional[int]:
        self._debug_log("duration_parse.input", raw_value=value)
        if not isinstance(value, str):
            self._debug_log("duration_parse.output", raw_value=value, parsed_seconds=None, reason="not_a_string")
            return None

        candidate = value.strip().lower()
        if not candidate:
            self._debug_log("duration_parse.output", raw_value=value, parsed_seconds=None, reason="empty_string")
            return None

        compact = re.sub(r"\s+", "", candidate)
        if not re.fullmatch(r"(?:\d+[hms]){1,3}", compact):
            self._debug_log(
                "duration_parse.output",
                raw_value=value,
                normalized=compact,
                parsed_seconds=None,
                reason="invalid_format",
            )
            return None

        total = 0
        seen_units = set()
        for number_text, unit in re.findall(r"(\d+)([hms])", compact):
            if unit in seen_units:
                return None
            seen_units.add(unit)
            amount = int(number_text)
            if amount < 0:
                return None
            if unit == "h":
                total += amount * 3600
            elif unit == "m":
                total += amount * 60
            else:
                total += amount

        parsed_seconds = total if total > 0 else None
        self._debug_log(
            "duration_parse.output",
            raw_value=value,
            normalized=compact,
            parsed_seconds=parsed_seconds,
            reason="ok" if parsed_seconds is not None else "zero_duration",
        )
        return parsed_seconds

    def _debug_log(self, event: str, **payload):
        if not self.debug_mode:
            return
        try:
            serialized_payload = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
        except Exception:
            serialized_payload = str(payload)
        printr.print(
            f"[MacroManager debug] {event}: {serialized_payload}",
            tags="info",
            console_only=True,
        )

    @staticmethod
    def _coerce_positive_seconds(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        return seconds

    def _format_duration_text(self, seconds: int) -> str:
        seconds = max(int(seconds), 0)
        hours, remainder = divmod(seconds, 3600)
        minutes, remaining_seconds = divmod(remainder, 60)

        parts = []
        if hours:
            parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        if remaining_seconds and not hours:
            parts.append(f"{remaining_seconds} {'second' if remaining_seconds == 1 else 'seconds'}")
        return " ".join(parts) or f"{seconds} seconds"

    @staticmethod
    def _format_duration_compact(seconds: int) -> str:
        seconds = max(int(seconds), 0)
        hours, remainder = divmod(seconds, 3600)
        minutes, sec = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if sec or not parts:
            parts.append(f"{sec}s")
        return " ".join(parts)

    def _build_macro_command_phrases(self, name: str, custom_phrases: Any) -> dict[str, list[str]]:
        spoken_name = self._humanize_macro_name(name)
        defaults = {
            "activate": [
                f"start {spoken_name}",
                f"enable {spoken_name}",
                f"turn on {spoken_name}",
            ],
            "deactivate": [
                f"stop {spoken_name}",
                f"disable {spoken_name}",
                f"turn off {spoken_name}",
            ],
        }

        if not isinstance(custom_phrases, dict):
            return defaults

        for action in ("activate", "deactivate"):
            configured = custom_phrases.get(action, [])
            if isinstance(configured, str):
                configured = [configured]
            if isinstance(configured, list):
                for phrase in configured:
                    phrase_text = str(phrase).strip()
                    if phrase_text:
                        defaults[action].append(phrase_text)

            defaults[action] = self._dedupe_phrases(defaults[action])
        return defaults

    @staticmethod
    def _extract_action_hint(normalized_transcript: str):
        if (
            "stop" in normalized_transcript
            or "turn off" in normalized_transcript
            or "disable" in normalized_transcript
            or "deactivate" in normalized_transcript
        ):
            return "deactivate"
        if (
            "start" in normalized_transcript
            or "turn on" in normalized_transcript
            or "enable" in normalized_transcript
            or "activate" in normalized_transcript
        ):
            return "activate"
        return None

    @staticmethod
    def _dedupe_phrases(phrases: list[str]) -> list[str]:
        deduped = []
        seen = set()
        for phrase in phrases:
            normalized = MacroManager._normalize_text(phrase)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(phrase.strip())
        return deduped

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = (text or "").lower().strip()
        normalized = re.sub(r"[^a-z0-9äöüß ]+", " ", lowered)
        return re.sub(r"\s+", " ", normalized).strip()

    def _macro_contains_key_steps(self, macro: dict[str, Any]) -> bool:
        for step in macro.get("steps", []):
            if isinstance(step, dict) and step.get("type") in ("key_press", "key_hold"):
                return True
        return False

    def _persist_macro_enabled_state(self, macro_name: Optional[str], enabled: bool):
        if not macro_name:
            return
        with self._lock:
            macro = self.macros.get(macro_name)
            if not macro:
                return
            macro["enabled"] = bool(enabled)
            self._save_macro_definition(macro)

    def _humanize_macro_name(self, name: str) -> str:
        text = self._normalize_text(name).replace("_", " ")
        replacements = [
            (" key press ", " key "),
            (" key hold ", " hold key "),
            ("macro ", ""),
        ]
        padded = f" {text} "
        for source, target in replacements:
            padded = padded.replace(source, target)
        humanized = re.sub(r"\s+", " ", padded).strip()
        return humanized or str(name).strip().lower()

    @staticmethod
    def _clean_optional_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @staticmethod
    def _slugify(text: str) -> str:
        normalized = MacroManager._normalize_text(text).replace(" ", "_")
        normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
        return normalized or "macro"

    def _normalize_modifier(self, modifier: Any) -> Optional[str]:
        if not isinstance(modifier, str):
            return None
        key = modifier.strip().lower()
        return self.SUPPORTED_MODIFIERS.get(key)

    def _normalize_key(self, key: str) -> Optional[str]:
        if not key:
            return None
        normalized = key.strip().lower()
        normalized = normalized.replace(" ", "_")
        mapped = self.sc_key_mappings.get(normalized, normalized)
        mapped = str(mapped).strip()
        if not mapped:
            return None

        canonical = mapped.lower().replace(" ", "_")
        if canonical in ("mouseleft", "mouse_left", "mouse1"):
            return "mouse_left"
        if canonical in ("mouseright", "mouse_right", "mouse2"):
            return "mouse_right"
        if canonical in ("mousemiddle", "mouse_middle", "mouse3"):
            return "mouse_middle"
        return mapped

    @staticmethod
    def _resolve_mouse_button(key: str) -> tuple[bool, str]:
        mapping = {
            "mouse_left": "left",
            "mouse_right": "right",
            "mouse_middle": "middle",
        }
        if key in mapping:
            return True, mapping[key]
        return False, ""

    @staticmethod
    def _response_success(action: str, message: str, **payload):
        response = {"success": True, "action": action, "message": message}
        response.update(payload)
        return response

    @staticmethod
    def _response_error(action: str, message: str, **payload):
        response = {"success": False, "action": action, "message": message, "do_not_cache": True}
        response.update(payload)
        return response

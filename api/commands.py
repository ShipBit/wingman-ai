from typing import Literal, Optional
from pydantic import BaseModel
from api.enums import (
    CommandTag,
    CoreState,
    KeyboardRecordingType,
    LogSource,
    LogType,
    RecordingDevice,
    ToastType,
)
from api.interface import AudioFile, CommandActionConfig, BenchmarkResult


# We use this Marker base class for reflection to "iterate all commands"
class WebSocketCommandModel(BaseModel):
    command: str


# RECEIVED FROM CLIENT


class ClientReadyCommand(WebSocketCommandModel):
    command: Literal["client_ready"] = "client_ready"


# TODO: make this a regular POST request
class SaveSecretCommand(WebSocketCommandModel):
    command: Literal["save_secret"] = "save_secret"
    secret_name: str
    secret_value: str
    show_message: Optional[bool] = True


class RecordKeyboardActionsCommand(WebSocketCommandModel):
    command: Literal["record_keyboard_actions"] = "record_keyboard_actions"
    recording_type: KeyboardRecordingType


class RecordMouseActionsCommand(WebSocketCommandModel):
    command: Literal["record_mouse_actions"] = "record_mouse_actions"


class RecordJoystickActionsCommand(WebSocketCommandModel):
    command: Literal["record_joystick_actions"] = "record_joystick_actions"


class StopRecordingCommand(WebSocketCommandModel):
    command: Literal["stop_recording"] = "stop_recording"
    recording_type: KeyboardRecordingType = KeyboardRecordingType.SINGLE
    recording_device: RecordingDevice = RecordingDevice.KEYBOARD


class ClientLoggedInCommand(WebSocketCommandModel):
    command: Literal["client_logged_in"] = "client_logged_in"
    plan: str
    account_name: str


class ClientLoggedOutCommand(WebSocketCommandModel):
    command: Literal["client_logged_out"] = "client_logged_out"


# SENT TO CLIENT


class LogCommand(WebSocketCommandModel):
    command: Literal["log"] = "log"
    text: str
    log_type: LogType
    source_name: Optional[str] = None
    wingman_name: Optional[str] = None
    source: LogSource = "system"
    tag: Optional[CommandTag] = None
    skill_name: Optional[str] = None
    additional_data: Optional[dict] = None
    benchmark_result: Optional[BenchmarkResult] = None


class PromptSecretCommand(WebSocketCommandModel):
    command: Literal["prompt_secret"] = "prompt_secret"
    requester: str
    secret_name: str


class ToastCommand(WebSocketCommandModel):
    command: Literal["toast"] = "toast"
    text: str
    toast_type: ToastType


class ActionsRecordedCommand(WebSocketCommandModel):
    command: Literal["actions_recorded"] = "actions_recorded"
    actions: list[CommandActionConfig]


class VoiceActivationMutedCommand(WebSocketCommandModel):
    command: Literal["voice_activation_muted"] = "voice_activation_muted"
    muted: bool


class McpStateChangedCommand(WebSocketCommandModel):
    """Sent when MCP server connection state changes (connected/disconnected)."""

    command: Literal["mcp_state_changed"] = "mcp_state_changed"
    wingman_name: str
    """The wingman whose MCP state changed."""


class AudioLibraryPlaybackFinishedCommand(WebSocketCommandModel):
    command: Literal["audio_library_playback_finished"] = (
        "audio_library_playback_finished"
    )
    audio_file: AudioFile


class CoreStateChangedCommand(WebSocketCommandModel):
    """Sent when the Core lifecycle state changes.

    The client should use this to update UI accordingly (show loading spinner,
    etc.). Note that if the Core crashes, it will NOT be able
    to send a state change - the client must detect WebSocket disconnection and
    failed /ping requests to determine that Core has crashed.
    """

    command: Literal["core_state_changed"] = "core_state_changed"
    state: CoreState
    """The current state of Wingman AI Core."""
    message: Optional[str] = None
    """Human-readable sub-step detail (e.g. 'Downloading Qwen3.5-2B...')."""
    progress: Optional[float] = None
    """0.0–1.0 progress for operations with known duration (e.g. downloads)."""


class ConversationCondensationCommand(WebSocketCommandModel):
    """Sent when conversation condensation starts or finishes for a wingman."""

    command: Literal["conversation_condensation"] = "conversation_condensation"
    wingman_name: str
    """The wingman whose conversation is being condensed."""
    status: str
    """'started' or 'finished'."""
    messages_condensed: Optional[int] = None
    """Number of messages that were condensed (only on finish)."""
    messages_remaining: Optional[int] = None
    """Number of messages remaining after condensation (only on finish)."""
    summary_length: Optional[int] = None
    """Character length of the summary (only on finish)."""
    estimated_tokens_saved: Optional[int] = None
    """Rough estimate of tokens saved by condensation (only on finish)."""
    summary_text: Optional[str] = None
    """The actual summary text (only on finish)."""


class ConversationTokenUsageCommand(WebSocketCommandModel):
    """Sent after each LLM call with actual API-reported token usage."""

    command: Literal["conversation_token_usage"] = "conversation_token_usage"
    wingman_name: str
    """The wingman that made the LLM call."""
    prompt_tokens: int
    """Tokens sent to the LLM (system prompt + history + tools)."""
    completion_tokens: int
    """Tokens in the LLM response."""
    is_local: bool = False
    """True for LOCAL_LLM provider (free, not billed)."""

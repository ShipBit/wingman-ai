from typing import Optional
from typing_extensions import Annotated, TypedDict
from pydantic import Base64Str, BaseModel, ConfigDict, Field, model_validator
from api.enums import (
    ConversationProvider,
    CoreState,
    ImageGenerationProvider,
    LocalAiMode,
    McpAuthType,
    McpTransportType,
    CustomPropertyType,
    TtsVoiceGender,
    SoundEffect,
    SttProvider,
    TtsProvider,
    WingmanInitializationErrorType,
    WingmanProTtsProvider,
    PerplexityModel,
)


class WingmanConfigFileInfo(BaseModel):
    name: str
    """"The name of this config used to display in the UI/Terminal, without file extension.

    Examples: Board Computer"""
    file: str
    """The actual name of the file in the file system (name + file extension).

    Examples: Board Computer.yaml"""
    is_deleted: bool
    """Deprecated - always False. Deleted wingman configs no longer exist in the
    file system; deletion state is tracked in configs/context.yaml.
    Kept for API client compatibility."""

    avatar: Annotated[str, Base64Str]
    """The avatar of the wingman or the default avatar if none is set. Encoded as base64 string."""


class ConfigDirInfo(BaseModel):
    name: str
    """"The name of this config used to display in the UI/Terminal.

    Examples: Star Citizen
    """
    directory: str
    """The actual name of the directory in the file system. Always equals name.

    Kept separate for API client compatibility."""
    is_default: bool
    """Whether this config is the default config that is used on launch
    (as tracked in configs/context.yaml)."""
    is_deleted: bool
    """Deprecated - always False. Deleted config dirs no longer exist in the
    file system; deletion state is tracked in configs/context.yaml.
    Kept for API client compatibility."""
    # TODO: icon(?)


class SystemCore(TypedDict):
    version: str
    cuda_available: bool
    gpu_name: Optional[str]
    is_dev: bool
    """True when Core runs from source (not a bundled/frozen build)."""


class SystemInfo(BaseModel):
    os: str
    core: SystemCore


class ChangelogEntry(BaseModel):
    """One published changelog entry, proxied from the public Canny RSS feed."""

    version: str
    """Entry title — our changelog entries are titled with the release version."""
    category: Optional[str] = None
    """Canny entry type: new, improved or fixed."""
    published_at: Optional[str] = None
    """Publication date as ISO string (YYYY-MM-DD)."""
    url: Optional[str] = None
    """Link to the full entry on Canny."""
    html: str
    """Entry body as HTML, authored on Canny."""
    unstable_only: bool = False
    """True for entries titled with an "(unstable)" marker on Canny — dev-build
    notes that clients only show to testers on the unstable update channel."""


class WingmanInitializationError(BaseModel):
    wingman_name: str
    message: str
    error_type: WingmanInitializationErrorType
    secret_name: Optional[str] = None


class CoreStatusResponse(BaseModel):
    """Response model for /ping endpoint providing detailed Core status."""

    state: CoreState
    """The current lifecycle state of Wingman AI Core."""
    message: Optional[str] = None
    """Human-readable sub-step detail for the current state."""
    progress: Optional[float] = None
    """0.0–1.0 progress for operations with known duration."""


class MicStatusResponse(BaseModel):
    """Current microphone / voice-activation state, published as the payload of the
    AudioPlayer.voice_events "changed" event (skill facade: audio.mic_status)."""

    state: str
    """off | muted | armed | held | paused. The one field that says it all; the
    booleans below are derived from it."""
    listening: bool
    """True when voice activation is on and the mic is not muted (nor paused for playback)."""
    muted: bool = False
    """True only when the user muted the mic (switch or hotkey). A held
    push-to-talk key or a speaking wingman does not count."""
    voice_activation_enabled: bool
    """Whether voice activation (vs push-to-talk) is configured."""
    playing: bool
    """True while a wingman is currently playing back audio (the mic is paused then)."""
    recording: bool
    """True while a push-to-talk / mouse / joystick key is held or a GUI mic toggle is active."""
    recording_wingman: Optional[str] = None
    """Name of the wingman currently being recorded, or None when not recording."""
    recording_wingman_avatar: Optional[str] = None
    """Local file path to the recording wingman's avatar (PNG), or None when not recording."""


class VoiceInfo(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[TtsVoiceGender] = None
    locale: Optional[str] = None
    languages: Optional[list[str]] = None
    provider: Optional[str] = None


# from sounddevice lib
class AudioDevice(BaseModel):
    name: str
    index: int
    hostapi: int
    max_input_channels: int
    max_output_channels: int
    default_low_input_latency: float
    default_low_output_latency: float
    default_high_input_latency: float
    default_high_output_latency: float
    default_samplerate: int


# CONFIG MODELS


class AudioDeviceSettings(BaseModel):
    hostapi: Optional[int] = 0
    name: str


class AudioSettings(BaseModel):
    input: Optional[int | AudioDeviceSettings] = None
    output: Optional[int | AudioDeviceSettings] = None


class XVASynthSettings(BaseModel):
    enable: bool
    host: str
    port: int
    install_dir: str
    """The path to your installation of XVASynth. Usually in your Steam installation directory."""
    process_device: str
    """Can be cpu or gpu. You may need to take additional steps to have XVASynth run on your GPU."""


class PocketTTSSettings(BaseModel):
    enable: bool
    run_locally: bool = True
    model: str = "english"
    quantize: bool = True
    host: str
    port: int


class PocketTTSPreloadResult(BaseModel):
    ok: bool
    voice: Optional[str] = None
    reason: Optional[str] = None


class ParakeetSettings(BaseModel):
    run_locally: bool = True
    model_variant: str
    """v2 (English) or v3 (Multilingual, 25 languages)"""
    execution_provider: str
    """cpu, directml, coreml, or cuda"""
    language: Optional[str] = None
    """Transcription language. Empty means auto-detect."""
    host: str = ""
    """Where a Parakeet server runs when `run_locally` is off. Empty until
    the user fills it in; nothing is contacted before that."""
    port: int = 9876


class ParakeetSttConfig(BaseModel):
    temperature: float


class ParakeetTranscript(BaseModel):
    text: str


class ElevenlabsLanguage(BaseModel):
    language_id: str
    name: str


class ElevenlabsModelMetadata(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    name: str
    can_be_finetuned: bool
    can_do_text_to_speech: bool
    can_do_voice_conversion: bool
    can_use_style: bool
    can_use_speaker_boost: bool
    serves_pro_voices: bool
    token_cost_factor: bool
    description: str
    requires_alpha_access: bool
    max_characters_request_free_user: int
    max_characters_request_subscribed_user: int
    maximum_text_length_per_request: int


class ElevenlabsModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    name: str
    model_id: str
    description: str
    max_characters: int
    cost_factor: int
    supported_languages: list[ElevenlabsLanguage]
    metadata: ElevenlabsModelMetadata


class ElevenlabsVoiceConfig(BaseModel):
    """You can either set a voice by name or by ID. If you set both, the ID will be used."""

    name: Optional[str] = None
    """You can configure "Premade voices" from the dropdown on https://elevenlabs.io/speech-synthesis by name.

    Might be overridden by id if both are set!
    """

    id: Optional[str] = None
    """To use a cloned or custom voice from their "Voice Library", copy it to your VoiceLab and paste the ID here.
    Only you(r) API key has acces to these voice IDs, so you can't share them.

    Overrides name if both are set!
    """


class ElevenlabsVoiceSettingsConfig(BaseModel):
    stability: Annotated[float, Field(strict=True, ge=0, le=1)]
    """0.0 - 1.0"""

    similarity_boost: Annotated[float, Field(strict=True, ge=0, le=1)]
    """0.0 - 1.0"""

    style: Annotated[float, Field(strict=True, ge=0, le=1)]
    """Not available for eleven_turbo_v2. 0.0 - 1.0"""

    use_speaker_boost: bool
    """Adds a delay to the playback"""


class ElevenlabsConfig(BaseModel):
    model: str
    """see https://elevenlabs.io/docs/speech-synthesis/models"""

    voice: ElevenlabsVoiceConfig
    voice_settings: ElevenlabsVoiceSettingsConfig
    output_streaming: bool
    use_tts_prompt: bool
    tts_prompt: str


class HumeVoiceConfig(BaseModel):
    id: str
    name: str
    provider: str


class HumeConfig(BaseModel):
    description: Optional[str] = None
    voice: HumeVoiceConfig


class InworldAudioConfig(BaseModel):
    audio_encoding: str
    """The audio encoding to use. Supported values: LINEAR16, MP3, OGG_OPUS, ALAW, MULAW"""
    bitrate: float
    """The bitrate to use for the audio encoding in bps. Default is 128k"""
    sample_rate_hertz: float
    """The synthesis sample rate (in hertz) for this audio. Accepts values within the range [8000, 48000]. Default is 48k"""
    streaming_sample_rate_hertz: int
    """The sample rate (in hertz) to use for streaming audio (LINEAR16 format). Accepts values within the range [8000, 48000]. Default is 24000 for good balance of quality and performance."""
    speaking_rate: float
    """Speaking rate/speed, in the range [0.5, 1.5]. 1.0 is the normal native speed supported by the specific voice. The default is 1.0."""


class InworldConfig(BaseModel):
    tts_endpoint: str
    model_id: str
    """inworld-tts-1, inworld-tts-1-max"""
    voice_id: str
    """The ID of the voice to use for synthesizing speech."""
    audio_config: InworldAudioConfig
    temperature: float
    """Determines the degree of randomness when sampling audio tokens to generate the response. Accepts values between 0 and 2. Defaults to 0.8"""
    output_streaming: bool
    use_tts_prompt: bool
    tts_prompt: str


class EdgeTtsConfig(BaseModel):
    voice: str
    """
    All available EdgeTTS voices: https://github.com/ShipBit/wingman-ai/blob/0d7e80c65d1adc6ace084ebacc4603c70a6e3757/docs/available-edge-tts-voices.md

    Voice samples: https://speech.microsoft.com/portal/voicegallery
    """


class PocketTTSConfig(BaseModel):
    voice: Optional[str] = None
    speed: float
    output_streaming: bool


class OpenAiCompatibleTtsConfig(BaseModel):
    api_key: str
    """Your local TTS provider probably won't need an API key, but if it does, you can set it here. The OpenAI client needs one to be initialized, so don't remove it even if you don't use it."""
    voice: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    speed: float
    output_streaming: bool
    use_tts_prompt: bool
    tts_prompt: str
    voices_endpoint: Optional[str] = None


class XVASynthVoiceConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_directory: str
    """The model (or game) directory in which your downloaded voice resides. The model directories are located in [xva-install-dir]/resources/app/models/."""
    voice_name: str
    """The name of the voice you downloaded to use (without file extension)"""
    language: str
    """The language the voice will speak in as 2-letter locale code. Some XVASynth voices are trained to be multilingual."""


class XVASynthTtsConfig(BaseModel):
    pace: float
    """The speed of the voice playback."""
    use_super_resolution: bool
    """Whether to use XVASynth's super resolution mode. Will take longer and generally not recommended."""
    use_cleanup: bool
    """Whether to use XVASynth's cleanup mode. May make voice quality better or worse depending on the voice model."""

    voice: XVASynthVoiceConfig


class OpenAiConfig(BaseModel):
    conversation_model: str
    """ The model to use for conversations aka "chit-chat" and for function calls.
    """

    tts_voice: str
    """The voice to use when generating the audio. Supported voices are alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer."""

    tts_model: str
    """One of the available TTS models: tts-1, tts-1-hd"""

    tts_speed: float
    """The speed of the generated audio. Select a value from 0.25 to 4.0. 1.0 is the default."""

    base_url: Optional[str] = None
    """ If you want to use a different API endpoint, uncomment this and configure it here.
    Use this to hook up your local in-place OpenAI replacement like Ollama or if you want to use a proxy.

    https://api.openai.com # or the localhost address of your local LLM etc.
    """

    organization: Optional[str] = None
    """If you have an organization key, you can set it here."""

    output_streaming: bool


class PromptConfig(BaseModel):
    system_prompt: str
    """The "context template" for the Wingman. Contains variables that will be replaced by the user (backstory) and/or skills."""

    backstory: Optional[str] = None
    """The backstory of the Wingman. Edit this to control how your Wingman should behave."""


class MistralConfig(BaseModel):
    conversation_model: str
    endpoint: str


class PerplexityConfig(BaseModel):
    conversation_model: PerplexityModel
    endpoint: str


class XaiConfig(BaseModel):
    conversation_model: str
    endpoint: str


class GroqConfig(BaseModel):
    conversation_model: str
    endpoint: str


class CerebrasConfig(BaseModel):
    conversation_model: str
    endpoint: str


class GoogleConfig(BaseModel):
    conversation_model: str


class OpenRouterConfig(BaseModel):
    conversation_model: str
    endpoint: str


class OpenRouterArchitecture(BaseModel):
    tokenizer: str
    instruct_type: Optional[str]
    modality: str


class OpenRouterEndpointPricing(BaseModel):
    request: Optional[str] = None
    image: Optional[str] = None
    prompt: Optional[str] = None
    completion: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    discount: Optional[float] = None


class OpenRouterEndpoint(BaseModel):
    name: str
    context_length: float
    pricing: OpenRouterEndpointPricing
    provider_name: str
    supported_parameters: Optional[list[str]] = None


class OpenRouterEndpointResult(BaseModel):
    id: str
    name: str
    created: float
    description: str
    architecture: OpenRouterArchitecture
    endpoints: list[OpenRouterEndpoint]


class LocalLlmConfig(BaseModel):
    conversation_model: Optional[str] = None
    endpoint: str


class WingmanProConfig(BaseModel):
    tts_provider: WingmanProTtsProvider

    conversation_deployment: str = ""
    """Gateway id of the chat model, or empty to follow the plan's default.

    Empty is the normal case. The backend resolves it to whatever the plan lists
    as default at that moment, so changing the default in /admin reaches every
    user without a release and without a migration. A concrete id here is a
    deliberate pick by the user; if the plan stops offering it, the backend
    serves its default instead of failing.
    """



class WingmanProSettings(BaseModel):
    base_url: str
    """Wingman backend. One region, so there is no endpoint to choose."""


class SoundConfig(BaseModel):
    play_beep: bool
    """adds a Beep/Quindar sound before and after the wingman talks"""

    play_beep_apollo: bool
    """adds a Apollo Beep sound before and after the wingman talks"""

    effects: list[SoundEffect]
    """You can put as many sound effects here as you want. They stack and are added in the defined order here."""

    volume: float
    """The volume for playback. 0.0 - 1.0"""


class VoiceActivationSettings(BaseModel):
    """Hands-free listening. Off means the user holds a wingman's record key.
    Which provider transcribes is not decided here but in ``SttSettings``:
    push-to-talk and voice activation share it."""

    enabled: bool
    """Whether to use voice activation or not. If you disable this, you need to use the record key to record your voice."""

    mute_toggle_key: str
    """If you want to use a key to toggle the microphone on/off, you can set it here. This is useful if you want to use voice activation but also want to be able to talk to other people without the Wingman interfering."""

    mute_toggle_key_codes: Optional[list[int]] = None

    sensitivity: float = 0.5
    """How easily the voice detector opens: 0 needs a clear voice, 1 opens on a
    whisper. Applies to push-to-talk too, where it trims silence off the clip."""

    end_pause_ms: int = 500
    """Silence that ends an utterance."""

    max_utterance_s: float = 160.0
    """Cut here even mid-sentence and send what was said; the rest becomes the
    next utterance. Keeps commands quick for people who never stop talking."""

    min_speech_ms: int = 200
    """Shorter bursts of speech are noise."""

    pre_roll_ms: int = 300
    """Audio kept from before the detector noticed speech."""

    listen_while_speaking: bool = False
    """Whether the microphone stays open while a wingman speaks, so "stop"
    cuts it off and talking on skips the answer. For headsets: through
    speakers the microphone hears the wingman itself, and the wingman then
    answers its own words or stops itself. Off means deaf while speaking."""

    stop_words: list[str] = ['stop', 'stopp', 'stop it', 'stop please', 'shut up', 'be quiet', 'silence', 'enough', 'halt', 'sei still', 'ruhe', 'schluss', 'bitte stopp', 'okay stop', 'basta', 'silencio', 'para', 'cállate', 'callate', 'arrête', 'arrete', 'tais-toi', 'assez', "stop s'il te plaît"]
    """Phrases that stop a wingman mid-sentence and are not answered. An
    utterance counts when every word in it comes from these phrases, so
    "okay stop please" works with "okay stop" and "stop please" listed."""


class VocabularyPreset(BaseModel):
    """A bundled word list for the speech correction, one per game."""

    id: str
    name: str
    count: int


class PresetOverride(BaseModel):
    """The user's edits to a bundled list, kept apart from it so an update of
    the bundled file still reaches them."""

    added: list[str] = []
    removed: list[str] = []


class SttTestResult(BaseModel):
    """What the microphone test in Settings heard."""

    text: str
    duration_s: float
    """Length of the recorded clip."""
    transcribe_ms: int = 0
    """How long the provider took to turn the clip into text."""
    level: float
    """Peak level of the clip, 0..1."""
    best_score: float
    """Best speech probability the detector saw, 0..1."""
    threshold: float


class SttSettings(BaseModel):
    """Speech-to-text, configured once for every wingman and for both ways of
    talking (record key and voice activation)."""

    provider: SttProvider

    languages: list[str]
    """Languages the cloud transcription may auto-detect, as BCP-47 tags such as
    en-US. Used by the Wingman backend; the local providers have their own
    language settings."""

    vocabulary: list[str] = []
    """Special words no speech model knows: place names, ship names, people.
    Every transcript is corrected against them afterwards, whatever the
    provider. The names of the active wingmen count without being listed."""

    presets: list[str] = ["star_citizen"]
    """Bundled word lists that apply on top of the user's own, by id
    ("star_citizen"). Switched on in Settings; the words stay in the bundled
    file and never enter the user's list."""

    preset_overrides: dict[str, PresetOverride] = {}
    """Per preset id: what the user added to and removed from the bundled list."""

    parakeet: ParakeetSettings
    parakeet_config: ParakeetSttConfig


class FeaturesConfig(BaseModel):
    """You can override various AI providers if your Wingman supports it. Our OpenAI wingman does!

    Note that the other providers may have additional config blocks. These are only used if the provider is set here.
    """

    tts_provider: TtsProvider
    conversation_provider: ConversationProvider
    image_generation_provider: ImageGenerationProvider
    use_generic_instant_responses: bool
    condense_conversation: bool
    """Enable automatic conversation condensation using the local support model.
    When enabled, older messages are automatically summarized when the conversation
    approaches the support model's context window capacity, saving tokens while
    preserving key information."""
    compress_tool_responses: bool
    """Let the support model summarize a tool/MCP response that is over the
    per-response cap (see ``skill_max_input_tokens``) instead of cutting it. Off, or
    with no support model ready, the response is cut structurally: whole JSON entries
    or whole lines, with a note saying what is missing. Responses under the cap are
    never touched either way."""
    condense_max_messages: int
    """Maximum number of user messages before forcing condensation, regardless of token count.
    Acts as a safety cap to prevent unbounded message list growth."""
    condense_keep_recent_tokens: int = 8000
    """How much recent history (in tokens) a condensation keeps verbatim. Whole turns,
    always at least the latest one. Older messages get condensed into the running
    summary. Capped at a third of what the support model can summarize in one pass."""
    skill_max_input_tokens: int = 16000
    """Max tokens skill-originated content may feed the main model at once: a
    ctx.ai.generate side-call, or a single tool/MCP response. The side-call cap is
    only enforced while ``condense_conversation`` is enabled; the tool-response cap is
    always on. Wingman Pro hardcodes a lower limit (8000) that users cannot change."""


class AudioFile(BaseModel):
    path: str
    """The audio file to play. Required."""

    name: str
    """The name of the audio file."""


class AudioFileConfig(BaseModel):
    files: list[AudioFile]
    """The audio file(s) to play. If there are multiple, a random file will be played."""

    volume: float
    """The volume to play the audio file at."""

    wait: bool
    """Whether to wait for the audio file to finish playing before continuing."""

    stop: Optional[bool] = None
    """Whether to stop instead of play the audio file. (Only stop or resume can be true)"""

    resume: Optional[bool] = None
    """Whether to resume instead of play from the last stopped audio file. (Only stop or resume can be true)"""


class CommandKeyboardConfig(BaseModel):
    hotkey: str
    """The hotkey. Can be a single key like 'a' or a combination like 'ctrl+shift+a'."""

    hotkey_codes: Optional[list[int]] = None
    """The hotkey codes. Can be a single key like 65 or a combination like 162+160+65. Optional."""

    hotkey_extended: Optional[bool] = None
    """Whether the hotkey is an extended key. Optional."""

    hold: Optional[float] = None
    """The duration the key will be pressed in seconds. Optional."""

    press: Optional[bool] = None
    """Whether to press the key. Optional."""

    release: Optional[bool] = None
    """Whether to release the key. Optional."""


class CommandMouseConfig(BaseModel):
    button: Optional[str] = None
    """The mouse button to press. Optional."""

    hold: Optional[float] = None
    """The duration the button will be pressed in seconds. Optional."""

    scroll: Optional[int] = None
    """The amount to scroll up (positive integer) or down (negative integer), example 10 or -10. Must have 'scroll' as key above to work."""

    move: Optional[list[int]] = None
    """The x, y coordinates to move to relative to the current mouse position, expected [x,y] format in yaml.  Must have associated button press to work."""

    move_to: Optional[list[int]] = None
    """The x, y coordinates to move the mouse to on the screen, expected [x,y] format in yaml.  Must have associated button press to work."""


class CommandJoystickConfig(BaseModel):
    button: Optional[int] = None
    """The joystick button to press. Optional."""

    name: Optional[str] = None
    """The joystick name to use. Optional."""

    guid: Optional[str] = None
    """The joystick GUID to use. Optional."""


class CommandSkillActionConfig(BaseModel):
    skill_name: str
    """The Skill class name that owns the @command_action function (e.g. 'Timer')."""
    function_name: str
    """The @command_action method name to invoke."""
    parameters: Optional[dict] = None
    """Static parameter values for the function, keyed by parameter name."""


class CommandActionConfig(BaseModel):
    keyboard: Optional[CommandKeyboardConfig] = None
    """The keyboard configuration for this action. Optional."""

    wait: Optional[float] = None
    """Wait time in seconds before pressing the next key. Optional."""

    mouse: Optional[CommandMouseConfig] = None
    """The mouse configuration for this action. Optional."""

    write: Optional[str] = None
    """The word or phrase to type, for example, to type text in a login screen.  Must have associated button press to work.  May need special formatting for special characters."""

    audio: Optional[AudioFileConfig] = None
    """The audio file to play. Optional."""

    joystick: Optional[CommandJoystickConfig] = None
    """The joystick configuration for this action. Optional."""

    skill_action: Optional[CommandSkillActionConfig] = None
    """Invoke a skill's @command_action function with static parameters. Optional."""


class CommandCategoryConfig(BaseModel):
    """Configuration for a command category."""

    id: str
    """Unique identifier for the category (UUID)."""

    name: str
    """Display name of the category."""


class CommandConfig(BaseModel):
    name: str
    """This is where the magic happens!
    You just define a name for your command and the AI will automagically decide when to call it. Not kidding!
    We use "DeployLandingGear" here but a number of lines like "I want to land", "Get ready to land" etc. will also work.
    If the Wingman doesn't call your command, try to rephrase the name here.
    """
    category_id: Optional[str] = None
    """Optional category ID to group commands."""
    is_system_command: Optional[bool] = False
    """Whether this is a system command that cannot be deleted or edited by the user."""
    instant_activation: Optional[list[str]] = None
    """Optional: Faster - like Voice Attack! Provide phrases that will instantly activate the command (without AI roundtripping). You need to say the exact phrase to execute the command"""
    force_instant_activation: Optional[bool] = False
    """Optional: If true, the command will only be executed if the exact phrase is said. If false, the command will be executed if the exact phrase is said, or if the AI thinks it makes sense based on name and context."""
    responses: Optional[list[str]] = None
    """Optional: Provide responses that will be used when the command is executed. A random one will be chosen (if multiple)."""
    additional_context: Optional[str] = None
    """Optional: Provide additional context for the LLM after command execution."""
    actions: Optional[list[CommandActionConfig]] = None
    """The actions to execute when the command is called. You can use keyboard, mouse and wait actions here."""


class CustomClassConfig(BaseModel):
    module: str
    """Where your code is located. Use '.' as path separator!"""

    name: str
    """The name of your class within your file/module."""


class LabelValuePair(BaseModel):
    label: str
    value: str | int | float | bool


class VoiceSelection(BaseModel):
    provider: TtsProvider
    subprovider: Optional[WingmanProTtsProvider] = None
    voice: str | ElevenlabsVoiceConfig | XVASynthVoiceConfig | HumeVoiceConfig

    @model_validator(mode="before")
    def check_voice_config(cls, values):

        def __parse_voice(provider: any, voice: any):
            if provider == "elevenlabs":
                return ElevenlabsVoiceConfig.model_validate(voice)
            if provider == "xvasynth":
                return XVASynthVoiceConfig.model_validate(voice)
            if provider == "hume":
                return HumeVoiceConfig.model_validate(voice)
            return str(voice)

        if isinstance(values, list):
            for value in values:
                value["voice"] = __parse_voice(
                    value.get("provider"), value.get("voice")
                )
        else:
            values["voice"] = __parse_voice(values.get("provider"), values.get("voice"))

        return values


class CustomProperty(BaseModel):
    id: str
    """The name of the property. Has to be unique"""
    name: str
    """The "friendly" name of the property, displayed in the UI."""
    value: (
        str
        | int
        | float
        | bool
        | list[int | float]
        | VoiceSelection
        | list[VoiceSelection]
        | AudioFileConfig
        | Optional[int | AudioDeviceSettings]
    )
    """The value of the property"""
    property_type: CustomPropertyType
    """Determines the type of the property and which controls to render in the UI."""
    hint: Optional[str] = None
    """A hint for the user, displayed in the UI."""
    required: Optional[bool] = False
    """Marks the property as required in the UI."""
    options: Optional[list[LabelValuePair]] = None
    """If property_type is set to 'single_select', you can provide options here. May also hold meta information for other property types like "multiple" for voice_selection."""


class LocalizedMetadata(BaseModel):
    en: str
    de: Optional[str] = None
    es: Optional[str] = None
    fr: Optional[str] = None


class SkillConfig(CustomClassConfig):
    display_name: str
    author: Optional[str] = None
    tags: Optional[list[str]] = None
    description: LocalizedMetadata
    prompt: Optional[str] = None
    """An additional prompt that extends the system prompt of the Wingman."""
    custom_properties: Optional[list[CustomProperty]] = None
    """You can add custom properties here to use in your custom skill class."""
    hint: Optional[LocalizedMetadata] = None
    examples: Optional[list[LocalizedMetadata]] = None
    platforms: Optional[list[str]] = None
    """List of supported platforms: 'windows', 'darwin' (macOS), 'linux'. If None, skill works on all platforms."""
    auto_activate: Optional[bool] = False
    """If True, this skill's tools are always available without LLM activation.
    Use for event-driven skills or skills that should always be active when enabled.
    Auto-activated skills are hidden from activate_skill and don't need LLM activation."""
    discoverable_by_default: Optional[bool] = True
    """Whether this skill is discoverable by default when creating new wingmen.
    Set to False for specialized skills that most users won't need immediately.
    Users can still make skills discoverable per wingman."""
    discovery_keywords: Optional[list[str]] = None
    """Optional keywords to help LLMs discover this skill during activation.

    Guidelines:
    1. Use ONLY if description + tags aren't enough for discovery
    2. Focus on terms users might say (not developer jargon)
    3. Include alternate names, specific examples, common queries
    4. Keep it concise - 5-10 keywords is usually enough
    5. Always in English only

    Examples:
    - ['trading', 'routes', 'cargo', 'commodities', 'ships']
    - ['screenshots', 'OCR', 'image analysis', 'text recognition']
    - ['flight simulator', 'altitude', 'speed', 'autopilot', 'navigation']
    """
    api_version: Optional[int] = None
    """Skill API contract version. Declares which version of the Skill base class +
    WingmanContext facade this skill targets. Independent of the Wingman app version —
    it only changes when the skill-facing contract makes a breaking change. Skills
    without this field are treated as legacy (pre-v3) and are not loaded. Current: 3."""
    version: Optional[str] = None
    """Optional skill release version (free-form, e.g. '2.0.1'). Used for telemetry only."""


class SkillToolInfo(BaseModel):
    """Basic info about a tool in a skill."""

    name: str
    """The tool's function name."""

    description: str
    """Brief description of what the tool does."""


class SkillBase(BaseModel):
    name: str
    config: SkillConfig
    logo: Optional[Annotated[str, Base64Str]] = None
    tools: Optional[list[SkillToolInfo]] = None
    """List of tools provided by this skill."""

    is_custom: bool = False
    """Whether this skill is a custom (user-installed) skill from custom_skills directory."""

    is_local: bool = False
    """Whether this skill is a local/in-development skill in the source skills dir (not git-tracked).
    Only True in dev mode for skills that exist in ./skills/ but are not committed to git."""

    folder_name: str = ""
    """The skill's directory name on disk (e.g. 'heads_up'). May differ from 'name' (the class name)."""


class WingmanSkillState(BaseModel):
    """Skill info with enabled/disabled state for a specific wingman."""

    skill: SkillBase
    """The skill configuration and metadata."""

    is_enabled: bool
    """Whether the skill is enabled for this wingman (in discoverable_skills list)."""


# ─────────────────────────────── MCP Configuration ─────────────────────────────── #


class McpServerConfig(BaseModel):
    """Configuration for an MCP (Model Context Protocol) server connection."""

    name: str
    """Unique identifier for this MCP server (e.g., 'context7', 'docker'). Used as key for secrets."""

    display_name: str
    """Human-readable name shown in the UI."""

    description: Optional[str] = None
    """Brief description of what this MCP server provides."""

    type: McpTransportType
    """Transport type: 'http' for hosted servers, 'stdio' for local processes, 'sse' for Server-Sent Events."""

    # HTTP/SSE transport settings
    url: Optional[str] = None
    """URL for HTTP or SSE transports (e.g., 'https://mcp.context7.com/mcp')."""

    headers: Optional[dict[str, str]] = None
    """Optional headers for HTTP requests. API keys should use SecretKeeper with 'mcp_<name>' prefix."""

    auth: McpAuthType = McpAuthType.API_KEY
    """How to authenticate against this server.

    Defaults to API_KEY, which is what every server did before 3.2.1 and costs
    nothing when no secret is stored: the bearer header is only added if the
    secret `mcp_<name>` exists. OAUTH runs an authorization code grant instead.
    """

    oauth_client_id: Optional[str] = None
    """OAuth client id to use instead of registering one dynamically.

    Leave empty for servers that support Dynamic Client Registration (RFC 7591) —
    the usual case, and Wingman registers itself on first use. Set it for servers
    that have no registration endpoint, such as ElevenLabs, which expects a
    client id metadata document URL here.
    """

    oauth_scopes: Optional[list[str]] = None
    """OAuth scopes to request. Empty means whatever the server grants by default."""

    disabled_tools: Optional[list[str]] = None
    """Tool names (as the server reports them) that are hidden from the model.

    Every tool a server offers is still listed in the UI, but a disabled one is
    left out of the prompt and cannot be called. Empty means everything is on.

    This matters for size: a server's tool definitions go into the prompt in
    full once the server is activated, and some servers are far too large for
    that. ElevenLabs offers 111 tools whose schemas come to roughly 222,000
    tokens; the seven a voice assistant needs come to about 6,800.
    """

    # STDIO transport settings
    command: Optional[str] = None
    """Command to run for stdio transport (e.g., 'docker', 'python', 'npx')."""

    args: Optional[list[str]] = None
    """Arguments for the command (e.g., ['mcp', 'gateway', 'run'])."""

    env: Optional[dict[str, str]] = None
    """Environment variables to set for the process."""

    timeout: Optional[int] = None
    """Connection timeout in seconds. Defaults to 30s for HTTP/SSE, 60s for stdio."""

    # Common settings
    discoverable_by_default: bool = False
    """Whether this MCP server is discoverable by default for new wingmen.
    Set to False for specialized MCP servers that most users won't need immediately.
    Users can still make MCP servers discoverable per wingman."""

    # Optional metadata
    version: Optional[str] = None
    """Version of the MCP server, if known."""

    discovery_keywords: Optional[list[str]] = None
    """Optional keywords to help LLMs discover this MCP server during activation.

    Guidelines:
    1. Use ONLY if description isn't enough for discovery
    2. Focus on terms users might say (not technical jargon)
    3. Include alternate names, specific use cases, common queries
    4. Keep it concise - 5-10 keywords is usually enough
    5. Always in English only

    Examples:
    - ['web search', 'internet', 'Google', 'research', 'find information']
    - ['documentation', 'API docs', 'library reference', 'code examples']
    - ['Docker containers', 'images', 'compose', 'Kubernetes', 'registry']
    """


class McpToolInfo(BaseModel):
    """Information about a tool provided by an MCP server."""

    name: str
    """The tool's function name as provided by the MCP server."""

    prefixed_name: str
    """The prefixed tool name used internally (e.g., 'mcp_context7_resolve_library')."""

    description: str
    """Description of what the tool does."""

    server_name: str
    """Name of the MCP server that provides this tool."""

    input_schema: Optional[dict] = None
    """JSON Schema for the tool's input parameters."""

    is_enabled: bool = True
    """False when the tool is in the server's `disabled_tools` list."""


class McpServerState(BaseModel):
    """MCP server info with connection state for a specific wingman."""

    config: McpServerConfig
    """The MCP server configuration."""

    is_enabled: bool
    """Whether the MCP server is enabled for this wingman (in discoverable_mcps list)."""

    is_connected: bool
    """Whether the server is currently connected."""

    tools: Optional[list[McpToolInfo]] = None
    """List of tools provided by this server when connected."""

    error: Optional[str] = None
    """Error message if connection failed."""

    oauth: Optional["McpOAuthStatus"] = None
    """OAuth state, present only for servers whose auth is 'oauth'."""


class McpOAuthStatus(BaseModel):
    """Whether Wingman holds a usable OAuth token for an MCP server."""

    server_name: str
    """The MCP server this status belongs to."""

    is_authorized: bool
    """True when a token is stored. It may still be expired — see `is_expired`."""

    is_expired: bool = False
    """True when the stored access token has passed its expiry.

    Not fatal on its own: a refresh token, when the server issued one, renews it
    silently on the next request.
    """

    can_refresh: bool = False
    """True when a refresh token is stored, so an expired token renews itself."""

    scopes: Optional[list[str]] = None
    """Scopes the server granted, as reported in the token response."""

    expires_at: Optional[float] = None
    """Unix timestamp the access token expires at, if the server said."""


class McpOAuthStartResult(BaseModel):
    """Result of asking Core to begin an OAuth flow."""

    success: bool
    """False when the URL could not be built — see `error`."""

    server_name: str
    """The MCP server the flow belongs to."""

    authorization_url: Optional[str] = None
    """The consent page to open in the user's browser."""

    error: Optional[str] = None
    """Why the flow could not be started."""


# McpServerState refers to McpOAuthStatus before it exists, so the reference has
# to be resolved once both are defined.
McpServerState.model_rebuild()


class TestConnectionResult(BaseModel):
    """Result of testing a provider connection."""

    success: bool
    """Whether the connection test succeeded."""

    provider: str
    """The provider/secret name that was tested."""

    error: Optional[str] = None
    """Error message if the test failed."""


class McpConnectResult(BaseModel):
    """Result of attempting to connect to an MCP server."""

    success: bool
    """Whether the connection was successful."""

    server_name: str
    """The MCP server name that was connected."""

    tools: Optional[list[McpToolInfo]] = None
    """List of tools provided by this server if connection succeeded."""

    error: Optional[str] = None
    """Error message if connection failed."""


class McpConfig(BaseModel):
    """Central MCP configuration loaded from mcp.yaml.

    This defines all available MCP servers that any Wingman can use.
    Individual Wingmen control which servers are discoverable using their discoverable_mcps list.
    """

    servers: list[McpServerConfig] = []
    """List of all available MCP server configurations."""


class NestedConfig(BaseModel):
    prompts: PromptConfig
    sound: SoundConfig
    features: FeaturesConfig
    openai: OpenAiConfig
    mistral: MistralConfig
    groq: GroqConfig
    cerebras: CerebrasConfig
    google: GoogleConfig
    openrouter: OpenRouterConfig
    local_llm: LocalLlmConfig
    edge_tts: EdgeTtsConfig
    openai_compatible_tts: OpenAiCompatibleTtsConfig
    elevenlabs: ElevenlabsConfig
    hume: HumeConfig
    inworld: InworldConfig
    xvasynth: XVASynthTtsConfig
    pocket_tts: PocketTTSConfig
    wingman_pro: WingmanProConfig
    perplexity: PerplexityConfig
    xai: XaiConfig
    commands: Optional[list[CommandConfig]] = None
    command_categories: Optional[list[CommandCategoryConfig]] = None
    skills: Optional[list[SkillConfig]] = None
    """User's skill configuration overrides. Skills not listed here use defaults."""

    discoverable_skills: list[str] = []
    """List of skill names that are discoverable to the LLM for this wingman.
    This is a whitelist - only skills in this list are available at runtime.
    Empty list means no skills are discoverable.
    Example: ["ConversationStarter", "AutoScreenshot"] to make only these skills available."""

    discoverable_mcps: list[str] = []
    """List of MCP server names that are discoverable to the LLM for this wingman.
    This is a whitelist - only MCP servers in this list are available at runtime.
    Empty list means no MCP servers are discoverable.
    Example: ["wingman_date_time", "wingman_starhead"] to make only these MCPs available."""

    disabled_skill_tools: list[str] = []
    """Skill tool names this wingman hides from the model.

    A skill stays enabled, but a tool listed here is left out of the prompt and
    cannot be called. Tool names are unique across skills, so no skill prefix is
    needed. Empty means every tool of every enabled skill is on.
    """


class WingmanConfig(NestedConfig):
    def __getitem__(self, item):
        return self.extra_properties.get(item)

    def __setitem__(self, key, value):
        self.extra_properties[key] = value

    custom_properties: Optional[list[CustomProperty]] = None
    """You can add custom properties here to use in your custom wingman class."""

    disabled: Optional[bool] = False
    """Set this to true if you want to disable this wingman. You can also just remove it from the config."""

    custom_class: Optional[CustomClassConfig] = None
    """If you want to use a custom Wingman (Python) class, you can specify it here."""
    name: str
    """The "friendly" name of this Wingman. Can be changed by the user."""
    description: Optional[str] = None
    """A short description of this Wingman."""
    record_key: Optional[str] = None
    """The "push-to-talk" key for this wingman. Keep it pressed while talking! Don't use the same key for multiple wingmen!"""
    record_key_codes: Optional[list[int]] = None
    """The "push-to-talk" key code for this wingman. Keep it pressed while talking! Don't use the same key for multiple wingmen!"""
    record_mouse_button: Optional[str] = None
    """The "push-to-talk" mouse button for this wingman. Keep it pressed while talking! Don't use the same button for multiple wingmen!"""
    record_joystick_button: Optional[CommandJoystickConfig] = None
    """The "push-to-talk" joystick config for this wingman. Keep it pressed while talking! Don't use the same button for multiple wingmen!"""
    is_voice_activation_default: Optional[bool] = None
    """If voice activation is enabled and this is true, the Wingman will listen to your voice by default and without saying its name."""
    persistent_memory: bool = True
    """Enable persistent memory — automatically remember and recall facts across sessions using local AI."""
    created_with_version: Optional[str] = None
    """The version of Wingman AI that created this configuration. Used to detect configs that may benefit from restoring updated defaults."""


class Config(NestedConfig):
    """You can override these default settings for each wingman.
    If you do that, make sure you keep the "hierarchy" of the config intact.
    """

    wingmen: Optional[dict[str, WingmanConfig]] = None
    """The Wingmen in this config. You can add as many as you want!"""


class MemoryEntryResponse(BaseModel):
    """A persistent memory entry returned from the API."""

    id: int
    collection: str
    entry_type: str
    content: str
    source_wingman: Optional[str] = None
    session_id: Optional[str] = None
    created_at: float
    updated_at: float


class MemoryUpdateRequest(BaseModel):
    """Request to update a memory entry's content."""

    content: str


class ConfigsInfo(BaseModel):
    config_dirs: list[ConfigDirInfo]
    current_config_dir: ConfigDirInfo


class ConfigWithDirInfo(BaseModel):
    config: Config
    config_dir: ConfigDirInfo


class NewWingmanTemplate(BaseModel):
    wingman_config: WingmanConfig
    avatar: Annotated[str, Base64Str]


class DuplicateWingmanRequest(BaseModel):
    """Request payload for duplicating a Wingman into a target config/context."""

    source_config_dir: ConfigDirInfo
    source_wingman_file: WingmanConfigFileInfo
    target_config_dir: ConfigDirInfo
    new_name: str


class DuplicateWingmanResult(BaseModel):
    """Result of a Wingman duplication request."""

    config_dir: ConfigDirInfo
    wingman_file: WingmanConfigFileInfo


class DuplicateConfigRequest(BaseModel):
    """Request payload for duplicating an entire config/context."""

    source_config_dir: ConfigDirInfo
    new_name: str


class HudServerSettings(BaseModel):
    """HUD Server settings for global configuration."""

    enabled: bool
    """Whether the HUD server should auto-start with Wingman AI Core."""

    host: str
    """The interface to listen on. Use '127.0.0.1' for local only, '0.0.0.0' for LAN access."""

    port: int
    """The port to listen on."""

    framerate: int
    """HUD overlay rendering framerate. Higher = smoother but more CPU. Minimum 1."""

    layout_margin: int
    """Margin from screen edges in pixels for HUD elements. Between 0 and 200."""

    layout_spacing: int
    """Spacing between stacked HUD windows in pixels. Between 0 and 100."""

    screen: int
    """Which screen/monitor to render the HUD on (1 = primary, 2 = secondary, etc.)."""


class DetectContextSizeRequest(BaseModel):
    host: str
    port: int


class PlaygroundChatRequest(BaseModel):
    system_message: str
    user_message: str
    temperature: float = 1.0
    top_p: float = 1.0
    top_k: int = 20
    presence_penalty: float = 2.0
    reasoning: bool = False
    iterations: int = 1


class MemorySuiteRequest(BaseModel):
    scenario_id: str
    samples: int = 1


class LlamaCppSettings(BaseModel):
    mode: LocalAiMode = LocalAiMode.CLOUD
    """Where the support model runs: on our backend, on this machine, or on a
    llama-server the user runs elsewhere. Replaced the old `run_locally` flag,
    which could only say local or remote."""
    support_cloud_model: str = ""
    """Gateway id of the cloud support model, empty means the plan's default.

    Deliberately free text rather than an enum: the list lives in the backend and
    changes without a Wingman release. An id the plan no longer offers is not an
    error — the backend answers with the plan default and says so."""
    gpu_backend: str = "cpu"
    """GPU backend for llama-server: 'cpu' (default), 'vulkan' (works on all GPUs), 'cuda' (NVIDIA only, fastest)."""
    support_model: str = "Qwen3.5-4B-Q4_K_M.gguf"
    embed_model: str = "nomic-embed-text-v1.5.f16.gguf"
    n_ctx: int
    """Context window size for the local support model. Minimum 2048."""
    n_threads: int
    """Number of CPU threads for local inference. 0 = auto (half of logical cores, max 8)."""
    support_remote_host: str
    support_remote_port: int
    embed_remote_host: str
    embed_remote_port: int

    @property
    def run_locally(self) -> bool:
        """Whether llama.cpp runs on this machine.

        True for LOCAL, and also for CLOUD: the embedding model stays here even
        when the support model does not, because the vector database it feeds is
        local and vectors from a different model would not be comparable.
        """
        return self.mode != LocalAiMode.SERVER


class SettingsConfig(BaseModel):
    audio: Optional[AudioSettings] = None
    stt: SttSettings
    voice_activation: VoiceActivationSettings
    wingman_pro: WingmanProSettings
    xvasynth: XVASynthSettings
    pocket_tts: PocketTTSSettings
    llama_cpp: LlamaCppSettings
    hud_server: HudServerSettings
    debug_mode: bool
    streamer_mode: bool
    cancel_tts_key: Optional[str] = None
    cancel_tts_key_codes: Optional[list[int]] = None
    cancel_tts_joystick_button: Optional[CommandJoystickConfig] = None
    user_name: Optional[str] = None
    hardware_scan_performed: bool = False
    spoken_language: str = "multilingual"


class SubscriptionModel(BaseModel):
    id: str
    name: str


class SubscriptionRoutes(BaseModel):
    """The models behind the plan's fixed roles, decided in /admin, so the
    client asks rather than assumes. None means the plan has no such access."""

    stt: Optional[SubscriptionModel] = None
    """Transcription."""
    tts: Optional[SubscriptionModel] = None
    """Speech."""
    image: Optional[SubscriptionModel] = None
    """Image generation."""
    downgraded: Optional[SubscriptionModel] = None
    """What chat falls back to once the allowance is used up."""


class BenchmarkResult(BaseModel):
    label: str
    execution_time_ms: float
    formatted_execution_time: str
    snapshots: Optional[list["BenchmarkResult"]] = None


BenchmarkResult.model_rebuild()

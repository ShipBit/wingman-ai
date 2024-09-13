from typing import Optional
from typing_extensions import Annotated, TypedDict
from pydantic import Base64Str, BaseModel, Field, model_validator
from api.enums import (
    AzureApiVersion,
    AzureRegion,
    ConversationProvider,
    GoogleAiModel,
    ImageGenerationProvider,
    MistralModel,
    CustomPropertyType,
    SkillCategory,
    TtsVoiceGender,
    OpenAiModel,
    OpenAiTtsVoice,
    SoundEffect,
    SttProvider,
    TtsProvider,
    VoiceActivationSttProvider,
    WingmanInitializationErrorType,
    WingmanProAzureDeployment,
    WingmanProRegion,
    WingmanProSttProvider,
    WingmanProTtsProvider,
)


class WingmanConfigFileInfo(BaseModel):
    name: str
    """"The "friendly" name of this config used to display in the UI/Terminal without prefixes or file extension.

    Examples: Board Computer"""
    file: str
    """The actual name of the file in the file system. May include meta prefixes and always includes file extension.

    Examples: Board Computer.yaml or .Board Computer.yaml"""
    is_deleted: bool
    """Whether this file is logically deleted."""

    avatar: Annotated[str, Base64Str]
    """The avatar of the wingman or the default avatar if none is set. Encoded as base64 string."""


class ConfigDirInfo(BaseModel):
    name: str
    """"The "friendly" name of this config used to display in the UI/Terminal.

    Examples: Star Citizen
    """
    directory: str
    """The actual name of the directory in the file system. May include meta prefixes.

    Examples: Star Citizen or _Star Citizen or .Star Citizen"""
    is_default: bool
    """Whether this config is the default config that is used on launch."""
    is_deleted: bool
    """Whether this directory is logically deleted."""
    # TODO: icon(?)


class SystemCore(TypedDict):
    version: str
    latest_version: str
    is_latest: bool


class SystemInfo(BaseModel):
    os: str
    core: SystemCore


class WingmanInitializationError(BaseModel):
    wingman_name: str
    message: str
    error_type: WingmanInitializationErrorType
    secret_name: Optional[str] = None


class VoiceInfo(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[TtsVoiceGender] = None
    locale: Optional[str] = None


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


class WhispercppSettings(BaseModel):
    host: str
    port: int
    model: str
    language: str
    translate_to_english: bool
    use_cuda: bool


class XVASynthSettings(BaseModel):
    enable: bool
    host: str
    port: int
    install_dir: str
    """The path to your installation of XVASynth. Usually in your Steam installation directory."""
    process_device: str
    """Can be cpu or gpu. You may need to take additional steps to have XVASynth run on your GPU."""


class WhispercppSttConfig(BaseModel):
    temperature: float


class WhispercppTranscript(BaseModel):
    text: str
    language: str


class AzureInstanceConfig(BaseModel):
    api_base_url: str
    """https://xxx.openai.azure.com/"""

    api_version: AzureApiVersion
    """The API version to use. For a list of supported versions, see here: https://learn.microsoft.com/en-us/azure/ai-services/openai/reference"""

    deployment_name: str
    """The deployment name e.g. 'whisper'"""


class AzureTtsConfig(BaseModel):
    region: AzureRegion
    voice: str
    output_streaming: bool


class AzureSttConfig(BaseModel):
    region: AzureRegion
    languages: list[str]


class AzureConfig(BaseModel):
    """Azure is a paid subscription provider from Microsoft which also offers OpenAI API access.

    If you configured some providers above to use Azure, you need to provide your Azure settings here.
    Please also provide your Azure API keys in the secrets.yaml.
    """

    whisper: AzureInstanceConfig
    conversation: AzureInstanceConfig
    tts: AzureTtsConfig
    stt: AzureSttConfig


class ElevenlabsLanguage(BaseModel):
    language_id: str
    name: str


class ElevenlabsModelMetadata(BaseModel):
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

    latency: Annotated[int, Field(strict=True, ge=0, le=4)]
    """Optimization - Higher values are faster but can produce audio stuttering. 0 - 4"""

    voice: ElevenlabsVoiceConfig
    voice_settings: ElevenlabsVoiceSettingsConfig
    output_streaming: bool


class EdgeTtsConfig(BaseModel):
    voice: str
    """
    All available EdgeTTS voices: https://github.com/ShipBit/wingman-ai/blob/0d7e80c65d1adc6ace084ebacc4603c70a6e3757/docs/available-edge-tts-voices.md

    Voice samples: https://speech.microsoft.com/portal/voicegallery
    """


class XVASynthVoiceConfig(BaseModel):
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
    conversation_model: OpenAiModel
    """ The model to use for conversations aka "chit-chat" and for function calls.
    """

    tts_voice: OpenAiTtsVoice
    """ The voice to use for OpenAI text-to-speech.
    Only used if features > tts_provider is set to 'openai'.
    """

    base_url: Optional[str] = None
    """ If you want to use a different API endpoint, uncomment this and configure it here.
    Use this to hook up your local in-place OpenAI replacement like Ollama or if you want to use a proxy.

    https://api.openai.com # or the localhost address of your local LLM etc.
    """

    organization: Optional[str] = None
    """If you have an organization key, you can set it here."""


class PromptConfig(BaseModel):
    system_prompt: str
    """The read-only "context template" for the Wingman. Contains variables that will be replaced by the user (backstory) and/or skills."""

    backstory: Optional[str] = None
    """The backstory of the Wingman. Edit this to control how your Wingman should behave."""


class MistralConfig(BaseModel):
    conversation_model: MistralModel
    endpoint: str


class GroqConfig(BaseModel):
    conversation_model: str
    endpoint: str


class CerebrasConfig(BaseModel):
    conversation_model: str
    endpoint: str


class GoogleConfig(BaseModel):
    conversation_model: GoogleAiModel


class OpenRouterConfig(BaseModel):
    conversation_model: str
    endpoint: str


class LocalLlmConfig(BaseModel):
    conversation_model: Optional[str] = None
    endpoint: str


class WingmanProConfig(BaseModel):
    stt_provider: WingmanProSttProvider
    tts_provider: WingmanProTtsProvider
    conversation_deployment: WingmanProAzureDeployment
    # we'll reuse the Azure STT config and OpenAI TTS config here for voice etc.


class WingmanProSettings(BaseModel):
    base_url: str
    region: WingmanProRegion


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
    """You can configure the voice activation here. If you don't want to use voice activation, just set 'enabled' to false."""

    enabled: bool
    """Whether to use voice activation or not. If you disable this, you need to use the record key to record your voice."""

    mute_toggle_key: str
    """If you want to use a key to toggle the microphone on/off, you can set it here. This is useful if you want to use voice activation but also want to be able to talk to other people without the Wingman interfering."""

    mute_toggle_key_codes: Optional[list[int]] = None

    energy_threshold: float
    """The minimum energy threshold a recording must pass in a certain frequency band to be considererd as spoken voice."""

    stt_provider: VoiceActivationSttProvider

    azure: AzureSttConfig
    whispercpp: WhispercppSettings
    whispercpp_config: WhispercppSttConfig


class FeaturesConfig(BaseModel):
    """You can override various AI providers if your Wingman supports it. Our OpenAI wingman does!

    Note that the other providers may have additional config blocks. These are only used if the provider is set here.
    """

    tts_provider: TtsProvider
    stt_provider: SttProvider
    conversation_provider: ConversationProvider
    remember_messages: Optional[int] = None
    image_generation_provider: ImageGenerationProvider
    use_generic_instant_responses: bool


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


class CommandActionConfig(BaseModel):
    keyboard: Optional[CommandKeyboardConfig] = None
    """The keyboard configuration for this action. Optional."""

    wait: Optional[float] = None
    """Wait time in seconds before pressing the next key. Optional."""

    mouse: Optional[CommandMouseConfig] = None
    """The mouse configuration for this action. Optional."""

    write: Optional[str] = None
    """The word or phrase to type, for example, to type text in a login screen.  Must have associated button press to work.  May need special formatting for special characters."""


class CommandConfig(BaseModel):
    name: str
    """This is where the magic happens!
    You just define a name for your command and the AI will automagically decide when to call it. Not kidding!
    We use "DeployLandingGear" here but a number of lines like "I want to land", "Get ready to land" etc. will also work.
    If the Wingman doesn't call your command, try to rephrase the name here.
    """
    is_system_command: Optional[bool] = False
    """Whether this is a system command that cannot be deleted or edited by the user."""
    instant_activation: Optional[list[str]] = None
    """Optional: Faster - like Voice Attack! Provide phrases that will instantly activate the command (without AI roundtripping). You need to say the exact phrase to execute the command"""
    force_instant_activation: Optional[bool] = False
    """Optional: If true, the command will only be executed if the exact phrase is said. If false, the command will be executed if the exact phrase is said, or if the AI thinks it makes sense based on name and context."""
    responses: Optional[list[str]] = None
    """Optional: Provide responses that will be used when the command is executed. A random one will be chosen (if multiple)."""
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
    voice: str | ElevenlabsVoiceConfig | OpenAiTtsVoice | XVASynthVoiceConfig

    @model_validator(mode="before")
    def check_voice_config(cls, values):

        def __parse_voice(provider: any, voice: any):
            if provider == "elevenlabs":
                return ElevenlabsVoiceConfig.model_validate(voice)
            if provider == "openai":
                return OpenAiTtsVoice(voice)
            if provider == "xvasynth":
                return XVASynthVoiceConfig.model_validate(voice)
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
    value: str | int | float | bool | VoiceSelection | list[VoiceSelection]
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


class SkillExample(BaseModel):
    question: LocalizedMetadata
    answer: LocalizedMetadata


class SkillConfig(CustomClassConfig):
    description: LocalizedMetadata
    prompt: Optional[str] = None
    """An additional prompt that extends the system prompt of the Wingman."""
    custom_properties: Optional[list[CustomProperty]] = None
    """You can add custom properties here to use in your custom skill class."""
    hint: Optional[LocalizedMetadata] = None
    examples: Optional[list[SkillExample]] = None
    category: Optional[SkillCategory] = None


class SkillBase(BaseModel):
    name: str
    config: SkillConfig
    logo: Optional[Annotated[str, Base64Str]] = None


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
    elevenlabs: ElevenlabsConfig
    azure: AzureConfig
    xvasynth: XVASynthTtsConfig
    whispercpp: WhispercppSttConfig
    wingman_pro: WingmanProConfig
    commands: Optional[list[CommandConfig]] = None
    skills: Optional[list[SkillConfig]] = None


class BasicWingmanConfig(BaseModel):
    """All configuration options that can be save in the "Basic" config in the client"""

    name: str
    disabled: Optional[bool] = False
    record_key: Optional[str] = None
    record_key_codes: Optional[list[int]] = None
    sound: SoundConfig
    voice: str | OpenAiTtsVoice
    backstory: Optional[str] = None


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
    description: str
    """A short description of this Wingman."""
    record_key: Optional[str] = None
    """The "push-to-talk" key for this wingman. Keep it pressed while talking! Don't use the same key for multiple wingmen!"""
    record_key_codes: Optional[list[int]] = None
    """The "push-to-talk" key code for this wingman. Keep it pressed while talking! Don't use the same key for multiple wingmen!"""
    record_mouse_button: Optional[str] = None
    """The "push-to-talk" mouse button for this wingman. Keep it pressed while talking! Don't use the same button for multiple wingmen!"""
    is_voice_activation_default: Optional[bool] = None
    """If voice activation is enabled and this is true, the Wingman will listen to your voice by default and without saying its name."""


class Config(NestedConfig):
    """You can override these default settings for each wingman.
    If you do that, make sure you keep the "hierarchy" of the config intact.
    """

    wingmen: Optional[dict[str, WingmanConfig]] = None
    """The Wingmen in this config. You can add as many as you want!"""


class ConfigsInfo(BaseModel):
    config_dirs: list[ConfigDirInfo]
    current_config_dir: ConfigDirInfo


class ConfigWithDirInfo(BaseModel):
    config: Config
    config_dir: ConfigDirInfo


class NewWingmanTemplate(BaseModel):
    wingman_config: WingmanConfig
    avatar: Annotated[str, Base64Str]


class SettingsConfig(BaseModel):
    audio: Optional[AudioSettings] = None
    voice_activation: VoiceActivationSettings
    wingman_pro: WingmanProSettings
    xvasynth: XVASynthSettings
    debug_mode: bool = False

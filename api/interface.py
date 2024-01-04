from typing import Optional
from typing_extensions import Annotated, TypedDict
from pydantic import BaseModel, Field
from api.enums import (
    AzureApiVersion,
    ConversationProvider,
    EdgeTtsVoiceGender,
    ElevenlabsModel,
    OpenAiModel,
    OpenAiTtsVoice,
    SoundEffect,
    SttProvider,
    SummarizeProvider,
    TtsProvider,
    WingmanInitializationErrorType,
)


class ConfigInfo(BaseModel):
    configs: list[str]
    currentConfig: str


class SystemCore(TypedDict):
    version: str
    latest: str
    isLatest: bool


class SystemInfo(BaseModel):
    os: str
    core: SystemCore


class WingmanInitializationError(BaseModel):
    wingman_name: str
    message: str
    error_type: WingmanInitializationErrorType
    secret_name: Optional[str] = None


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


class AudioSettings(BaseModel):
    input: Optional[int] = None
    output: Optional[int] = None


class SettingsConfig(BaseModel):
    audio: Optional[AudioSettings] = None


class AzureInstanceConfig(BaseModel):
    api_base_url: str
    """https://xxx.openai.azure.com/"""

    api_version: AzureApiVersion
    """The API version to use. For a list of supported versions, see here: https://learn.microsoft.com/en-us/azure/ai-services/openai/reference"""

    deployment_name: str
    """The deployment name e.g. 'whisper'"""


class AzureTtsConfig(BaseModel):
    region: str
    voice: str
    detect_language: bool
    languages: list[str]


class AzureConfig(BaseModel):
    """Azure is a paid subscription provider from Microsoft which also offers OpenAI API access.

    If you configured some providers above to use Azure, you need to provide your Azure settings here.
    Please also provide your Azure API keys in the secrets.yaml.
    """

    whisper: AzureInstanceConfig
    conversation: AzureInstanceConfig
    summarize: AzureInstanceConfig
    tts: AzureTtsConfig


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
    model: ElevenlabsModel
    """see https://elevenlabs.io/docs/speech-synthesis/models"""

    latency: Annotated[int, Field(strict=True, ge=0, le=4)]
    """Optimization - Higher values are faster but can produce audio stuttering. 0 - 4"""

    voice: ElevenlabsVoiceConfig
    voice_settings: ElevenlabsVoiceSettingsConfig
    use_sound_effects: Optional[bool] = False
    """Adds a delay"""


class EdgeTtsConfig(BaseModel):
    tts_voice: str
    """The voice to use (only if detect_language is set to false).

    All available EdgeTTS voices: https://github.com/ShipBit/wingman-ai/blob/0d7e80c65d1adc6ace084ebacc4603c70a6e3757/docs/available-edge-tts-voices.md

    Voice samples: https://speech.microsoft.com/portal/voicegallery
    """

    detect_language: bool
    """EdgeTTS does not support on-the-fly language switches like OpenAI's TTS does.
    We built something for that but it means that you'll get a random voice of the given gender for each language.
    These voices can be weird, e.g. chidrens' voices for some languages.
    Only enable this if you need to change languages on-the-fly(!) during your conversations.
    Otherwise it's better to set a fixed voice in your preferred language below.
    """

    gender: EdgeTtsVoiceGender


class OpenAiConfig(BaseModel):
    context: Optional[str] = None
    """The "context" for the wingman. Here's where you can tell the AI how to behave.
    This is probably what you want to play around with the most.
    """

    conversation_model: OpenAiModel
    """ The model to use for conversations aka "chit-chat" and for function calls.
    gpt-4 is more powerful than gpt-3.5 but also 10x more expensive.
    gpt-3.5 is the default and should be enough for most use cases.
    If something is not working as expected, you might want to test it with gpt-4.
    """

    summarize_model: OpenAiModel
    """ This model summarizes function responses, like API call responses etc.
    In most cases gpt-3.5 should be enough.
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


class SoundConfig(BaseModel):
    play_beep: bool
    """adds a beep/Quindar sound before and after the wingman talks"""

    effects: Optional[list[SoundEffect]] = None
    """You can put as many sound effects here as you want. They stack and are added in the defined order here."""


class FeaturesConfig(BaseModel):
    """You can override various AI providers if your Wingman supports it. Our OpenAI wingman does!

    Note that the other providers may have additional config blocks. These are only used if the provider is set here.
    """

    debug_mode: bool
    """If enabled, the Wingman will skip executing any keypresses. It will also print more debug messages and benchmark results."""

    tts_provider: TtsProvider
    stt_provider: SttProvider
    conversation_provider: ConversationProvider
    summarize_provider: SummarizeProvider
    remember_messages: Optional[int] = None


class KeyPressConfig(BaseModel):
    key: str
    """The key the wingman will press when executing the command.  Use 'primary', 'secondary' or 'middle' for mouse buttons. Use 'scroll' to scroll."""

    modifier: Optional[str] = None
    """This will press "modifier + key" instead of just "modifier". Optional."""

    wait: Optional[int] = None
    """Wait n second before pressing the next key. Optional."""

    hold: Optional[float] = None
    """The duration the key will be pressed in seconds. Optional."""

    scroll_amount: Optional[int] = None
    """The amount of clicks to scroll up (positive integer) or down (negative integer), example 10 or -10. Must have 'scroll' as key above to work."""

    moveto: Optional[tuple] = None
    """The x, y coordinates to move the mouse to on the screen, expected [x,y] format in yaml.  Must have associated button press to work."""

    moveto_relative: Optional[tuple] = None
    """The x, y coordinates to move to relative to the current mouse position, expected [x,y] format in yaml.  Must have associated button press to work."""

    write: Optional[str] = None
    """The word or phrase to type, for example, to type text in a login screen.  Must have associated button press to work.  May need special formatting for special characters."""

class CommandConfig(BaseModel):
    name: str
    """This is where the magic happens!
    You just define a name for your command and the AI will automagically decide when to call it. Not kidding!
    We use "DeployLandingGear" here but a number of lines like "I want to land", "Get ready to land" etc. will also work.
    If the Wingman doesn't call your command, try to rephrase the name here.
    """

    instant_activation: Optional[list[str]] = None
    responses: Optional[list[str]] = None
    keys: Optional[list[KeyPressConfig]] = None


class CustomWingmanClassConfig(BaseModel):
    module: str
    """Where your code is located. Use '.' as path separator!
    We advise you to put all your custom wingmen into the /wingmen directory.
    "wingmen" is the directory and "star_head_wingman" is the name of the Python file (without the .py extension).
    """

    name: str
    """The name of your class within your file/module."""


class NestedConfig(BaseModel):
    sound: SoundConfig
    features: FeaturesConfig
    openai: OpenAiConfig
    edge_tts: EdgeTtsConfig
    elevenlabs: ElevenlabsConfig
    azure: AzureConfig
    commands: list[CommandConfig] | None = None


class WingmanConfig(NestedConfig):
    def __getitem__(self, item):
        return self.extra_properties.get(item)

    def __setitem__(self, key, value):
        self.extra_properties[key] = value

    # these can only be strings because otherwise our schema generation will break (if they were of type Any)
    custom_properties: Optional[dict[str, str]] = {}

    disabled: Optional[bool] = False
    custom_class: Optional[CustomWingmanClassConfig] = None
    record_key: str
    """The "push-to-talk" key for this wingman. Keep it pressed while talking!
    Modifiers for this key are not supported yet. Don't use the same key for multiple wingmen!"""


class Config(NestedConfig):
    """You can override these default settings for each wingman.
    If you do that, make sure you keep the "hierarchy" of the config intact.
    """

    wingmen: Optional[dict[str, WingmanConfig]] = None

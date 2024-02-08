from enum import Enum
from pydantic import BaseModel


# Enum declarations
class LogType(Enum):
    SUBTLE = "subtle"
    INFO = "info"
    HIGHLIGHT = "highlight"
    POSITIVE = "positive"
    WARNING = "warning"
    ERROR = "error"
    PURPLE = "purple"


class LogSource(Enum):
    SYSTEM = "system"
    USER = "user"
    WINGMAN = "wingman"


class ToastType(Enum):
    NORMAL = "normal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class WingmanInitializationErrorType(Enum):
    UNKNOWN = "unknown"
    INVALID_CONFIG = "invalid_config"
    MISSING_SECRET = "missing_secret"


class CommandTag(Enum):
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    IGNORED_RECORDING = "ignored_recording"
    PLAYBACK_STARTED = "playback_started"
    PLAYBACK_STOPPED = "playback_stopped"


class AzureApiVersion(Enum):
    A2023_09_01_PREVIEW = "2023-09-01-preview"
    A2023_12_01_PREVIEW = "2023-12-01-preview"


class AzureRegion(Enum):
    WESTEUROPE = "westeurope"


class ElevenlabsModel(Enum):
    ELEVEN_MULTILINGUAL_V2 = "eleven_multilingual_v2"
    ELEVEN_TURBO_V2 = "eleven_turbo_v2"
    ELEVEN_MONOLINGUAL_V1 = "eleven_monolingual_v1"


class TtsVoiceGender(Enum):
    UNKNOWN = "Unknown"
    MALE = "Male"
    FEMALE = "Female"


class OpenAiModel(Enum):
    GPT_35_TURBO_1106 = "gpt-3.5-turbo-1106"
    GPT_4_1106_PREVIEW = "gpt-4-1106-preview"


class OpenAiTtsVoice(Enum):
    NOVA = "nova"
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    SHIMMER = "shimmer"


class SoundEffect(Enum):
    ROBOT = "ROBOT"
    RADIO = "RADIO"
    INTERIOR_HELMET = "INTERIOR_HELMET"
    INTERIOR_SMALL = "INTERIOR_SMALL"
    INTERIOR_MEDIUM = "INTERIOR_MEDIUM"
    INTERIOR_LARGE = "INTERIOR_LARGE"


class TtsProvider(Enum):
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    EDGE_TTS = "edge_tts"
    AZURE = "azure"
    XVASYNTH = "xvasynth"


class SttProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    AZURE_SPEECH = "azure_speech"
    WHISPERCPP = "whispercpp"


class ConversationProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"


class SummarizeProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"


class KeyboardRecordingType(Enum):
    SINGLE = "single"
    MACRO = "macro"


# Pydantic models for enums
class BaseEnumModel(BaseModel):
    class Config:
        # fix pydantic serialization of enums
        json_encoders = {
            Enum: lambda v: v.value,
        }


class LogTypeEnumModel(BaseEnumModel):
    log_type: LogType


class LogSourceEnumModel(BaseEnumModel):
    log_source: LogSource


class ToastTypeEnumModel(BaseEnumModel):
    toast_type: ToastType


class WingmanInitializationErrorTypeModel(BaseEnumModel):
    error_type: WingmanInitializationErrorType


class CommandTagEnumModel(BaseEnumModel):
    command_tag: CommandTag


class AzureApiVersionEnumModel(BaseEnumModel):
    api_version: AzureApiVersion


class AzureRegionEnumModel(BaseEnumModel):
    region: AzureRegion


class ElevenlabsModelEnumModel(BaseEnumModel):
    model: ElevenlabsModel


class TtsVoiceGenderEnumModel(BaseEnumModel):
    gender: TtsVoiceGender


class OpenAiModelEnumModel(BaseEnumModel):
    model: OpenAiModel


class OpenAiTtsVoiceEnumModel(BaseEnumModel):
    voice: OpenAiTtsVoice


class SoundEffectEnumModel(BaseEnumModel):
    sound_effect: SoundEffect


class TtsProviderEnumModel(BaseEnumModel):
    tts_provider: TtsProvider


class SttProviderEnumModel(BaseEnumModel):
    stt_provider: SttProvider


class ConversationProviderEnumModel(BaseEnumModel):
    conversation_provider: ConversationProvider


class SummarizeProviderEnumModel(BaseEnumModel):
    summarize_provider: SummarizeProvider


class KeyboardRecordingTypeModel(BaseEnumModel):
    recording_type: KeyboardRecordingType


# Add all additional Pydantic models for enums as needed


# Enums and their corresponding model classes for dynamic schema generation
ENUM_TYPES = {
    "LogType": LogTypeEnumModel,
    "LogSource": LogSourceEnumModel,
    "ToastType": ToastTypeEnumModel,
    "WingmanInitializationErrorType": WingmanInitializationErrorTypeModel,
    "CommandTag": CommandTagEnumModel,
    "AzureApiVersion": AzureApiVersionEnumModel,
    "AzureRegion": AzureRegionEnumModel,
    "ElevenlabsModel": ElevenlabsModelEnumModel,
    "TtsVoiceGender": TtsVoiceGenderEnumModel,
    "OpenAiModel": OpenAiModelEnumModel,
    "OpenAiTtsVoice": OpenAiTtsVoiceEnumModel,
    "SoundEffect": SoundEffectEnumModel,
    "TtsProvider": TtsProviderEnumModel,
    "SttProvider": SttProviderEnumModel,
    "ConversationProvider": ConversationProviderEnumModel,
    "SummarizeProvider": SummarizeProviderEnumModel,
    "KeyboardRecordingType": KeyboardRecordingTypeModel,
    # Add new enums here as key-value pairs
}


# make yaml.dump save Pydantic enums as strings
def enum_representer(dumper, value):
    return dumper.represent_data(value.value)

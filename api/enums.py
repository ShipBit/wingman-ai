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
    UNAUTHORIZED = "unauthorized"


class AzureApiVersion(Enum):
    A2023_12_01_PREVIEW = "2023-12-01-preview"
    A2024_02_15_PREVIEW = "2024-02-15-preview"


class AzureRegion(Enum):
    WESTEUROPE = "westeurope"
    NORTHCENTRALUS = "northcentralus"


class ElevenlabsModel(Enum):
    ELEVEN_MULTILINGUAL_V2 = "eleven_multilingual_v2"
    ELEVEN_TURBO_V2 = "eleven_turbo_v2"
    ELEVEN_MONOLINGUAL_V1 = "eleven_monolingual_v1"


class TtsVoiceGender(Enum):
    UNKNOWN = "Unknown"
    MALE = "Male"
    FEMALE = "Female"


class OpenAiModel(Enum):
    GPT_35_TURBO = "gpt-3.5-turbo"
    GPT_4_TURBO_PREVIEW = "gpt-4-turbo-preview"


class WingmanProAzureDeployment(Enum):
    GPT_35_TURBO = "gpt-35-turbo"
    GPT_4_TURBO = "gpt-4-turbo"


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
    WINGMAN_PRO = "wingman_pro"


class SttProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    AZURE_SPEECH = "azure_speech"
    WHISPERCPP = "whispercpp"
    WINGMAN_PRO = "wingman_pro"


class VoiceActivationSttProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    WHISPERCPP = "whispercpp"
    WINGMAN_PRO = "wingman_pro"


class ConversationProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    WINGMAN_PRO = "wingman_pro"


class SummarizeProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    WINGMAN_PRO = "wingman_pro"


class KeyboardRecordingType(Enum):
    SINGLE = "single"
    MACRO = "macro"


class WingmanProRegion(Enum):
    EUROPE = "europe"
    USA = "usa"


class WingmanProSttProvider(Enum):
    WHISPER = "whisper"
    AZURE_SPEECH = "azure_speech"


class WingmanProTtsProvider(Enum):
    AZURE = "azure"
    OPENAI = "openai"


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


class WingmanProAzureDeploymentEnumModel(BaseEnumModel):
    deployment_name: WingmanProAzureDeployment


class OpenAiTtsVoiceEnumModel(BaseEnumModel):
    voice: OpenAiTtsVoice


class SoundEffectEnumModel(BaseEnumModel):
    sound_effect: SoundEffect


class TtsProviderEnumModel(BaseEnumModel):
    tts_provider: TtsProvider


class SttProviderEnumModel(BaseEnumModel):
    stt_provider: SttProvider


class VoiceActivationSttProviderEnumModel(BaseEnumModel):
    stt_provider: VoiceActivationSttProvider


class ConversationProviderEnumModel(BaseEnumModel):
    conversation_provider: ConversationProvider


class SummarizeProviderEnumModel(BaseEnumModel):
    summarize_provider: SummarizeProvider


class KeyboardRecordingTypeModel(BaseEnumModel):
    recording_type: KeyboardRecordingType


class WingmanProRegionModel(BaseEnumModel):
    region: WingmanProRegion


class WingmanProSttProviderModel(BaseEnumModel):
    stt_provider: WingmanProSttProvider


class WingmanProTtsProviderModel(BaseEnumModel):
    tts_provider: WingmanProTtsProvider


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
    "WingmanProAzureDeployment": WingmanProAzureDeploymentEnumModel,
    "OpenAiTtsVoice": OpenAiTtsVoiceEnumModel,
    "SoundEffect": SoundEffectEnumModel,
    "TtsProvider": TtsProviderEnumModel,
    "SttProvider": SttProviderEnumModel,
    "VoiceActivationSttProvider": VoiceActivationSttProviderEnumModel,
    "ConversationProvider": ConversationProviderEnumModel,
    "SummarizeProvider": SummarizeProviderEnumModel,
    "KeyboardRecordingType": KeyboardRecordingTypeModel,
    "WingmanProRegion": WingmanProRegionModel,
    "WingmanProSttProvider": WingmanProSttProviderModel,
    "WingmanProTtsProvider": WingmanProTtsProviderModel,
    # Add new enums here as key-value pairs
}


# make yaml.dump save Pydantic enums as strings
def enum_representer(dumper, value):
    return dumper.represent_data(value.value)

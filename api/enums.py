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
    CONFIG_LOADED = "config_loaded"


class CustomPropertyType(Enum):
    STRING = "string"
    TEXTAREA = "textarea"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SINGLE_SELECT = "single_select"
    VOICE_SELECTION = "voice_selection"
    SLIDER = "slider"
    AUDIO_FILES = "audio_files"


class AzureApiVersion(Enum):
    A2023_12_01_PREVIEW = "2023-12-01-preview"
    A2024_02_15_PREVIEW = "2024-02-15-preview"


class AzureRegion(Enum):
    WESTEUROPE = "westeurope"
    NORTHCENTRALUS = "northcentralus"


class TtsVoiceGender(Enum):
    UNKNOWN = "Unknown"
    MALE = "Male"
    FEMALE = "Female"


class MistralModel(Enum):
    """https://docs.mistral.ai/getting-started/models/"""

    MISTRAL_7B = "open-mistral-7b"
    OPEN_MIXTRAL_8X7B = "open-mixtral-8x7b"
    OPEN_MIXTRAL_8X22B = "open-mixtral-8x22b"
    MISTRAL_SMALL = "mistral-small-latest"
    MISTRAL_MEDIUM = "mistral-medium-latest"
    MISTRAL_LARGE = "mistral-large-latest"

class PerplexityModel(Enum):
    """https://docs.perplexity.ai/guides/model-cards"""

    SONAR_SMALL = "llama-3.1-sonar-small-128k-online"
    SONAR_MEDIUM = "llama-3.1-sonar-large-128k-online"
    SONAR_LARGE = "llama-3.1-sonar-huge-128k-online"
    CHAT_SMALL = "llama-3.1-sonar-small-128k-chat"
    CHAT_LARGE = "llama-3.1-sonar-large-128k-chat"
    LLAMA3_8B = "llama-3.1-8b-instruct"
    LLAMA3_70B = "llama-3.1-70b-instruct"

class GoogleAiModel(Enum):
    GEMINI_1_5_FLASH = "gemini-1.5-flash"
    GEMINI_1_5_PRO = "gemini-1.5-pro"


class WingmanProAzureDeployment(Enum):
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    MISTRAL_LARGE = "mistral-large-latest"
    LLAMA3_8B = "llama3-8b"
    LLAMA3_70B = "llama3-70b"


class OpenAiTtsVoice(Enum):
    NOVA = "nova"
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    SHIMMER = "shimmer"


class SoundEffect(Enum):
    AI = "AI"
    LOW_QUALITY_RADIO = "LOW_QUALITY_RADIO"
    MEDIUM_QUALITY_RADIO = "MEDIUM_QUALITY_RADIO"
    HIGH_END_RADIO = "HIGH_END_RADIO"
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
    MISTRAL = "mistral"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    LOCAL_LLM = "local_llm"
    AZURE = "azure"
    WINGMAN_PRO = "wingman_pro"
    GOOGLE = "google"
    CEREBRAS = "cerebras"
    PERPLEXITY = "perplexity"


class ImageGenerationProvider(Enum):
    OPENAI = "openai"
    WINGMAN_PRO = "wingman_pro"


class KeyboardRecordingType(Enum):
    SINGLE = "single"
    MACRO = "macro"
    MACRO_ADVANCED = "macro_advanced"


class WingmanProRegion(Enum):
    EUROPE = "europe"
    USA = "usa"


class WingmanProSttProvider(Enum):
    WHISPER = "whisper"
    AZURE_SPEECH = "azure_speech"


class WingmanProTtsProvider(Enum):
    AZURE = "azure"
    OPENAI = "openai"


class SkillCategory(Enum):
    GENERAL = "general"
    STAR_CITIZEN = "star_citizen"
    TRUCK_SIMULATOR = "truck_simulator"
    NO_MANS_SKY = "no_mans_sky"
    FLIGHT_SIMULATOR = "flight_simulator"


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


class CustomPropertyTypeEnumModel(BaseEnumModel):
    property_type: CustomPropertyType


class AzureApiVersionEnumModel(BaseEnumModel):
    api_version: AzureApiVersion


class AzureRegionEnumModel(BaseEnumModel):
    region: AzureRegion


class TtsVoiceGenderEnumModel(BaseEnumModel):
    gender: TtsVoiceGender


class MistralModelEnumModel(BaseEnumModel):
    model: MistralModel

class PerplexityModelEnumModel(BaseEnumModel):
    model: PerplexityModel

class GoogleAiModelEnumModel(BaseEnumModel):
    model: GoogleAiModel


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


class ImageGenerationProviderEnumModel(BaseEnumModel):
    image_generation_provider: ImageGenerationProvider


class KeyboardRecordingTypeModel(BaseEnumModel):
    recording_type: KeyboardRecordingType


class WingmanProRegionModel(BaseEnumModel):
    region: WingmanProRegion


class WingmanProSttProviderModel(BaseEnumModel):
    stt_provider: WingmanProSttProvider


class WingmanProTtsProviderModel(BaseEnumModel):
    tts_provider: WingmanProTtsProvider


class SkillCategoryModel(BaseEnumModel):
    category: SkillCategory


# Add all additional Pydantic models for enums as needed


# Enums and their corresponding model classes for dynamic schema generation
ENUM_TYPES = {
    "LogType": LogTypeEnumModel,
    "LogSource": LogSourceEnumModel,
    "ToastType": ToastTypeEnumModel,
    "WingmanInitializationErrorType": WingmanInitializationErrorTypeModel,
    "CommandTag": CommandTagEnumModel,
    "CustomPropertyType": CustomPropertyTypeEnumModel,
    "AzureApiVersion": AzureApiVersionEnumModel,
    "AzureRegion": AzureRegionEnumModel,
    "TtsVoiceGender": TtsVoiceGenderEnumModel,
    "MistralModel": MistralModelEnumModel,
    "GoogleAiModel": GoogleAiModelEnumModel,
    "WingmanProAzureDeployment": WingmanProAzureDeploymentEnumModel,
    "OpenAiTtsVoice": OpenAiTtsVoiceEnumModel,
    "SoundEffect": SoundEffectEnumModel,
    "TtsProvider": TtsProviderEnumModel,
    "SttProvider": SttProviderEnumModel,
    "VoiceActivationSttProvider": VoiceActivationSttProviderEnumModel,
    "ConversationProvider": ConversationProviderEnumModel,
    "KeyboardRecordingType": KeyboardRecordingTypeModel,
    "WingmanProRegion": WingmanProRegionModel,
    "WingmanProSttProvider": WingmanProSttProviderModel,
    "WingmanProTtsProvider": WingmanProTtsProviderModel,
    "SkillCategory": SkillCategoryModel,
    "PerplexityModel": PerplexityModelEnumModel,
    # Add new enums here as key-value pairs
}


# make yaml.dump save Pydantic enums as strings
def enum_representer(dumper, value):
    return dumper.represent_data(value.value)

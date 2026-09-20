"""Factory for creating provider instances from config.

Reads the config enum values, looks up the registered adapter class from
the decorator registry, retrieves API keys via SecretKeeper, and instantiates
the provider. Each provider holds a reference to the live config object.
"""

import traceback
from typing import TYPE_CHECKING

from api.enums import (
    ConversationProvider,
    ImageGenerationProvider,
    TtsProvider,
    WingmanInitializationErrorType,
)
from api.interface import WingmanInitializationError
from providers.interfaces import (
    LlmInterface,
    TtsInterface,
    Validatable,
    get_llm_class,
    get_tts_class,
)
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import SettingsConfig, WingmanConfig
    from services.secret_keeper import SecretKeeper

printr = Printr()


# Import all provider modules so their decorators run and populate the registries.
# These imports have no other side effects.
import providers.open_ai  # noqa: F401
import providers.google  # noqa: F401
import providers.x_ai  # noqa: F401
import providers.elevenlabs  # noqa: F401
import providers.edge  # noqa: F401
import providers.hume  # noqa: F401
import providers.inworld  # noqa: F401
import providers.pocket_tts  # noqa: F401
import providers.xvasynth  # noqa: F401
import providers.wingman_subscription  # noqa: F401


class ProviderFactory:
    """Creates TTS and LLM provider instances from config."""

    def __init__(
        self,
        config: "WingmanConfig",
        settings: "SettingsConfig",
        secret_keeper: "SecretKeeper",
        shared_providers: dict,
        wingman_name: str,
    ):
        self._config = config
        self._settings = settings
        self._secret_keeper = secret_keeper
        self._shared = shared_providers
        self._wingman_name = wingman_name

    async def _retrieve_secret(
        self, requester: str, errors: list[WingmanInitializationError]
    ) -> str | None:
        """Retrieve an API key, adding to errors if missing."""
        secret = await self._secret_keeper.retrieve(
            requester=requester,
            key=requester,
            prompt_if_missing=True,
        )
        if not secret:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self._wingman_name,
                    message=f"Missing API key for '{requester}'.",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                )
            )
        return secret

    async def _retrieve_optional_secret(self, requester: str) -> str:
        """Read an API key that the endpoint may or may not want.

        Used for OpenAI-compatible endpoints the user points at themselves: a
        llama.cpp server on localhost needs no key, Ollama Cloud or a hosted
        gateway does. Never prompts and never fails - a missing key would
        otherwise pop a dialog on every start for the people running keyless.
        "not-set" is the placeholder the 1.8.2 -> 2.0.0 migration wrote into
        secrets.yaml and means the same as empty. The OpenAI client rejects an
        empty api_key, so keyless falls back to a dummy the server ignores.
        """
        secret = await self._secret_keeper.retrieve(
            requester=requester,
            key=requester,
            prompt_if_missing=False,
        )
        secret = (secret or "").strip()
        if not secret or secret == "not-set":
            return "not-needed"
        return secret

    async def create_tts(
        self, errors: list[WingmanInitializationError]
    ) -> TtsInterface | None:
        """Create the TTS provider from config."""
        tts_enum = self._config.features.tts_provider
        if tts_enum == TtsProvider.EDGE_TTS:
            from providers.edge import EdgeTts

            return EdgeTts(config=self._config)
        elif tts_enum == TtsProvider.ELEVENLABS:
            api_key = await self._retrieve_secret("elevenlabs", errors)
            if not api_key:
                return None
            from providers.elevenlabs import ElevenLabs, ElevenLabsTts

            elevenlabs = ElevenLabs(api_key=api_key, wingman_name=self._wingman_name)
            return ElevenLabsTts(elevenlabs_instance=elevenlabs, config=self._config)
        elif tts_enum == TtsProvider.HUME:
            api_key = await self._retrieve_secret("hume", errors)
            if not api_key:
                return None
            from providers.hume import Hume, HumeTts

            hume = Hume(api_key=api_key, wingman_name=self._wingman_name)
            return HumeTts(hume_instance=hume, config=self._config)
        elif tts_enum == TtsProvider.INWORLD:
            api_key = await self._retrieve_secret("inworld", errors)
            if not api_key:
                return None
            from providers.inworld import Inworld, InworldTts

            inworld = Inworld(api_key=api_key, wingman_name=self._wingman_name)
            return InworldTts(inworld_instance=inworld, config=self._config)
        elif tts_enum == TtsProvider.OPENAI:
            api_key = await self._retrieve_secret("openai", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, OpenAiTts

            openai = OpenAi(
                api_key=api_key, organization=self._config.openai.organization
            )
            return OpenAiTts(openai_instance=openai, config=self._config)
        elif tts_enum == TtsProvider.OPENAI_COMPATIBLE:
            api_key = self._config.openai_compatible_tts.api_key
            # api_key might be optional for local endpoints
            from providers.open_ai import (
                OpenAiCompatibleTts,
                OpenAiCompatibleTtsAdapter,
            )

            tts = OpenAiCompatibleTts(
                api_key=api_key or "",
                base_url=self._config.openai_compatible_tts.base_url,
            )
            return OpenAiCompatibleTtsAdapter(tts_instance=tts, config=self._config)
        elif tts_enum == TtsProvider.XVASYNTH:
            from providers.xvasynth import XVASynthTts

            return XVASynthTts(shared=self._shared["xvasynth"], config=self._config)
        elif tts_enum == TtsProvider.POCKET_TTS:
            from providers.pocket_tts import PocketTtsTts

            return PocketTtsTts(shared=self._shared["pocket_tts"], config=self._config)
        elif tts_enum == TtsProvider.WINGMAN_PRO:
            from providers.wingman_subscription import (
                WingmanSubscription,
                WingmanSubscriptionTts,
            )

            ws = WingmanSubscription(
                wingman_name=self._wingman_name,
                settings=self._settings.wingman_pro,
            )
            return WingmanSubscriptionTts(ws_instance=ws, config=self._config)
        return None

    async def create_llm(
        self, errors: list[WingmanInitializationError]
    ) -> LlmInterface | None:
        """Create the LLM provider from config."""
        llm_enum = self._config.features.conversation_provider
        if llm_enum == ConversationProvider.OPENAI:
            api_key = await self._retrieve_secret("openai", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, OpenAiLlm

            openai = OpenAi(
                api_key=api_key, organization=self._config.openai.organization
            )
            return OpenAiLlm(openai_instance=openai, config=self._config)
        elif llm_enum == ConversationProvider.MISTRAL:
            api_key = await self._retrieve_secret("mistral", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, MistralLlm

            mistral = OpenAi(api_key=api_key, base_url=self._config.mistral.endpoint)
            return MistralLlm(openai_instance=mistral, config=self._config)
        elif llm_enum == ConversationProvider.GROQ:
            api_key = await self._retrieve_secret("groq", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, GroqLlm

            groq = OpenAi(api_key=api_key, base_url=self._config.groq.endpoint)
            return GroqLlm(openai_instance=groq, config=self._config)
        elif llm_enum == ConversationProvider.CEREBRAS:
            api_key = await self._retrieve_secret("cerebras", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, CerebrasLlm

            cerebras = OpenAi(api_key=api_key, base_url=self._config.cerebras.endpoint)
            return CerebrasLlm(openai_instance=cerebras, config=self._config)
        elif llm_enum == ConversationProvider.GOOGLE:
            api_key = await self._retrieve_secret("google", errors)
            if not api_key:
                return None
            from providers.google import GoogleGenAI, GoogleLlm

            google = GoogleGenAI(api_key=api_key)
            return GoogleLlm(google_instance=google, config=self._config)
        elif llm_enum == ConversationProvider.OPENROUTER:
            api_key = await self._retrieve_secret("openrouter", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, OpenRouterLlm

            openrouter = OpenAi(
                api_key=api_key, base_url=self._config.openrouter.endpoint
            )
            supports_tools = await self._check_openrouter_tool_support(api_key)
            return OpenRouterLlm(
                openai_instance=openrouter,
                config=self._config,
                supports_tools=supports_tools,
            )
        elif llm_enum == ConversationProvider.LOCAL_LLM:
            from providers.open_ai import OpenAi, LocalLlm

            local_llm = None
            if self._config.local_llm.endpoint:
                local_llm = OpenAi(
                    api_key=await self._retrieve_optional_secret("local_llm"),
                    base_url=self._config.local_llm.endpoint,
                )
            return LocalLlm(openai_instance=local_llm, config=self._config)
        elif llm_enum == ConversationProvider.WINGMAN_PRO:
            from providers.wingman_subscription import (
                WingmanSubscription,
                WingmanSubscriptionLlm,
            )

            ws = WingmanSubscription(
                wingman_name=self._wingman_name,
                settings=self._settings.wingman_pro,
            )
            return WingmanSubscriptionLlm(ws_instance=ws, config=self._config)
        elif llm_enum == ConversationProvider.PERPLEXITY:
            api_key = await self._retrieve_secret("perplexity", errors)
            if not api_key:
                return None
            from providers.open_ai import OpenAi, PerplexityLlm

            perplexity = OpenAi(
                api_key=api_key, base_url=self._config.perplexity.endpoint
            )
            return PerplexityLlm(openai_instance=perplexity, config=self._config)
        elif llm_enum == ConversationProvider.XAI:
            api_key = await self._retrieve_secret("xai", errors)
            if not api_key:
                return None
            from providers.x_ai import XAi, XAiLlm

            xai = XAi(api_key=api_key, base_url=self._config.xai.endpoint)
            return XAiLlm(xai_instance=xai, config=self._config)
        return None

    async def _check_openrouter_tool_support(self, api_key: str) -> bool:
        """Check if the configured OpenRouter model supports tools.

        Replicates the logic from OpenAiWingman.validate_and_set_openrouter().
        """
        try:
            import asyncio
            import requests

            model = self._config.openrouter.conversation_model

            def _fetch():
                return requests.get(
                    f"https://openrouter.ai/api/v1/models/{model}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )

            response = await asyncio.to_thread(_fetch)
            if response.status_code == 200:
                result = response.json()
                supported_params = result.get("data", {}).get(
                    "supported_parameters", []
                )
                return "tools" in supported_params
        except Exception:
            pass
        return False

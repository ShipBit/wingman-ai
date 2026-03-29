from typing import Optional

from api.enums import LogType
from api.interface import LlamaCppSettings
from providers.llama_cpp_provider import LlamaCppProvider
from providers.llama_cpp_remote import LlamaCppRemote
from services.local_model_manager import LocalModelManager
from services.printr import Printr

printr = Printr()


class LocalAiService:
    """Unified facade that routes support/embed calls to local or remote provider."""

    def __init__(
        self,
        provider: LlamaCppProvider,
        remote: LlamaCppRemote,
        settings: LlamaCppSettings,
    ):
        self.provider = provider
        self.remote = remote
        self.settings = settings

    async def update_settings_async(self, new_settings: LlamaCppSettings):
        """Handle settings changes including local↔remote toggle."""
        old = self.settings
        self.settings = new_settings

        self.provider.update_settings(new_settings)
        self.remote.update_settings(new_settings)

        if old.run_locally and not new_settings.run_locally:
            await printr.print_async(
                "Switched to remote mode — local models unloaded.",
                color=LogType.INFO,
                server_only=True,
            )
        elif not old.run_locally and new_settings.run_locally:
            await self.initialize()
        elif old.run_locally and new_settings.run_locally:
            # Backend or model changed while staying in local mode —
            # provider already killed old processes, now re-initialize.
            backend_changed = old.gpu_backend != new_settings.gpu_backend
            model_changed = (
                old.support_model != new_settings.support_model
                or old.embed_model != new_settings.embed_model
            )
            config_changed = (
                old.n_ctx != new_settings.n_ctx
                or old.n_threads != new_settings.n_threads
                or old.reasoning_effort != new_settings.reasoning_effort
            )
            if backend_changed or model_changed or config_changed:
                await self.initialize()

    def support(
        self,
        text: str,
        system_prompt: str = "",
        max_tokens: int = 512,
    ) -> "SupportResult":
        """Process text using the active provider's support model (local or remote).

        Returns a SupportResult with text, token usage, and truncation flag.
        """
        from providers.llama_cpp_provider import SupportResult

        if not system_prompt:
            from services.file import get_prompt

            system_prompt = get_prompt("support-default")
        if self.settings.run_locally:
            return self.provider.support(text, system_prompt, max_tokens)
        return self.remote.support(text, system_prompt, max_tokens)

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings using the active provider (local or remote)."""
        if self.settings.run_locally:
            return self.provider.embed(texts)
        return self.remote.embed(texts)

    def is_ready(self) -> bool:
        """Check if the active provider is ready."""
        if self.settings.run_locally:
            return self.provider.is_ready()
        return self.remote.is_ready()

    def get_embed_model_name(self) -> str | None:
        """Return the embed model filename, or None if not configured."""
        name = getattr(self.settings, "embed_model", None)
        if not name:
            return None
        # Strip path and extension for display
        from os.path import basename, splitext

        return splitext(basename(name))[0]

    async def initialize(self):
        """Eagerly load local models if run_locally is on and models are available."""
        if not self.settings.run_locally:
            return

        if not self.provider.model_manager.models_available():
            printr.print(
                "[Local AI] Skipping initialization — models not downloaded.",
                color=LogType.WARNING,
                server_only=True,
            )
            return

        await printr.print_async(
            "[Local AI] Initializing local models...",
            color=LogType.INFO,
            server_only=True,
        )
        ok_sum = self.provider.load_support_model()
        ok_emb = self.provider.load_embed_model()
        if ok_sum and ok_emb:
            await printr.print_async(
                "[Local AI] Both models loaded and ready.",
                color=LogType.INFO,
                server_only=True,
            )
        else:
            await printr.print_async(
                f"[Local AI] Model loading incomplete (support={'ok' if ok_sum else 'FAILED'}, embed={'ok' if ok_emb else 'FAILED'}).",
                color=LogType.WARNING,
                server_only=True,
            )

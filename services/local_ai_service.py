from typing import Optional

from api.enums import LogType
from api.interface import LlamaCppSettings
from providers.llama_cpp_provider import LlamaCppProvider
from providers.llama_cpp_remote import LlamaCppRemote
from services.local_model_manager import LocalModelManager
from services.printr import Printr

printr = Printr()


class LocalAiService:
    """Unified facade that routes summarize/embed calls to local or remote provider."""

    def __init__(
        self,
        provider: LlamaCppProvider,
        remote: LlamaCppRemote,
        settings: LlamaCppSettings,
    ):
        self.provider = provider
        self.remote = remote
        self.settings = settings

    def update_settings(self, new_settings: LlamaCppSettings):
        """Handle settings changes including local↔remote toggle."""
        old_run_locally = self.settings.run_locally
        self.settings = new_settings

        self.provider.update_settings(new_settings)
        self.remote.update_settings(new_settings)

        if old_run_locally and not new_settings.run_locally:
            printr.print(
                "Switched to remote mode — local models unloaded.",
                color=LogType.INFO,
                server_only=True,
            )
        elif not old_run_locally and new_settings.run_locally:
            printr.print(
                "Switched to local mode — models will load on next use.",
                color=LogType.INFO,
                server_only=True,
            )

    def summarize(
        self,
        text: str,
        system_prompt: str = "You are a helpful assistant that summarizes text concisely.",
    ) -> Optional[str]:
        """Summarize text using the active provider (local or remote)."""
        if self.settings.run_locally:
            return self.provider.summarize(text, system_prompt)
        return self.remote.summarize(text, system_prompt)

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

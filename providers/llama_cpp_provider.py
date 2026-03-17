import gc
from typing import Optional

from api.enums import LogType
from api.interface import LlamaCppSettings
from services.local_model_manager import LocalModelManager
from services.printr import Printr

printr = Printr()


class LlamaCppProvider:
    """Local llama.cpp provider for summarization and embedding using GGUF models."""

    def __init__(
        self,
        settings: LlamaCppSettings,
        model_manager: LocalModelManager,
    ):
        self.settings = settings
        self.model_manager = model_manager
        self._summarize_model = None
        self._embed_model = None

    def load_summarize_model(self) -> bool:
        """Load the summarization model. Returns True on success."""
        if self._summarize_model is not None:
            return True

        if not self.model_manager.summarize_model_available():
            printr.print(
                "Summarize model not downloaded yet.",
                color=LogType.WARNING,
                server_only=True,
            )
            return False

        try:
            from llama_cpp import Llama

            model_path = self.model_manager.get_summarize_model_path()
            printr.print(
                f"Loading summarize model: {model_path}",
                color=LogType.INFO,
                server_only=True,
            )
            self._summarize_model = Llama(
                model_path=model_path,
                n_ctx=4096,
                n_threads=4,
                verbose=False,
            )
            printr.print(
                "Summarize model loaded successfully.",
                color=LogType.INFO,
                server_only=True,
            )
            return True
        except Exception as e:
            printr.print(
                f"Failed to load summarize model: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            self._summarize_model = None
            return False

    def load_embed_model(self) -> bool:
        """Load the embedding model. Returns True on success."""
        if self._embed_model is not None:
            return True

        if not self.model_manager.embed_model_available():
            printr.print(
                "Embed model not downloaded yet.",
                color=LogType.WARNING,
                server_only=True,
            )
            return False

        try:
            from llama_cpp import Llama

            model_path = self.model_manager.get_embed_model_path()
            printr.print(
                f"Loading embed model: {model_path}",
                color=LogType.INFO,
                server_only=True,
            )
            self._embed_model = Llama(
                model_path=model_path,
                n_ctx=2048,
                n_threads=4,
                embedding=True,
                verbose=False,
            )
            printr.print(
                "Embed model loaded successfully.",
                color=LogType.INFO,
                server_only=True,
            )
            return True
        except Exception as e:
            printr.print(
                f"Failed to load embed model: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            self._embed_model = None
            return False

    def unload_models(self):
        """Unload both models and free memory."""
        if self._summarize_model is not None:
            del self._summarize_model
            self._summarize_model = None
            printr.print(
                "Summarize model unloaded.",
                color=LogType.INFO,
                server_only=True,
            )
        if self._embed_model is not None:
            del self._embed_model
            self._embed_model = None
            printr.print(
                "Embed model unloaded.",
                color=LogType.INFO,
                server_only=True,
            )
        gc.collect()

    def update_settings(self, new_settings: LlamaCppSettings):
        """Update settings. If run_locally changed or models changed, handle load/unload."""
        old = self.settings
        self.settings = new_settings
        self.model_manager.update_settings(new_settings)

        if old.run_locally and not new_settings.run_locally:
            # Switched from local to remote — unload models
            self.unload_models()
        elif new_settings.run_locally:
            # If model files changed, unload so they reload on next use
            if old.summarize_model != new_settings.summarize_model:
                if self._summarize_model is not None:
                    del self._summarize_model
                    self._summarize_model = None
                    gc.collect()
            if old.embed_model != new_settings.embed_model:
                if self._embed_model is not None:
                    del self._embed_model
                    self._embed_model = None
                    gc.collect()

    def summarize(
        self,
        text: str,
        system_prompt: str = "You are a helpful assistant that summarizes text concisely.",
    ) -> Optional[str]:
        """Summarize text using the local Qwen model. Loads model on first call."""
        if not self.load_summarize_model():
            return None

        try:
            result = self._summarize_model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            printr.print(
                f"Summarization failed: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings for a list of texts. Loads model on first call."""
        if not self.load_embed_model():
            return None

        try:
            results = []
            for text in texts:
                embedding = self._embed_model.embed(text)
                # llama-cpp-python returns list[float] for single text
                if isinstance(embedding[0], list):
                    results.append(embedding[0])
                else:
                    results.append(embedding)
            return results
        except Exception as e:
            printr.print(
                f"Embedding failed: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

    def is_ready(self) -> bool:
        """Check if models are loaded and responsive."""
        return self._summarize_model is not None or self._embed_model is not None

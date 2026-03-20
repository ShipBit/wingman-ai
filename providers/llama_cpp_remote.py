from typing import Optional

from openai import OpenAI

from api.enums import LogType
from api.interface import LlamaCppSettings
from services.printr import Printr

printr = Printr()


class LlamaCppRemote:
    """Remote llama.cpp client using the OpenAI-compatible API that llama-server exposes."""

    def __init__(self, settings: LlamaCppSettings):
        self.settings = settings
        self._summarize_client: Optional[OpenAI] = None
        self._embed_client: Optional[OpenAI] = None
        self._init_clients()

    def _init_clients(self):
        """Initialize OpenAI clients pointing at remote llama-server endpoints."""
        summarize_url = f"{self.settings.summarize_remote_host}:{self.settings.summarize_remote_port}/v1"
        embed_url = (
            f"{self.settings.embed_remote_host}:{self.settings.embed_remote_port}/v1"
        )

        self._summarize_client = OpenAI(
            base_url=summarize_url,
            api_key="not-needed",
        )
        self._embed_client = OpenAI(
            base_url=embed_url,
            api_key="not-needed",
        )

    def update_settings(self, new_settings: LlamaCppSettings):
        """Update settings and reinitialize clients if endpoints changed."""
        old = self.settings
        self.settings = new_settings

        if (
            old.summarize_remote_host != new_settings.summarize_remote_host
            or old.summarize_remote_port != new_settings.summarize_remote_port
            or old.embed_remote_host != new_settings.embed_remote_host
            or old.embed_remote_port != new_settings.embed_remote_port
        ):
            self._init_clients()

    def summarize(
        self,
        text: str,
        system_prompt: str = "",
        max_tokens: int = 512,
    ) -> "SummarizeResult":
        """Summarize text via remote llama-server."""
        from providers.llama_cpp_provider import SummarizeResult

        if not system_prompt:
            from services.file import get_prompt

            system_prompt = get_prompt("summarize-default")
        try:
            response = self._summarize_client.chat.completions.create(
                model="local-model",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
                frequency_penalty=0.5,
                presence_penalty=0.3,
            )
            raw = response.choices[0].message.content
            cleaned = self._deduplicate_lines(raw) if raw else None

            prompt_tokens = 0
            completion_tokens = 0
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens or 0
                completion_tokens = response.usage.completion_tokens or 0

            truncated = (
                response.choices[0].finish_reason == "length"
                if response.choices
                else False
            )

            return SummarizeResult(
                text=cleaned,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                truncated=truncated,
            )
        except Exception as e:
            printr.print(
                f"Remote summarization failed: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return SummarizeResult(text=None)

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings via remote llama-server."""
        try:
            response = self._embed_client.embeddings.create(
                model="local-model",
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            printr.print(
                f"Remote embedding failed: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

    def is_ready(self) -> bool:
        """Non-blocking connectivity check. Logs warnings but doesn't block."""
        try:
            # Quick health check on summarize endpoint
            self._summarize_client.models.list()
            return True
        except Exception:
            return False

    @staticmethod
    def _deduplicate_lines(text: str) -> str:
        """Remove duplicate lines from model output to fix small-model repetition loops."""
        seen = set()
        result = []
        for line in text.split("\n"):
            normalized = line.strip().lower()
            if not normalized or normalized not in seen:
                seen.add(normalized)
                result.append(line)
        return "\n".join(result).strip()

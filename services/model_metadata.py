import time
from typing import Optional

import aiohttp

from api.enums import LogType
from services.printr import Printr

printr = Printr()

LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
CACHE_TTL_SECONDS = 3600  # 1 hour


class ModelMetadata:
    def __init__(self, data: dict):
        self.supports_vision: bool = data.get("supports_vision", False)
        self.supports_tool_calling: bool = data.get(
            "supports_function_calling", False
        )
        self.supports_response_schema: bool = data.get(
            "supports_response_schema", False
        )
        self.supports_prompt_caching: bool = data.get(
            "supports_prompt_caching", False
        )
        self.supports_reasoning: bool = data.get("supports_reasoning", False)
        self.max_tokens: Optional[int] = data.get("max_tokens")
        self.max_input_tokens: Optional[int] = data.get("max_input_tokens")
        self.max_output_tokens: Optional[int] = data.get("max_output_tokens")
        self.input_cost_per_token: Optional[float] = data.get(
            "input_cost_per_token"
        )
        self.output_cost_per_token: Optional[float] = data.get(
            "output_cost_per_token"
        )

    def to_dict(self) -> dict:
        return {
            "supports_vision": self.supports_vision,
            "supports_tool_calling": self.supports_tool_calling,
            "supports_response_schema": self.supports_response_schema,
            "supports_prompt_caching": self.supports_prompt_caching,
            "supports_reasoning": self.supports_reasoning,
            "max_tokens": self.max_tokens,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "input_cost_per_token": self.input_cost_per_token,
            "output_cost_per_token": self.output_cost_per_token,
        }


class ModelMetadataService:
    def __init__(self):
        self._cache: dict[str, ModelMetadata] = {}
        self._last_fetch: float = 0

    def _is_cache_valid(self) -> bool:
        return bool(self._cache) and (
            time.time() - self._last_fetch < CACHE_TTL_SECONDS
        )

    async def _fetch(self):
        if self._is_cache_valid():
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    LITELLM_URL, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    resp.raise_for_status()
                    raw = await resp.json(content_type=None)
        except Exception as e:
            printr.print(
                f"Failed to fetch model metadata: {e}",
                color=LogType.WARNING,
                server_only=True,
            )
            return

        self._cache = {}
        for model_id, data in raw.items():
            if isinstance(data, dict):
                self._cache[model_id] = ModelMetadata(data)
        self._last_fetch = time.time()

    async def get_all(self) -> dict[str, dict]:
        await self._fetch()
        return {mid: m.to_dict() for mid, m in self._cache.items()}

    async def get(self, model_id: str) -> Optional[dict]:
        await self._fetch()
        # Exact match
        meta = self._cache.get(model_id)
        if meta:
            return meta.to_dict()
        # Prefix match (e.g., "gpt-4o" matches "gpt-4o-2024-...")
        for cached_id, meta in self._cache.items():
            if cached_id.startswith(model_id):
                return meta.to_dict()
        return None

    async def supports_vision(self, model_id: str) -> bool:
        meta = await self.get(model_id)
        return meta.get("supports_vision", False) if meta else False

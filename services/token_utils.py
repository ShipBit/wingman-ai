"""Unified token counting utility for Wingman AI.

Uses tiktoken with cl100k_base encoding as a reliable approximation
for all models (including Qwen). Not exact for non-OpenAI tokenizers,
but far more accurate than len(text)//4 heuristics.

Falls back to a character-based estimate if tiktoken is unavailable
(e.g. encoding data missing in a bundled build).
"""

from functools import lru_cache
from typing import Optional

import tiktoken

_USE_TIKTOKEN: Optional[bool] = None


@lru_cache(maxsize=1)
def _get_encoding() -> Optional[tiktoken.Encoding]:
    global _USE_TIKTOKEN
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        _USE_TIKTOKEN = True
        return enc
    except (ValueError, LookupError):
        _USE_TIKTOKEN = False
        return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    if not text:
        return 0
    enc = _get_encoding()
    if enc is not None:
        return len(enc.encode(text))
    return _estimate_tokens(text)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to a maximum number of tokens, cutting at a token boundary."""
    enc = _get_encoding()
    if enc is not None:
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    # Fallback: estimate 4 chars per token
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars]

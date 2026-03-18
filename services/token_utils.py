"""Unified token counting utility for Wingman AI.

Uses tiktoken with cl100k_base encoding as a reliable approximation
for all models (including Qwen). Not exact for non-OpenAI tokenizers,
but far more accurate than len(text)//4 heuristics.
"""

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _get_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count the number of tokens in a text string."""
    if not text:
        return 0
    return len(_get_encoding().encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to a maximum number of tokens, cutting at a token boundary."""
    enc = _get_encoding()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])

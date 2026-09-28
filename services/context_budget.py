"""How much Wingman may send, computed from the model it is talking to.

Three numbers decide every shortening in Core (see docs/context-and-shortening.md):

- ``tool_cap``: the most one tool response, or one skill's ``ai.generate`` input,
  may bring. Over it the content is cut, entry by entry or line by line.
- ``history_limit``: below it nothing in the history is touched. Above it old
  tool output is cleared first, and only if that is not enough, older turns
  are summarized.
- ``brake``: the most a request may be. Over it the oldest turns go.

Each is the smaller of an absolute ceiling and a share of the main model's
context window. The ceilings protect the user's allowance from a skill that
returns half a million tokens; the shares keep a small model from being sent
more than it can read. Nothing here depends on the support model: it reads
whatever it is given in chunks that fit its own window.

Measured on 2026-09-28 (evals/FINDINGS-context-budget-2026-09-28.md): with the
history left alone up to 64k, gpt-4.1-mini answered 8 of 10 questions about
data 3 to 36 turns old and invented nothing; with the old rules it answered 4
and invented 3 numbers. A normal trading session costs the same, a long
tool-heavy evening about twice as much.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from api.enums import ConversationProvider

if TYPE_CHECKING:
    from api.interface import WingmanConfig

TOOL_CAP_TOKENS = 32_000
"""A tool response or skill side-call never brings more than this."""

HISTORY_CAP_TOKENS = 64_000
"""The history is left alone until a request passes this."""

KEEP_SHARE = 0.25
"""Share of ``history_limit`` that stays word for word when the history is shortened."""

KEEP_TURNS = 4
"""The last turns that always stay word for word, however big they are."""

BRAKE_SHARE = 0.9
"""A request may fill this share of the main model's window."""

SUBSCRIPTION_MAX_REQUEST_CHARS = 320_000
"""80% of the Wingman backend's ``MAX_MESSAGES_BYTES`` (400,000 characters of
JSON, about 100,000 tokens), for the subscription's brake. The backend measures
``JSON.stringify`` of what it receives, Core the messages before the OpenAI
client serializes them; the margin covers the difference."""

DEFAULT_WINDOW = 128_000
"""A model we know nothing about. A smaller one says so when it overflows, and
the wingman learns its window from that (see ``learn_window``)."""

LOCAL_LLM_WINDOW = 32_000
"""Local models are usually run with a small context. Guessing high would make
the first long request fail; guessing low only cuts earlier."""

# Known windows, matched on a substring of the model id. First match wins, so
# the more specific name comes first.
_KNOWN_WINDOWS: tuple[tuple[str, int], ...] = (
    ("gpt-4.1", 1_047_576),
    ("gpt-5", 400_000),
    ("gpt-4o", 128_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("gemini", 1_048_576),
    ("gemma", 128_000),
    ("claude", 200_000),
    ("deepseek", 128_000),
    ("glm", 128_000),
    ("qwen", 128_000),
    ("grok", 256_000),
    ("llama", 128_000),
    ("mistral", 128_000),
    ("sonar", 128_000),
)

# Phrases providers use when a request is larger than the model's window. Kept
# narrow on purpose: Groq says "Request too large" for its per-minute token
# limit, which has nothing to do with the window.
_OVERFLOW_PHRASES = (
    "context_length_exceeded",
    "maximum context length",
    "context length",
    "context window",
    "exceeds the available context",
    "prompt is too long",
    "input is too long",
    "too many tokens",
    "reduce the length",
)


class ContextOverflowError(Exception):
    """The provider refused a request as larger than the model's window."""


def is_context_overflow(message: str) -> bool:
    text = (message or "").lower()
    return any(phrase in text for phrase in _OVERFLOW_PHRASES)


@dataclass(frozen=True)
class ContextBudget:
    window: int
    """The main model's context window, in tokens."""

    @property
    def tool_cap(self) -> int:
        return min(TOOL_CAP_TOKENS, self.window // 4)

    @property
    def history_limit(self) -> int:
        return min(HISTORY_CAP_TOKENS, self.window // 2)

    @property
    def keep_tokens(self) -> int:
        return int(self.history_limit * KEEP_SHARE)

    @property
    def brake(self) -> int:
        return int(self.window * BRAKE_SHARE)


def conversation_model(config: "WingmanConfig") -> str:
    provider = config.features.conversation_provider
    if provider == ConversationProvider.WINGMAN_PRO:
        return config.wingman_pro.conversation_deployment or ""
    section = getattr(config, provider.value, None)
    model = getattr(section, "conversation_model", None) if section else None
    return str(getattr(model, "value", model) or "")


def model_window(
    config: "WingmanConfig",
    reported: Optional[int] = None,
    learned: Optional[int] = None,
) -> int:
    """The main model's window: what the wingman learned from an overflow,
    else what the provider reported (OpenRouter), else the table, else a
    default for the provider."""
    if learned:
        return learned
    if reported:
        return reported
    model = conversation_model(config).lower()
    for fragment, window in _KNOWN_WINDOWS:
        if fragment in model:
            return window
    if config.features.conversation_provider == ConversationProvider.LOCAL_LLM:
        return LOCAL_LLM_WINDOW
    return DEFAULT_WINDOW


def learn_window(request_tokens: int) -> int:
    """The window to assume after a request of ``request_tokens`` overflowed:
    comfortably below it, so the retry fits."""
    return max(4_000, int(request_tokens * 0.75))

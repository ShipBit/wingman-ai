from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from api.enums import LocalAiMode, LogType
from api.interface import LlamaCppSettings
from providers.llama_cpp_provider import LlamaCppProvider
from providers.llama_cpp_remote import LlamaCppRemote
from providers.wingman_support import WingmanSupport
from services.local_model_manager import LocalModelManager
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from services.skill_local_ai import SamplingPreset

printr = Printr()

# ── Constants ──────────────────────────────────────────────────────

SAFETY_MARGIN = 0.9
"""10% safety buffer to account for tokenizer differences between
cl100k_base (used for estimation) and the model's actual tokenizer."""

MIN_OUTPUT_TOKENS = 256
"""Minimum output tokens reserved for a non-thinking call."""

CLOUD_MAX_OUTPUT_TOKENS = 8_192
"""Hard ceiling on what a cloud support call may generate.

Every support job is short: a summary, a handful of extracted facts, a squeezed
tool response. Without this the budget is "whatever is left of the window", so a
2,000-token extraction asks for roughly 113,000 tokens of output. Locally that
could not happen — llama.cpp is bounded by ``n_ctx``, usually 4096.

It normally costs nothing, because the model stops when it is done. It costs
real money on the day a model gets stuck repeating itself, which is exactly what
``_deduplicate_lines`` exists to clean up after.
"""

CLOUD_CONTEXT_TOKENS = 128_000
"""Context window assumed for a cloud support model.

The real models offer far more — gemini-2.5-flash-lite has a million — but Core
does not know which one answered, and an unbounded budget would mean a runaway
tool response gets sent in full and billed in full. The largest thing we measured
is a 78k-token trade table, so this never chunks anything real and still caps the
pathological case."""

REASONING_OUTPUT_TOKENS = 1024
"""Output tokens to reserve when reasoning is enabled. The <think> block shares
the output budget with the answer, so a 256-token reservation (fine for plain
output) gets eaten by thinking and truncates the answer. Reserve more headroom.

This is an absolute target — a 2B model's think block is roughly constant in
size regardless of context window — but ``_output_reservation`` caps it at half
the usable context so a small ``n_ctx`` still leaves room for input. Validated
against the real model in the internal eval suite; retune there if needed.
"""


def _output_reservation(reasoning: bool, safe_ctx: int) -> int:
    """Output tokens to reserve for a call, respecting the user's context size.

    Non-thinking calls reserve ``MIN_OUTPUT_TOKENS``. Thinking calls reserve
    ``REASONING_OUTPUT_TOKENS`` so the <think> block and the answer both fit,
    but never more than half of ``safe_ctx`` — on a small ``n_ctx`` we'd rather
    chunk the input than starve it.
    """
    if not reasoning:
        return MIN_OUTPUT_TOKENS
    return min(REASONING_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, safe_ctx // 2))

# Qwen3.5 non-thinking sampling defaults (HuggingFace-recommended). Used as the
# final fallback when a support call passes neither explicit sampling args nor a
# SamplingPreset. Not user-configurable — callers that need different values use
# a SamplingPreset or pass args directly.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_TOP_K = 20
DEFAULT_PRESENCE_PENALTY = 2.0


# ── Token Budget ───────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenBudget:
    """Token budget computed from the model's context window.

    Use ``max_input_tokens`` to decide how much text fits in a single call
    (for chunking decisions). The actual output budget is computed per-call
    inside ``support()`` based on the real input size.
    """

    n_ctx: int
    """Raw context window from user settings."""

    safe_ctx: int
    """Usable context after safety margin (n_ctx * SAFETY_MARGIN)."""

    system_tokens: int
    """Estimated tokens consumed by the system prompt."""

    max_input_tokens: int
    """Maximum user-text tokens that fit alongside the system prompt,
    with ``MIN_OUTPUT_TOKENS`` reserved for the response."""

    min_output_tokens: int
    """Output tokens reserved for this budget — ``MIN_OUTPUT_TOKENS`` normally,
    more when ``reasoning=True`` (see ``_output_reservation``)."""


# ── Service ────────────────────────────────────────────────────────

class LocalAiService:
    """Unified facade that routes support/embed calls to local or remote provider.

    All token budget calculations are centralised here. Callers should never
    access ``n_ctx`` or compute output budgets themselves — use
    ``get_token_budget()`` for planning and ``support()`` for execution.
    """

    def __init__(
        self,
        provider: LlamaCppProvider,
        remote: LlamaCppRemote,
        cloud: WingmanSupport,
        settings: LlamaCppSettings,
    ):
        self.provider = provider
        self.remote = remote
        self.cloud = cloud
        self.settings = settings

    async def update_settings_async(self, new_settings: LlamaCppSettings):
        """Handle settings changes, including a switch between the three modes."""
        old = self.settings
        self.settings = new_settings

        self.provider.update_settings(new_settings)
        self.remote.update_settings(new_settings)
        self.cloud.update_settings(new_settings)

        if old.mode == new_settings.mode == LocalAiMode.SERVER:
            return

        if new_settings.mode == LocalAiMode.SERVER:
            await printr.print_async(
                "Support model moved to your own server — local models unloaded.",
                color=LogType.INFO,
                server_only=True,
            )
            return

        if old.mode != new_settings.mode:
            await self.initialize()
            return

        # Same mode, but something the local processes were started with changed.
        backend_changed = old.gpu_backend != new_settings.gpu_backend
        model_changed = (
            old.support_model != new_settings.support_model
            or old.embed_model != new_settings.embed_model
        )
        config_changed = (
            old.n_ctx != new_settings.n_ctx or old.n_threads != new_settings.n_threads
        )
        if backend_changed or model_changed or config_changed:
            await self.initialize()

    def update_subscription(self, subscription):
        """The backend address changed — cloud support calls have to follow it.

        Separate from :meth:`update_settings_async` because it comes from a
        different part of the settings, and because the dev/prod switch
        (`WINGMAN_BACKEND_URL`) moves it without any llama.cpp setting changing.
        """
        self.cloud.update_subscription(subscription)

    # ── Token budget API ───────────────────────────────────────────

    def _context_window(self) -> int:
        """The context window to plan against, for whichever model is answering.

        ``n_ctx`` is the user's setting for llama.cpp and means nothing to a
        cloud model, which has its own — far larger — window.
        """
        if self.settings.mode == LocalAiMode.CLOUD:
            return CLOUD_CONTEXT_TOKENS
        return self.settings.n_ctx

    def get_token_budget(
        self, system_prompt: str = "", reasoning: bool = False
    ) -> TokenBudget:
        """Compute the token budget for a support model call.

        Returns a ``TokenBudget`` telling callers how much input text they can
        send alongside the given ``system_prompt``.  Use this for planning
        (e.g. deciding whether to chunk) — the actual output cap is computed
        inside ``support()`` per-call.

        Pass ``reasoning=True`` to mirror a thinking call: more output is
        reserved (so chunked callers leave room for the <think> block), which
        lowers ``max_input_tokens`` and yields smaller chunks.
        """
        n_ctx = self._context_window()
        safe_ctx = int(n_ctx * SAFETY_MARGIN)
        system_tokens = count_tokens(system_prompt) if system_prompt else 0
        min_output = _output_reservation(reasoning, safe_ctx)
        max_input = max(0, safe_ctx - system_tokens - min_output)

        return TokenBudget(
            n_ctx=n_ctx,
            safe_ctx=safe_ctx,
            system_tokens=system_tokens,
            max_input_tokens=max_input,
            min_output_tokens=min_output,
        )

    # ── Support model call ─────────────────────────────────────────

    def support(
        self,
        text: str,
        system_prompt: str = "",
        preset: SamplingPreset | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        presence_penalty: float | None = None,
        reasoning: bool | None = None,
        max_output_tokens: int | None = None,
    ) -> "SupportResult":
        """Process text using the support model (local or remote).

        The output token budget is computed automatically from the context
        window (``n_ctx``). ``max_output_tokens`` lowers it further for calls
        whose answer must stay small — a summary that is allowed to be as long
        as the window costs money on the day the model decides to use it all.

        Sampling resolution order (highest priority first):
        1. Per-call keyword arguments (temperature, top_p, etc.)
        2. ``preset`` (a ``SamplingPreset`` enum member)
        3. Qwen3.5 default constants (DEFAULT_TEMPERATURE, etc.)

        ``reasoning`` controls thinking for this call and defaults to OFF (fast).
        Pass ``True`` for background quality work (memory extraction,
        summarization); leave it unset on latency-sensitive paths.

        Returns a ``SupportResult`` with text, token usage, and truncation flag.
        """
        from providers.llama_cpp_provider import SupportResult

        if not system_prompt:
            from services.file import get_prompt
            system_prompt = get_prompt("support-default")

        safe_ctx = int(self._context_window() * SAFETY_MARGIN)
        system_tokens = count_tokens(system_prompt)
        # Reasoning shares the output budget with the <think> block, so reserve
        # more output (and truncate input more aggressively) on thinking calls.
        min_output = _output_reservation(bool(reasoning), safe_ctx)
        max_input = safe_ctx - system_tokens - min_output
        if count_tokens(text) > max_input:
            text = truncate_to_tokens(text, max(0, max_input))
        input_tokens = system_tokens + count_tokens(text)
        max_tokens = max(min_output, safe_ctx - input_tokens)
        if self.settings.mode == LocalAiMode.CLOUD:
            max_tokens = min(max_tokens, CLOUD_MAX_OUTPUT_TOKENS)
        if max_output_tokens is not None:
            max_tokens = max(1, min(max_tokens, max_output_tokens))

        # Resolve sampling: explicit args > preset > Qwen3.5 default constants
        t = temperature
        p = top_p
        k = top_k
        pp = presence_penalty
        if preset is not None:
            if t is None:
                t = preset.temperature
            if p is None:
                p = preset.top_p
            if k is None:
                k = preset.top_k
            if pp is None:
                pp = preset.presence_penalty
        t = t if t is not None else DEFAULT_TEMPERATURE
        p = p if p is not None else DEFAULT_TOP_P
        k = k if k is not None else DEFAULT_TOP_K
        pp = pp if pp is not None else DEFAULT_PRESENCE_PENALTY

        if self.settings.mode == LocalAiMode.CLOUD:
            return self.cloud.support(
                text, system_prompt, max_tokens, t, p, k, pp, reasoning
            )
        if self.settings.mode == LocalAiMode.LOCAL:
            return self.provider.support(
                text, system_prompt, max_tokens, t, p, k, pp, reasoning
            )
        return self.remote.support(
            text, system_prompt, max_tokens, t, p, k, pp, reasoning
        )

    # ── Embeddings ─────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings for the local vector database.

        Cloud mode keeps these on this machine: the vectors already stored were
        computed by this model, and ones from another model would not be
        comparable to them. The embedding server is a sixth of the support
        model's size, so it is not what was costing testers their hardware.
        """
        if self.settings.mode == LocalAiMode.SERVER:
            return self.remote.embed(texts)
        return self.provider.embed(texts)

    # ── Status ─────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Whether a support call can be made right now.

        This gates every feature built on the support model, so it has to be
        cheap: memory, condensation and tool compression each ask before they
        start.
        """
        if self.settings.mode == LocalAiMode.CLOUD:
            return self.cloud.is_ready()
        if self.settings.mode == LocalAiMode.LOCAL:
            return self.provider.support_is_ready()
        return self.remote.is_ready()

    def embed_ready(self) -> bool:
        """Whether embeddings can be computed — the other half of memory.

        Separate from :meth:`is_ready` since cloud mode splits the two: the
        support model answers over the network while the embedding model still
        has to be downloaded and loaded here.
        """
        if self.settings.mode == LocalAiMode.SERVER:
            return self.remote.embed_is_ready()
        return self.provider.embed_is_ready()

    def get_embed_model_name(self) -> str | None:
        """Return the embed model filename, or None if not configured."""
        name = getattr(self.settings, "embed_model", None)
        if not name:
            return None
        # Strip path and extension for display
        from os.path import basename, splitext

        return splitext(basename(name))[0]

    async def initialize(self):
        """Load whatever local models this mode needs, if they are on disk.

        Nothing is downloaded here. A model arrives when the user asks for it in
        Settings — starting Wingman used to pull 1.5 GB unannounced, which is
        the wrong moment to spend somebody's bandwidth.
        """
        if self.settings.mode == LocalAiMode.SERVER:
            return

        needs_support = self.settings.mode == LocalAiMode.LOCAL

        if needs_support and not self.provider.model_manager.support_model_available():
            printr.print(
                "[Local AI] Support model is set to Local but not downloaded yet.",
                color=LogType.WARNING,
                server_only=True,
            )
        if not self.provider.model_manager.embed_model_available():
            printr.print(
                "[Local AI] Embedding model not downloaded — memory stays off.",
                color=LogType.WARNING,
                server_only=True,
            )

        await printr.print_async(
            "[Local AI] Initializing local models...",
            color=LogType.INFO,
            server_only=True,
        )

        ok_sup = (
            self.provider.load_support_model()
            if needs_support and self.provider.model_manager.support_model_available()
            else not needs_support
        )
        ok_emb = (
            self.provider.load_embed_model()
            if self.provider.model_manager.embed_model_available()
            else False
        )

        if ok_sup and ok_emb:
            await printr.print_async(
                "[Local AI] Local models loaded and ready.",
                color=LogType.INFO,
                server_only=True,
            )
        else:
            await printr.print_async(
                f"[Local AI] Model loading incomplete (support={'ok' if ok_sup else 'FAILED'}, embed={'ok' if ok_emb else 'FAILED'}).",
                color=LogType.WARNING,
                server_only=True,
            )

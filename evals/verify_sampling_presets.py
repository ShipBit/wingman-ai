"""Verify SamplingPreset behaviour — deterministic, no model required.

Presets exist so skill/Core authors who don't want to reason about sampling can
pick PRECISE / BALANCED / CREATIVE and get sensible temperature / top_p / top_k /
presence_penalty. They only earn their keep if those values actually reach the
model. This checks:

- each preset resolves to its documented four params and they reach the provider,
- a call with no preset and no args falls back to the Qwen3.5 default constants,
- explicit per-call args override the preset,
- ``reasoning`` is independent of presets (a preset never sets it) and flows through,
- the provider forwards the resolved params into the actual completion request
  (temperature/top_p/presence_penalty as args, top_k + thinking in extra_body),
- the token budget is reasoning-aware: thinking calls reserve more output (so
  the <think> block and answer both fit) and that reservation respects the
  user's n_ctx (capped at half the usable context on small windows).

Run: python evals/verify_sampling_presets.py   (exit code 0 = all passed)
"""

import sys
from os import path
from types import SimpleNamespace

REPO_ROOT = path.dirname(path.dirname(path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.llama_cpp_provider import (  # noqa: E402
    LlamaCppProvider,
    SupportResult,
    build_support_extra_body,
    resolve_enable_thinking,
)
from services.local_ai_service import (  # noqa: E402
    DEFAULT_PRESENCE_PENALTY,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_K,
    DEFAULT_TOP_P,
    LocalAiService,
)
from services.skill_local_ai import SamplingPreset  # noqa: E402
from api.enums import LocalAiMode  # noqa: E402

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))


class _RecordingProvider:
    """Captures the sampling args LocalAiService resolves and forwards on."""

    def __init__(self):
        self.last: dict | None = None

    def support(self, text, system_prompt, max_tokens, temperature, top_p,
                top_k, presence_penalty, reasoning):
        self.last = dict(
            max_tokens=max_tokens,
            temperature=temperature, top_p=top_p, top_k=top_k,
            presence_penalty=presence_penalty, reasoning=reasoning,
        )
        return SupportResult(text="ok")


def _make_service(mode=LocalAiMode.LOCAL):
    provider = _RecordingProvider()
    remote = _RecordingProvider()
    cloud = _RecordingProvider()
    settings = SimpleNamespace(n_ctx=4096, mode=mode)
    service = LocalAiService(
        provider=provider, remote=remote, cloud=cloud, settings=settings
    )
    return service, provider, remote, cloud


# 1. Each preset resolves to its documented params and reaches the provider,
#    without ever setting reasoning.
svc, provider, _, _ = _make_service()
for preset in SamplingPreset:
    svc.support(text="hello", system_prompt="sys", preset=preset)
    got = provider.last
    want = dict(temperature=preset.temperature, top_p=preset.top_p,
                top_k=preset.top_k, presence_penalty=preset.presence_penalty)
    check(f"preset {preset.name}: 4 params reach provider",
          all(got[k] == want[k] for k in want), f"got={got} want={want}")
    check(f"preset {preset.name}: does not set reasoning",
          got["reasoning"] is None, f"reasoning={got['reasoning']}")

# 2. Naked call -> Qwen3.5 default constants.
svc.support(text="hello", system_prompt="sys")
got = provider.last
check("naked call -> default constants",
      got["temperature"] == DEFAULT_TEMPERATURE and got["top_p"] == DEFAULT_TOP_P
      and got["top_k"] == DEFAULT_TOP_K and got["presence_penalty"] == DEFAULT_PRESENCE_PENALTY,
      f"got={got}")

# 3. Explicit args override the preset; untouched params still come from it.
svc.support(text="hello", system_prompt="sys",
            preset=SamplingPreset.CREATIVE, temperature=0.123, top_k=7)
got = provider.last
check("explicit temperature overrides preset", got["temperature"] == 0.123, f"temp={got['temperature']}")
check("explicit top_k overrides preset", got["top_k"] == 7, f"top_k={got['top_k']}")
check("non-overridden param still from preset",
      got["presence_penalty"] == SamplingPreset.CREATIVE.presence_penalty, f"pp={got['presence_penalty']}")

# 4. reasoning is an independent extra param, not carried by presets.
svc.support(text="hello", system_prompt="sys", preset=SamplingPreset.PRECISE, reasoning=True)
check("reasoning=True flows through alongside a preset", provider.last["reasoning"] is True)
svc.support(text="hello", system_prompt="sys", reasoning=False)
check("reasoning=False flows through", provider.last["reasoning"] is False)

# 5. Remote provider applies presets identically.
svc_r, _, remote, _ = _make_service(mode=LocalAiMode.SERVER)
svc_r.support(text="hello", system_prompt="sys", preset=SamplingPreset.BALANCED)
got = remote.last
check("remote path applies presets identically",
      got["temperature"] == SamplingPreset.BALANCED.temperature
      and got["presence_penalty"] == SamplingPreset.BALANCED.presence_penalty, f"got={got}")

# 6. Pure encoders: thinking + top_k into extra_body.
check("resolve_enable_thinking(None)=False", resolve_enable_thinking(None) is False)
check("resolve_enable_thinking(True)=True", resolve_enable_thinking(True) is True)
check("resolve_enable_thinking(False)=False", resolve_enable_thinking(False) is False)
eb_on, eb_off = build_support_extra_body(20, True), build_support_extra_body(20, False)
check("extra_body always carries top_k", eb_on.get("top_k") == 20 and eb_off.get("top_k") == 20)
check("thinking on -> no suppression", "chat_template_kwargs" not in eb_on)
check("thinking off -> enable_thinking False",
      eb_off.get("chat_template_kwargs") == {"enable_thinking": False})

# 7. Provider forwards resolved sampling into the actual completion request.
sink: dict = {}


class _FakeCompletions:
    def create(self, **kwargs):
        sink.update(kwargs)
        msg = SimpleNamespace(content="ok")
        choice = SimpleNamespace(message=msg, finish_reason="stop")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        return SimpleNamespace(choices=[choice], usage=usage)


prov = LlamaCppProvider.__new__(LlamaCppProvider)  # skip __init__ side effects
prov.settings = SimpleNamespace(n_ctx=4096)
prov._support_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
prov.load_support_model = lambda: True
prov._deduplicate_lines = lambda s: s
prov.support(text="hi", system_prompt="sys", max_tokens=64,
             temperature=0.6, top_p=0.95, top_k=20, presence_penalty=0.5, reasoning=False)
check("provider forwards temperature to create()", sink.get("temperature") == 0.6, f"got={sink.get('temperature')}")
check("provider forwards top_p to create()", sink.get("top_p") == 0.95)
check("provider forwards presence_penalty to create()", sink.get("presence_penalty") == 0.5)
check("provider puts top_k in extra_body", sink.get("extra_body", {}).get("top_k") == 20)
check("provider reasoning=False -> enable_thinking False",
      sink.get("extra_body", {}).get("chat_template_kwargs") == {"enable_thinking": False})

# 8. Token budget is reasoning-aware and respects the user's n_ctx.
from services.local_ai_service import (  # noqa: E402
    MIN_OUTPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    SAFETY_MARGIN,
    _output_reservation,
)

svc_b, prov_b, _, _ = _make_service()  # n_ctx=4096
safe_4k = int(4096 * SAFETY_MARGIN)
b_off = svc_b.get_token_budget("sys", reasoning=False)
b_on = svc_b.get_token_budget("sys", reasoning=True)
check("budget reasoning=False reserves MIN_OUTPUT_TOKENS",
      b_off.min_output_tokens == MIN_OUTPUT_TOKENS, f"got={b_off.min_output_tokens}")
check("budget reasoning=True reserves more output",
      b_on.min_output_tokens == _output_reservation(True, safe_4k)
      and b_on.min_output_tokens > MIN_OUTPUT_TOKENS, f"got={b_on.min_output_tokens}")
check("budget reasoning=True yields smaller max_input",
      b_on.max_input_tokens < b_off.max_input_tokens,
      f"on={b_on.max_input_tokens} off={b_off.max_input_tokens}")

# support() applies the reasoning output floor and truncates input to match.
huge = "word " * 20000  # far exceeds any n_ctx
svc_b.support(text=huge, system_prompt="sys", reasoning=True)
check("support reasoning=True floors max_tokens at reasoning reservation",
      prov_b.last["max_tokens"] == _output_reservation(True, safe_4k),
      f"got={prov_b.last['max_tokens']}")
svc_b.support(text=huge, system_prompt="sys", reasoning=False)
check("support reasoning=False floors max_tokens at MIN_OUTPUT_TOKENS",
      prov_b.last["max_tokens"] == MIN_OUTPUT_TOKENS, f"got={prov_b.last['max_tokens']}")

# Reservation respects context size: capped at half of safe_ctx on a small n_ctx.
small_safe = int(2048 * SAFETY_MARGIN)
check("reasoning reservation capped at half of safe_ctx on small n_ctx",
      _output_reservation(True, small_safe) == min(REASONING_OUTPUT_TOKENS, small_safe // 2)
      and _output_reservation(True, small_safe) < REASONING_OUTPUT_TOKENS,
      f"got={_output_reservation(True, small_safe)}")
check("non-reasoning reservation stays MIN_OUTPUT_TOKENS regardless of n_ctx",
      _output_reservation(False, small_safe) == MIN_OUTPUT_TOKENS)


def main() -> int:
    passed = sum(1 for _, ok, _ in _results if ok)
    for name, ok, detail in _results:
        line = f"[{'PASS' if ok else 'FAIL'}] {name}"
        if not ok and detail:
            line += f"  ({detail})"
        print(line)
    print(f"\n{passed}/{len(_results)} checks passed.")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

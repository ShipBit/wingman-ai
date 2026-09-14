"""Score condensation prompts and models against each other.

This exists to answer one question before a model goes into a subscription plan:
can it summarise a Wingman conversation without losing facts, without copying
tool plumbing, and short enough to be worth the call?

    export AI_GATEWAY_API_KEY=...

    # every shipped model against every prompt variant
    python evals/condense_suite/run.py

    # a model we are thinking about adding
    python evals/condense_suite/run.py --models deepseek/deepseek-v4.1-flash

    # one prompt, every model, including the bundled 2B
    python evals/condense_suite/run.py --prompts terse_rules --local

    # a single case while iterating on wording
    python evals/condense_suite/run.py --prompts minimal --cases tool_heavy_mcp --show

Results land in ``evals/condense_suite/results/`` as JSON so two runs can be
compared later. The score is defined in ``metrics.py``; recall carries half of
it, because a shorter summary that forgets the pilot's name is not an
improvement.

Adding a model is one entry in ``--models``. Adding a conversation shape is one
dict in ``conversations.py``. Nothing else has to change.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from evals.condense_suite import metrics  # noqa: E402
from evals.condense_suite.conversations import CONVERSATIONS, BY_NAME  # noqa: E402
from evals.condense_suite.prompt_variants import VARIANTS, user_prompt  # noqa: E402

GATEWAY = "https://ai-gateway.vercel.sh/v1"
RESULTS = Path(__file__).resolve().parent / "results"

# What the plans offer today plus the obvious candidates. The support lane runs
# on flash-lite; the chat lane models are here because a plan may want the same
# model to do both, and because this is the list a new candidate joins.
DEFAULT_MODELS = [
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.5-flash",
    "google/gemini-3.1-flash-lite",
    "google/gemini-3-flash",
    "openai/gpt-4.1-mini",
    "zai/glm-5.3-flash",
    "alibaba/qwen3.7-flash",
    "deepseek/deepseek-v4.1-flash",
]

# Thinking costs seconds and tokens and buys nothing for a summarisation pass.
# Measured per model, not read off the catalogue: the catalogue reports no
# reasoning options for qwen3.7-flash, yet it honours "none".
REASONING_OFF = {
    "google/gemini-2.5-flash": {"reasoning_effort": "none"},
    "google/gemini-2.5-flash-lite": {"reasoning_effort": "none"},
    "google/gemini-3-flash": {"reasoning_effort": "none"},
    "google/gemini-3.1-flash-lite": {"reasoning_effort": "none"},
    "zai/glm-5.3-flash": {"reasoning_effort": "none"},
    "alibaba/qwen3.7-flash": {"reasoning_effort": "none"},
    "deepseek/deepseek-v4.1-flash": {"reasoning_effort": "none"},
}

# Providers measured as usable for the one model where the gateway's own choice
# is a lottery. See supabase/migrations/20260914040000_model_providers.sql.
PROVIDER_PINS = {
    "deepseek/deepseek-v4.1-flash": {
        "gateway": {"only": ["baseten", "particle", "togetherai", "fireworks", "modal"]}
    }
}

LOCAL = "local/qwen3.5-2b"


# ── model access ──────────────────────────────────────────────────────


def _gateway_call(model: str, system: str, user: str, timeout: float = 180.0) -> dict:
    import httpx

    key = os.environ.get("AI_GATEWAY_API_KEY")
    if not key:
        raise SystemExit("Set AI_GATEWAY_API_KEY.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Enough room for a bad answer to be visibly bad rather than truncated.
        "max_tokens": 1200,
        "temperature": 0.3,
        **REASONING_OFF.get(model, {}),
    }
    if model in PROVIDER_PINS:
        payload["providerOptions"] = PROVIDER_PINS[model]

    started = time.perf_counter()
    r = httpx.post(
        f"{GATEWAY}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=timeout,
    )
    seconds = time.perf_counter() - started
    if r.status_code >= 300:
        return {"error": f"{r.status_code} {r.text[:200]}", "seconds": seconds}

    body = r.json()
    usage = body.get("usage") or {}
    return {
        "text": (body["choices"][0]["message"].get("content") or "").strip(),
        "seconds": seconds,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost": float(usage.get("cost") or 0),
    }


_local_service = None


def _local_call(system: str, user: str) -> dict:
    """The bundled 2B through the same service the product uses.

    Close the desktop app first — it holds the model ports.
    """
    global _local_service
    if _local_service is None:
        from evals.run_memory_eval import _build_local_ai

        _local_service, provider, _settings = _build_local_ai()
        if not provider.load_support_model():
            raise SystemExit(
                "Could not load the local support model. Is it downloaded and is "
                "the desktop app closed? It holds the model ports."
            )

    from services.skill_local_ai import SamplingPreset

    started = time.perf_counter()
    result = _local_service.support(
        text=user, system_prompt=system, preset=SamplingPreset.BALANCED
    )
    seconds = time.perf_counter() - started
    if not result or not result.text:
        return {"error": "local model returned nothing", "seconds": seconds}
    return {
        "text": result.text.strip(),
        "seconds": seconds,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost": 0.0,
        "truncated": result.truncated,
    }


def run_one(model: str, system: str, conversation: dict) -> dict:
    text = metrics._conversation_text(conversation["messages"])
    user = user_prompt(text)
    call = _local_call(system, user) if model == LOCAL else _gateway_call(model, system, user)
    if "error" in call:
        return {"model": model, "case": conversation["name"], **call, "score": 0.0}
    scored = metrics.evaluate(conversation, call["text"])
    return {
        "model": model,
        "case": conversation["name"],
        "summary": call["text"],
        "seconds": round(call["seconds"], 2),
        "cost": call.get("cost", 0.0),
        **scored,
    }


# ── reporting ─────────────────────────────────────────────────────────


def _mean(values):
    return statistics.mean(values) if values else 0.0


def report(rows: list[dict], show: bool) -> None:
    by_prompt_model: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_prompt_model.setdefault((r["prompt"], r["model"]), []).append(r)

    # The last column is the total for all cases of that row, not per run.
    print(f"\n{'prompt':<14} {'model':<30} {'score':>6} {'recall':>7} {'ratio':>7} "
          f"{'clean':>6} {'form':>6} {'tok':>6} {'s':>6} {'$ all':>9}")
    print("-" * 108)
    for (prompt, model), rs in sorted(
        by_prompt_model.items(), key=lambda kv: -_mean([r["score"] for r in kv[1]])
    ):
        failed = [r for r in rs if r.get("error")]
        ok = [r for r in rs if not r.get("error")]
        if not ok:
            print(f"{prompt:<14} {model:<30} {'FAILED':>6}  {failed[0]['error'][:50]}")
            continue
        print(
            f"{prompt:<14} {model:<30} "
            f"{_mean([r['score'] for r in ok]):>6.3f} "
            f"{_mean([r['recall'] for r in ok]):>7.3f} "
            f"{_mean([r['ratio'] for r in ok]):>7.3f} "
            f"{_mean([r['cleanliness'] for r in ok]):>6.3f} "
            f"{_mean([r['form'] for r in ok]):>6.3f} "
            f"{_mean([r['summary_tokens'] for r in ok]):>6.0f} "
            f"{_mean([r['seconds'] for r in ok]):>6.2f} "
            f"{sum(r['cost'] for r in ok):>9.5f}"
            + (f"   ({len(failed)} failed)" if failed else "")
        )

    worst = sorted((r for r in rows if not r.get("error")), key=lambda r: r["score"])[:6]
    if worst:
        print("\nweakest results:")
        for r in worst:
            detail = []
            if r["missing"]:
                detail.append("lost " + ", ".join(r["missing"]))
            if r["noise"]:
                detail.append("noise " + ", ".join(r["noise"][:3]))
            if r["form_problems"]:
                detail.append(", ".join(r["form_problems"]))
            print(f"  {r['score']:.3f} {r['prompt']:<13} {r['model']:<28} {r['case']:<16} "
                  + " | ".join(detail))

    if show:
        print("\n── summaries ──")
        for r in rows:
            if r.get("error"):
                continue
            print(f"\n[{r['prompt']} · {r['model']} · {r['case']}] "
                  f"score {r['score']} · {r['summary_tokens']} tok")
            print(r["summary"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS,
                        help="gateway model ids; add --local for the bundled 2B")
    parser.add_argument("--prompts", nargs="*", default=list(VARIANTS),
                        help=f"one or more of: {', '.join(VARIANTS)}")
    parser.add_argument("--cases", nargs="*", default=[c["name"] for c in CONVERSATIONS])
    parser.add_argument("--local", action="store_true", help="include the bundled 2B")
    parser.add_argument("--show", action="store_true", help="print every summary")
    parser.add_argument("--out", default=None, help="result file name")
    args = parser.parse_args()

    models = list(args.models)
    if args.local:
        models.append(LOCAL)
    cases = [BY_NAME[n] for n in args.cases]

    rows = []
    total = len(args.prompts) * len(models) * len(cases)
    done = 0
    for prompt_name in args.prompts:
        system = VARIANTS[prompt_name]
        for model in models:
            for conversation in cases:
                done += 1
                print(f"[{done}/{total}] {prompt_name} · {model} · {conversation['name']}",
                      flush=True)
                row = run_one(model, system, conversation)
                row["prompt"] = prompt_name
                rows.append(row)

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = RESULTS / (args.out or f"{stamp}.json")
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False))

    report(rows, args.show)
    spent = sum(r.get("cost", 0) for r in rows)
    print(f"\n{len(rows)} runs, ${spent:.4f} spent, written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

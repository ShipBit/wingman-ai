"""Compare Vercel AI Gateway models as a replacement for the local support model.

Runs the shipped support prompts against gateway models with the same sampling
the production paths use, and scores the output with the same scorers the local
evals use. The numbers are therefore directly comparable to the local baseline
in ``evals/memory_suite/results/results.json``.

    export AI_GATEWAY_API_KEY=...
    python evals/gateway_support_models.py google/gemini-2.5-flash-lite
    python evals/gateway_support_models.py --suite zai/glm-4.7-flash
    python evals/gateway_support_models.py --cost alibaba/qwen3.7-flash

Three modes:
    (default)  eight short labeled cases, two of them German — a quick screen
    --suite    the seven realistic memory-suite scenarios, the real comparison
    --cost     condensation and tool-response compression at realistic sizes

Findings and the resulting recommendation:
``docs/backend-migration/support-model-cloud.md``.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.memory_extraction_cases import CASES  # noqa: E402
from evals.memory_suite.metrics import score_extraction  # noqa: E402
from evals.memory_suite.scenarios import SCENARIOS  # noqa: E402
from evals.run_memory_eval import _score  # noqa: E402
from services.token_utils import count_tokens  # noqa: E402

GATEWAY = "https://ai-gateway.vercel.sh/v1"

EXTRACT_PROMPT = (ROOT / "prompts/extract-memories.md").read_text()
CONDENSE_PROMPT = (ROOT / "prompts/condense-conversation.md").read_text()
TOOL_PROMPT = (ROOT / "prompts/support-tool-response.md").read_text()

# Reasoning off wherever the gateway accepts the parameter. Measured, not read
# off the catalogue: it reports `reasoning_options: null` for qwen3.7-flash, yet
# the model honours "none" and thinks 106 tokens without it.
REASONING_OFF = {
    "google/gemini-2.5-flash-lite": {"reasoning_effort": "none"},
    "openai/gpt-5-nano": {"reasoning_effort": "minimal"},
    "zai/glm-4.7-flash": {"reasoning_effort": "none"},
    "zai/glm-5.3-flash": {"reasoning_effort": "low"},
    "nvidia/nemotron-3.5-lightning": {"reasoning_effort": "none"},
    "openai/gpt-oss-20b": {"reasoning_effort": "low"},
    "alibaba/qwen3.5-flash": {"reasoning_effort": "none"},
    "alibaba/qwen3.7-flash": {"reasoning_effort": "none"},
}

# The German half of the screen. The prompt forbids current locations in any
# language, which is exactly where a model that only learned the English rule
# gives itself away.
CASES_DE = [
    {
        "name": "de_facts_across_turns",
        "conversation": [
            {"role": "user", "content": "Servus, ich bin der Tobias."},
            {"role": "assistant", "content": "Willkommen an Bord, Tobias."},
            {"role": "user", "content": "Ich hab mir endlich eine Drake Cutlass Black gekauft."},
            {"role": "assistant", "content": "Ein solides Schiff."},
            {"role": "user", "content": "Gerade bin ich aber bei New Babbage geparkt."},
            {"role": "assistant", "content": "Verstanden."},
            {"role": "user", "content": "Meine Org heisst Rote Fuechse, da fliege ich meistens mit meinem Kumpel Leo."},
            {"role": "assistant", "content": "Klingt nach einer guten Crew."},
            {"role": "user", "content": "Salvage mag ich total, Bergbau hasse ich. Langfristig spare ich auf eine Reclaimer."},
        ],
        "expect": {
            "min_facts": 5,
            "forbidden_substrings": ["new babbage", "geparkt"],
            "required_any": [["tobias"], ["cutlass"], ["fuechse", "füchse", "foxes"], ["leo"], ["reclaimer"]],
        },
    },
    {
        "name": "de_smalltalk_yields_nothing",
        "conversation": [
            {"role": "user", "content": "hallo, alles klar bei dir?"},
            {"role": "assistant", "content": "Alles bestens, Pilot."},
            {"role": "user", "content": "ich flieg grad von Daymar nach Yela, bin gleich da"},
            {"role": "assistant", "content": "Guten Flug."},
        ],
        "expect": {"should_be_empty": True},
    },
]


def _client():
    from openai import OpenAI

    key = os.environ.get("AI_GATEWAY_API_KEY")
    if not key:
        raise SystemExit("Set AI_GATEWAY_API_KEY.")
    return OpenAI(base_url=GATEWAY, api_key=key, timeout=120.0, max_retries=1)


_prices: dict[str, tuple[float, float]] = {}


def _load_prices(client):
    """Dollars per million in/out, straight from the gateway catalogue."""
    if _prices:
        return
    import httpx

    r = httpx.get(f"{GATEWAY}/models", headers={"Authorization": f"Bearer {client.api_key}"}, timeout=60)
    r.raise_for_status()
    for raw in r.json().get("data", []):
        pricing = raw.get("pricing") or {}
        try:
            _prices[raw["id"]] = (float(pricing["input"]) * 1e6, float(pricing["output"]) * 1e6)
        except (KeyError, TypeError, ValueError):
            continue


def call(client, model, system, user, max_tokens=1024, temperature=0.1, top_p=0.95):
    """One support-model call, with usage, latency and dollar cost."""
    kwargs = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
    )
    kwargs.update(REASONING_OFF.get(model, {}))
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as err:  # a model that rejects the parameter still gets a fair run
        if "reasoning" not in str(err).lower() and "effort" not in str(err).lower():
            return {"error": str(err)[:200], "ms": (time.perf_counter() - started) * 1000}
        kwargs.pop("reasoning_effort", None)
        started = time.perf_counter()
        response = client.chat.completions.create(**kwargs)

    elapsed = (time.perf_counter() - started) * 1000
    usage = response.usage
    try:
        thinking = usage.completion_tokens_details.reasoning_tokens or 0
    except AttributeError:
        thinking = 0
    price_in, price_out = _prices.get(model, (0.0, 0.0))
    return {
        "text": response.choices[0].message.content or "",
        "ms": elapsed,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "reasoning_tokens": thinking,
        "cost": (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) / 1e6,
    }


def parse_json_response(text):
    """The same repair ladder ``PersistentMemoryService`` applies."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(re.sub(r'"\s*\n\s*"', '", "', raw))
    except json.JSONDecodeError:
        return None


def conversation_text(messages):
    return "\n".join(
        f"{m['role']}: {m['content']}"
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    )


def screen(client, model):
    """Eight short labeled cases — a cheap first cut."""
    passed, times = 0, []
    total_cost = 0.0
    for case in CASES + CASES_DE:
        result = call(client, model, EXTRACT_PROMPT, conversation_text(case["conversation"]))
        if "error" in result:
            print(f"   {case['name']:30} ERROR {result['error'][:80]}")
            continue
        times.append(result["ms"])
        total_cost += result["cost"]
        data = parse_json_response(result["text"])
        facts = [f for f in (data or {}).get("facts", []) if isinstance(f, str)]
        ok, reasons = _score(case, facts, (data or {}).get("summary", "") or "")
        ok = ok and data is not None
        passed += bool(ok)
        if not ok:
            print(f"   {case['name']:30} FAIL {'; '.join(reasons)[:100]}")
    print(f"   {passed}/{len(CASES) + len(CASES_DE)} passed, median {statistics.median(times):.0f} ms, "
          f"{total_cost * 1000:.3f} m$ total")


def suite(client, model, samples=2):
    """The seven realistic scenarios, scored like the local memory suite."""
    scores, recalls, precisions, times, costs = [], [], [], [], []
    for scenario in SCENARIOS:
        text = conversation_text(scenario.messages)
        runs = []
        for _ in range(samples):
            result = call(client, model, EXTRACT_PROMPT, text, max_tokens=1500)
            if "error" in result:
                print(f"   {scenario.id:22} ERROR {result['error'][:80]}")
                break
            times.append(result["ms"])
            costs.append(result["cost"])
            data = parse_json_response(result["text"])
            facts = [f for f in (data or {}).get("facts", []) if isinstance(f, str)]
            runs.append(score_extraction(facts, scenario, text))
        if not runs:
            continue
        s = statistics.mean(r["score"] for r in runs)
        rec = statistics.mean(r["recall"] for r in runs)
        prec = statistics.mean(r["precision"] for r in runs)
        scores.append(s)
        recalls.append(rec)
        precisions.append(prec)
        print(f"   {scenario.id:22} score {s:.3f}  recall {rec:.3f}  precision {prec:.3f}")
    if scores:
        print(f"   MEAN score {statistics.mean(scores):.3f}  recall {statistics.mean(recalls):.3f}  "
              f"precision {statistics.mean(precisions):.3f}  median {statistics.median(times):.0f} ms  "
              f"{statistics.mean(costs) * 1000:.4f} m$/call")


def cost(client, model):
    """The two tasks that actually move the bill, at realistic sizes."""
    marathon = next(s for s in SCENARIOS if s.id == "sc_va_marathon")
    conversation = conversation_text(marathon.messages)

    # A trade table shaped like what the uexcorp skill returns.
    rows = [
        {
            "commodity": f"Commodity {i}", "buy_price": 12.5 + i, "sell_price": 30.1 + i,
            "terminal": f"Terminal {i % 37}", "system": "Stanton", "scu_available": 100 + i,
            "status": "ok" if i % 5 else "out_of_stock", "updated": "2026-09-11T12:00:00Z",
        }
        for i in range(900)
    ]
    payload = json.dumps({"routes": rows}, indent=1)

    print(f"   condense input {count_tokens(conversation)} tokens, tool input {count_tokens(payload)} tokens")
    jobs = [
        ("condense", CONDENSE_PROMPT,
         "CONVERSATION TO SUMMARIZE:\n" + conversation +
         "\n\n---\nNow list every fact from the conversation above as bullet points.", 1.0),
        ("tool", TOOL_PROMPT,
         "DATA TO SUMMARIZE:\n" + payload +
         "\n\n---\nSummarize the above data. Preserve all key facts, numbers, names, IDs, and status values:", 0.1),
    ]
    for label, system, user, temperature in jobs:
        result = call(client, model, system, user, max_tokens=2000, temperature=temperature)
        if "error" in result:
            print(f"   {label:10} ERROR {result['error'][:100]}")
            continue
        print(f"   {label:10} in={result['prompt_tokens']:6} out={result['completion_tokens']:5} "
              f"think={result['reasoning_tokens']:5} {result['ms']:7.0f} ms  {result['cost'] * 1000:.4f} m$")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 1

    client = _client()
    _load_prices(client)

    for model in args:
        print(f"--- {model}", flush=True)
        if "--suite" in flags:
            suite(client, model)
        elif "--cost" in flags:
            cost(client, model)
        else:
            screen(client, model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

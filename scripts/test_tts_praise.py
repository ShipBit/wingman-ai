#!/usr/bin/env python3
"""Test prompts via the Local AI Lab playground endpoint.

Usage:
    python scripts/test_tts_praise.py [--prompt tts-test-praise] [--iterations 3] [--host http://localhost:49111]
    python scripts/test_tts_praise.py --prompt condense-conversation --preset Balanced --iterations 5

Fetches presets, prompts, and example messages from Core (single source of truth).
By default tests only the production preset for known prompts, or all presets for unknown ones.
Use --all to test all presets, or --preset to test a specific one.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request


def fetch_json(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def load_presets(host: str) -> dict[str, dict]:
    """Fetch sampling presets from Core and return as {name: {temp, top_p, ...}}."""
    raw = fetch_json(f"{host}/settings/local-ai/playground/presets")
    return {
        p["name"]: {
            "temperature": p["temperature"],
            "top_p": p["top_p"],
            "top_k": p["top_k"],
            "presence_penalty": p["presence_penalty"],
        }
        for p in raw
    }


def load_prompts(host: str) -> dict[str, dict]:
    """Fetch prompt configs from Core and return as {name: {content, production_preset, example_message}}."""
    raw = fetch_json(f"{host}/settings/local-ai/playground/prompts")
    return {p["name"]: p for p in raw}


def call_playground(host: str, system_prompt: str, user_message: str,
                    iterations: int, temperature: float, top_p: float,
                    top_k: int = 20, presence_penalty: float = 2.0):
    payload = {
        "system_message": system_prompt,
        "user_message": user_message,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "presence_penalty": presence_penalty,
        "iterations": iterations,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/settings/local-ai/playground/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def analyze_preset(responses: list[dict]) -> dict:
    """Compute stats for a set of responses."""
    texts = [r["text"].strip() for r in responses]
    word_counts = [len(t.split()) for t in texts]
    token_counts = [r["completion_tokens"] for r in responses]
    times = [r["time_ms"] for r in responses]

    return {
        "texts": texts,
        "word_counts": word_counts,
        "avg_words": statistics.mean(word_counts),
        "avg_tokens": statistics.mean(token_counts),
        "avg_ms": statistics.mean(times),
        "word_stddev": statistics.stdev(word_counts) if len(word_counts) > 1 else 0,
        "unique_ratio": len(set(texts)) / len(texts) if texts else 0,
    }


def print_results(name: str, params: dict, stats: dict, is_production: bool = False):
    prod_tag = "  ← PRODUCTION" if is_production else ""
    print(f"\n{'─' * 90}")
    print(f"  {name}  (temp={params['temperature']}, top_p={params['top_p']}, "
          f"top_k={params['top_k']}, presence_penalty={params['presence_penalty']}){prod_tag}")
    print(f"{'─' * 90}")

    for i, text in enumerate(stats["texts"], 1):
        wc = stats["word_counts"][i - 1]
        print(f"  {i:2d}. [{wc:2d}w] {text}")

    print(f"\n  Stats: avg {stats['avg_words']:.1f} words (+-{stats['word_stddev']:.1f}), "
          f"{stats['avg_tokens']:.0f} tokens, {stats['avg_ms']:.0f}ms/response, "
          f"{stats['unique_ratio']:.0%} unique")


def print_analysis(all_results: dict):
    print(f"\n{'=' * 90}")
    print("  ANALYSIS")
    print(f"{'=' * 90}")

    print(f"\n  {'Preset':<14} {'Avg Words':>10} {'StdDev':>8} {'Avg Tokens':>11} {'Avg ms':>8} {'Unique':>8}")
    print(f"  {'─' * 14} {'─' * 10} {'─' * 8} {'─' * 11} {'─' * 8} {'─' * 8}")

    for name, stats in all_results.items():
        print(f"  {name:<14} {stats['avg_words']:>10.1f} {stats['word_stddev']:>8.1f} "
              f"{stats['avg_tokens']:>11.0f} {stats['avg_ms']:>8.0f} {stats['unique_ratio']:>7.0%}")

    best = min(all_results.items(),
               key=lambda x: abs(x[1]["avg_words"] - 15) + (1 - x[1]["unique_ratio"]) * 20)
    print(f"\n  Recommendation: '{best[0]}' -- best balance of length (~15w target) and variety")


def main():
    parser = argparse.ArgumentParser(description="Test prompts via Local AI Lab playground")
    parser.add_argument("--prompt", default="tts-test-praise",
                        help="Prompt name from prompts/ dir (default: tts-test-praise)")
    parser.add_argument("--preset", default=None,
                        help="Run only this preset (default: production preset if known, else all)")
    parser.add_argument("--all", action="store_true", dest="all_presets",
                        help="Test all presets even when a production mapping exists")
    parser.add_argument("--user-message", default=None,
                        help="Override user message (default: example from Core)")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Iterations per preset (default: 3)")
    parser.add_argument("--host", default="http://localhost:49111",
                        help="Core API base URL")
    args = parser.parse_args()

    # Fetch everything from Core (single source of truth)
    try:
        presets = load_presets(args.host)
        prompts = load_prompts(args.host)
    except Exception as e:
        print(f"ERROR: Could not connect to Core at {args.host}: {e}")
        sys.exit(1)

    prompt_config = prompts.get(args.prompt)
    if not prompt_config:
        print(f"ERROR: prompt '{args.prompt}' not found. Available prompts:")
        for name in sorted(prompts):
            prod = prompts[name].get("production_preset") or "-"
            print(f"  - {name}  (preset: {prod})")
        return

    system_prompt = prompt_config["content"]
    production_preset = prompt_config.get("production_preset")
    user_message = args.user_message or prompt_config.get("example_message") or "Generate a response."
    preset_names = list(presets.keys())

    # Validate --preset against what Core knows
    if args.preset and args.preset not in presets:
        print(f"ERROR: preset '{args.preset}' not found. Available: {', '.join(preset_names)}")
        return

    # Determine which presets to test
    if args.preset:
        presets_to_test = [args.preset]
    elif args.all_presets:
        presets_to_test = preset_names
    elif production_preset:
        presets_to_test = [production_preset]
    else:
        presets_to_test = preset_names

    print(f"Prompt: {args.prompt}")
    if production_preset:
        print(f"Production preset: {production_preset}")
    print(f"Testing: {', '.join(presets_to_test)}")
    print(f"System: {system_prompt.strip()[:120]}...")
    print(f"User:   {user_message[:120]}{'...' if len(user_message) > 120 else ''}")
    print(f"Iterations per preset: {args.iterations}")
    print(f"{'=' * 90}")

    all_results = {}

    for preset_name in presets_to_test:
        params = presets[preset_name]
        try:
            result = call_playground(
                args.host, system_prompt, user_message, args.iterations,
                params["temperature"], params["top_p"], params["top_k"], params["presence_penalty"],
            )
        except Exception as e:
            print(f"\n  {preset_name}: ERROR -- {e}")
            continue

        if not result.get("success"):
            print(f"\n  {preset_name}: FAILED -- {result.get('error', 'unknown')}")
            continue

        stats = analyze_preset(result["responses"])
        all_results[preset_name] = stats
        is_prod = (preset_name == production_preset)
        print_results(preset_name, params, stats, is_production=is_prod)

    if len(all_results) > 1:
        print_analysis(all_results)

    print(f"\n{'=' * 90}")
    print("Done.")


if __name__ == "__main__":
    main()

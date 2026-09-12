"""Live evaluation of local-model memory extraction.

Runs the labeled cases in ``memory_extraction_cases.py`` through the REAL
extraction path (the ``extract-memories`` prompt + your configured local model +
the actual parsing/dedup code) and scores the stored facts against each case's
expectations. This is the feedback loop for tuning the tiny model: change a
prompt or a sampling/reasoning setting, re-run, watch the score move.

It uses your real Wingman settings (model, n_ctx, run_locally) but writes to a
throwaway temp database, so your actual persistent memory is never touched.

Usage:
    # Close the Wingman desktop app first (it holds the local-model ports).
    python evals/run_memory_eval.py            # all cases
    python evals/run_memory_eval.py ship org   # only cases whose name matches

Requires local AI enabled (run_locally) with the support + embed models
downloaded.
"""

import os
import shutil
import sys
import tempfile
import time
from os import path

# Make the repo root importable when run as a script.
REPO_ROOT = path.dirname(path.dirname(path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Keep eval runs out of the real debug log.
os.environ.setdefault("WINGMAN_MEMORY_DEBUG_LOG", "0")

from evals.memory_extraction_cases import CASES  # noqa: E402


def _score(case: dict, facts: list[str], summary: str) -> tuple[bool, list[str]]:
    """Score one extraction result. Returns (passed, list_of_failure_reasons)."""
    expect = case.get("expect", {})
    reasons: list[str] = []
    lowered = [f.lower() for f in facts]

    if expect.get("should_be_empty"):
        if facts:
            reasons.append(f"expected no facts, got {len(facts)}")

    if "min_facts" in expect and len(facts) < expect["min_facts"]:
        reasons.append(f"expected >= {expect['min_facts']} facts, got {len(facts)}")
    if "max_facts" in expect and len(facts) > expect["max_facts"]:
        reasons.append(f"expected <= {expect['max_facts']} facts, got {len(facts)}")

    for bad in expect.get("forbidden_substrings", []):
        hits = [f for f, lo in zip(facts, lowered) if bad.lower() in lo]
        if hits:
            reasons.append(f"forbidden '{bad}' in: {hits}")

    for concept in expect.get("required_any", []):
        if not any(any(s.lower() in lo for s in concept) for lo in lowered):
            reasons.append(f"missing required concept (any of {concept})")

    sl = summary.lower()
    for bad in expect.get("summary_forbidden", []):
        if bad.lower() in sl:
            reasons.append(f"forbidden '{bad}' in summary")
    for req in expect.get("summary_required", []):
        if req.lower() not in sl:
            reasons.append(f"summary missing '{req}'")

    return (len(reasons) == 0, reasons)


def _measure_reasoning(local_ai, cases) -> None:
    """Diagnostic: run each case with reasoning ON and report think/answer token
    usage + truncation.

    This is why memory extraction ships with reasoning OFF: the bundled 2B model
    rambles thousands of <think> tokens and truncates before emitting the answer.
    If most cases show a large think block with answer=0/truncated, reasoning is
    over-thinking on this model — keep it off (more output budget won't help; the
    model just thinks more). REASONING_OUTPUT_TOKENS only matters when a *capable*
    model uses reasoning via the playground or a skill opt-in.
    """
    from services.file import get_prompt
    from services.skill_local_ai import SamplingPreset
    from services.token_utils import count_tokens

    system_prompt = get_prompt("extract-memories")
    print(f"\n{'=' * 40}")
    print("Reasoning diagnostic (extract-memories, reasoning=True — NOT the default)")
    print(f"{'case':30}{'think':>7}{'answer':>7}  truncated")
    failed = 0
    for case in cases:
        text = "\n".join(
            f"{m['role']}: {m['content']}"
            for m in case["conversation"]
            if m.get("role") in ("user", "assistant")
        )
        res = local_ai.support(
            text=text, system_prompt=system_prompt,
            preset=SamplingPreset.PRECISE, reasoning=True,
        )
        think = count_tokens(res.reasoning_content) if res and res.reasoning_content else 0
        answer = count_tokens(res.text) if res and res.text else 0
        truncated = bool(res and res.truncated)
        if truncated and answer == 0:
            failed += 1
        print(f"{case['name'][:30]:30}{think:>7}{answer:>7}  {'YES' if truncated else ''}")

    print(
        f"\n{failed}/{len(cases)} cases produced NO answer (thought past the output "
        f"limit). Extraction therefore runs with reasoning=False (the default)."
        if failed
        else "\nReasoning produced answers on all cases — safe to consider here."
    )


def _build_local_ai():
    """Bootstrap the real local-AI stack from the user's saved settings."""
    from providers.llama_cpp_provider import LlamaCppProvider
    from providers.llama_cpp_remote import LlamaCppRemote
    from services.config_manager import ConfigManager
    from services.config_service import ConfigService
    from services.local_ai_service import LocalAiService
    from services.local_model_manager import LocalModelManager
    from services.settings_service import SettingsService

    from api.enums import LocalAiMode
    from providers.wingman_support import WingmanSupport

    config_manager = ConfigManager(REPO_ROOT)
    config_service = ConfigService(config_manager=config_manager)
    settings_service = SettingsService(
        config_manager=config_manager, config_service=config_service
    )
    settings = settings_service.settings.llama_cpp
    # This harness measures the model on this machine, whatever the user's
    # config says. Cloud would answer with a different model entirely and the
    # numbers would not be comparable to the ones in FINDINGS.md.
    settings.mode = LocalAiMode.LOCAL

    model_manager = LocalModelManager(settings=settings)
    provider = LlamaCppProvider(settings=settings, model_manager=model_manager)
    remote = LlamaCppRemote(settings=settings)
    cloud = WingmanSupport(
        subscription=settings_service.settings.wingman_pro, settings=settings
    )
    local_ai = LocalAiService(
        provider=provider, remote=remote, cloud=cloud, settings=settings
    )
    return local_ai, provider, settings


def main() -> int:
    filters = [a.lower() for a in sys.argv[1:]]
    cases = [
        c for c in CASES
        if not filters or any(f in c["name"].lower() for f in filters)
    ]
    if not cases:
        print("No cases matched the given filters.")
        return 1

    local_ai, provider, settings = _build_local_ai()

    print(
        f"Local AI: mode={settings.mode.value}, n_ctx={settings.n_ctx} "
        "(extraction runs reasoning=OFF; see the reasoning diagnostic below)"
    )
    if settings.mode.value == "local":
        print("Loading support + embed models (close the desktop app if this hangs)...")
        if not provider.load_support_model() or not provider.load_embed_model():
            print("ERROR: could not load local models. Are they downloaded and the "
                  "ports free (desktop app closed)?")
            return 1
    elif not local_ai.is_ready():
        print("ERROR: remote local-AI is not reachable.")
        return 1

    # Isolate storage: point the persistent-memory dir at a throwaway folder.
    import services.persistent_memory as pm_mod
    from services.persistent_memory import PersistentMemoryService

    tmpdir = tempfile.mkdtemp(prefix="wingman_mem_eval_")
    pm_mod.get_persistent_memory_dir = lambda: tmpdir

    svc = PersistentMemoryService(wingman_name="__eval__", local_ai_service=local_ai)
    svc.initialize()

    passed = 0
    try:
        for case in cases:
            svc.clear_collection()
            t0 = time.time()
            svc.extract_memories_sync(case["conversation"], generate_summary=True)
            elapsed = time.time() - t0

            facts = [e.content for e in svc.get_all(entry_type="fact")]
            summaries = svc.get_all(entry_type="session_summary")
            summary = summaries[0].content if summaries else ""

            ok, reasons = _score(case, facts, summary)
            passed += ok
            mark = "PASS" if ok else "FAIL"
            print(f"\n[{mark}] {case['name']}  ({elapsed:.1f}s)")
            for f in facts:
                print(f"    fact:    {f}")
            if summary:
                print(f"    summary: {summary}")
            for r in reasons:
                print(f"    >> {r}")

        _measure_reasoning(local_ai, cases)
    finally:
        svc.close()
        if settings.mode.value == "local":
            try:
                provider.unload_models()
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    total = len(cases)
    print(f"\n{'=' * 40}\n{passed}/{total} cases passed.")
    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for the Persistent Memory test suite.

Close the Wingman desktop app first (it holds the local-model ports).

  # Baseline: every scenario under the shipping defaults -> HTML report
  python -m evals.memory_suite.run

  # Compare several named profiles (different 'Wingmen')
  python -m evals.memory_suite.run --profiles default,bigctx,temp0

  # Find a better value along one axis (writes a sweep comparison table)
  python -m evals.memory_suite.run --sweep temp
  python -m evals.memory_suite.run --sweep n_ctx
  python -m evals.memory_suite.run --sweep min_similarity

  # One scenario, more samples (stochastic stability)
  python -m evals.memory_suite.run --scenario sc_long --samples 5

  # Only one category (star_citizen | other_game | assistant)
  python -m evals.memory_suite.run --category star_citizen

Output lands in evals/memory_suite/results/ (report.html + results.json).
"""

import argparse
import sys
from os import makedirs, path

REPO_ROOT = path.dirname(path.dirname(path.dirname(path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import os  # noqa: E402

os.environ.setdefault("WINGMAN_MEMORY_DEBUG_LOG", "0")

from evals.memory_suite import profiles as prof_mod  # noqa: E402
from evals.memory_suite import report  # noqa: E402
from evals.memory_suite.harness import ModelHost, run_suite  # noqa: E402
from evals.memory_suite.scenarios import get_scenarios  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Persistent Memory test suite")
    ap.add_argument("--profiles", help="comma-separated named profiles "
                    f"({', '.join(prof_mod.NAMED_PROFILES)})")
    ap.add_argument("--sweep", help="sweep one axis: temp | n_ctx | min_similarity")
    ap.add_argument("--scenario", help="only scenarios whose id matches (comma-separated)")
    ap.add_argument("--category", help="star_citizen | other_game | assistant")
    ap.add_argument("--samples", type=int, default=1,
                    help="extraction samples per scenario (stochastic averaging)")
    ap.add_argument("--attach", action="store_true",
                    help="run against an already-running llama-server (the live "
                         "desktop app) instead of spawning our own. Skips n_ctx/"
                         "model-swap profiles but needs no app shutdown.")
    ap.add_argument("--support-port", type=int, default=49172)
    ap.add_argument("--embed-port", type=int, default=49173)
    ap.add_argument("--outdir", default=path.join(path.dirname(__file__), "results"))
    args = ap.parse_args()

    ids = args.scenario.split(",") if args.scenario else None
    cats = [args.category] if args.category else None
    scenarios = get_scenarios(ids=ids, categories=cats)
    if not scenarios:
        print("No scenarios matched.")
        return 1

    if args.sweep:
        profile_list = prof_mod.sweep_profiles(args.sweep)
    elif args.profiles:
        profile_list = prof_mod.resolve_profiles(args.profiles.split(","))
    else:
        profile_list = [prof_mod.DEFAULT]

    host = ModelHost(attach=args.attach,
                     support_port=args.support_port, embed_port=args.embed_port)
    mode = "attach (live server)" if args.attach else "managed (spawns servers)"
    print(f"Local AI [{mode}]: support={host.settings.mode.value}, "
          f"n_ctx={host.settings.n_ctx}, model={host.settings.support_model}")
    if not host.ensure_loaded():
        print("ERROR: could not load local models (close the desktop app / check downloads).")
        return 1

    runs = []
    try:
        for profile in profile_list:
            print(f"\n▶ profile '{profile.id}': {profile.description}")
            run = run_suite(host, scenarios, profile, samples=args.samples)
            runs.append(run)
            sm = run["summary"]
            print(f"   extraction {sm['extraction_score']}  "
                  f"recall@probe {sm['recall_probes']}  forget {sm['forget_probes']}")
    finally:
        host.shutdown()

    makedirs(args.outdir, exist_ok=True)
    html_path, json_path = report.write_reports(
        runs, args.outdir, sweep_axis=args.sweep)
    report.print_summary(runs)
    print(f"\nReport: {html_path}\nJSON:   {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

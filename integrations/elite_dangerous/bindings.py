"""Legacy command export; use control_setup for verified runtime controls."""
from skills.elite_dangerous_controls.bindings import *  # Backward-compatible API.

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", required=True, type=Path)
    parser.add_argument("--presets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-key", default="end")
    args = parser.parse_args()
    stage(generate(args.bindings, args.presets, args.record_key), args.output)

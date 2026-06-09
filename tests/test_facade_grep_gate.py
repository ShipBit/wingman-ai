"""Fails if any forbidden side-door survives in skills/**. Run:
    PYTHONPATH=. venv/bin/python -m tests.test_facade_grep_gate

This is the lockdown gate: after the v3 migration, no bundled skill may reach the
runtime through a removed/raw path. skill_base.py is exempt (it defines the facade
plumbing and the FacadeError messages that name the old members).
"""
import os
import re
import sys

FORBIDDEN = [
    r"actual_llm_call",
    r"self\.wingman\.llm_call",
    r"self\.local_ai\b",
    r"self\.retrieve_secret\(",
    r"self\.threaded_execution\(",
    r"self\.wingman\.tool_skills",
    r"self\.wingman\.mcp_registry",
    r"self\.wingman\.skill_registry",
    r"self\.wingman\.registry\b",
    r"self\.wingman\.tower\b",
    r"self\.wingman\.secret_keeper",
    r"self\.wingman\.messages\b",
    r"self\.wingman\.get_command\(",
    r"self\.wingman\.get_context\(",
    r"self\.wingman\.get_conversation_history\(",
    r"self\.wingman\.play_to_user\(",
    r"self\.wingman\.generate_image\(",
    r"self\.wingman\.add_user_message\(",
    r"self\.wingman\.add_assistant_message\(",
    r"self\.wingman\.reset_conversation_history\(",
    r"self\.wingman\.audio_player\b",
    r"self\.wingman\.audio_library\b",
    r"self\.wingman\.local_ai_service",
    r"self\.wingman\.persistent_memory_service",
    r"_tool_to_server",
    r"_manifests\b",
    r"switch_tts_provider",
]
PATS = [re.compile(p) for p in FORBIDDEN]


def test_no_side_doors():
    hits = []
    for root, dirs, files in os.walk("skills"):
        if "venv" in root or "/dependencies" in root or "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            # skip skill_base.py (defines the FacadeError messages mentioning old names)
            if path.endswith("skill_base.py"):
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    for pat in PATS:
                        if pat.search(line):
                            hits.append(f"{path}:{i}: {line.strip()}")
    if hits:
        print("FORBIDDEN side-doors found:")
        print("\n".join(hits))
        sys.exit(1)
    print("PASS: no forbidden side-doors in skills/**")


if __name__ == "__main__":
    test_no_side_doors()
    print("ALL OK")

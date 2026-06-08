"""Run: PYTHONPATH=. venv/bin/python -m tests.test_wingman_context_closed"""
from wingmen.wingman_context import WingmanContext


class _W:
    name = "W"
    config = type("C", (), {})()
    settings = type("S", (), {"audio": None})()


def test_closed_surface():
    ctx = WingmanContext(_W())
    # sub-facades present
    for ns in ("ai", "local_ai", "tts", "audio", "commands", "tools",
               "conversation", "memory", "secrets", "skills"):
        assert hasattr(ctx, ns), f"missing {ns}"
    # leaks removed
    for leak in ("llm_call", "audio_player", "tool_skills", "mcp_registry",
                 "skill_registry", "tower", "secret_keeper", "messages",
                 "get_command", "get_context", "local_ai_service",
                 "persistent_memory_service"):
        assert not hasattr(ctx, leak), f"LEAK still present: {leak}"
    # raw wingman not reachable via _wingman (name-mangled)
    assert not hasattr(ctx, "_wingman"), "raw _wingman must be name-mangled"
    print("PASS: closed surface — sub-facades present, leaks gone, _wingman mangled")


if __name__ == "__main__":
    test_closed_surface()
    print("ALL OK")

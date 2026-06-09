"""Run: PYTHONPATH=. venv/bin/python -m tests.test_wingman_context_closed"""
from wingmen.wingman_context import WingmanContext
from wingmen.facade import FacadeError


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
    # removed v2 leaks raise a helpful FacadeError (spec §8), naming the replacement
    for leak in ("llm_call", "audio_player", "tool_skills", "mcp_registry",
                 "skill_registry", "tower", "secret_keeper", "messages",
                 "get_command", "get_context", "local_ai_service",
                 "persistent_memory_service", "registry", "play_to_user",
                 "generate_image", "add_assistant_message", "retrieve_secret",
                 "threaded_execution"):
        try:
            getattr(ctx, leak)
            raise AssertionError(f"LEAK still present: {leak}")
        except FacadeError as e:
            assert "MIGRATING-TO-V3" in str(e), f"{leak}: error must point to the guide"
    # an unknown attribute still raises a plain AttributeError (not FacadeError)
    try:
        getattr(ctx, "totally_unknown_attr")
        raise AssertionError("unknown attr should raise AttributeError")
    except AttributeError:
        pass
    # raw wingman not reachable via _wingman (name-mangled, not in the removed map)
    assert not hasattr(ctx, "_wingman"), "raw _wingman must be name-mangled"
    print("PASS: closed surface — sub-facades present, removed leaks raise FacadeError, _wingman mangled")


if __name__ == "__main__":
    test_closed_surface()
    print("ALL OK")

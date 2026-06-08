"""Run: PYTHONPATH=. venv/bin/python -m tests.test_skill_base_surface"""
import inspect
from skills.skill_base import Skill


def test_removed_members():
    for gone in ("local_ai", "retrieve_secret", "threaded_execution", "llm_call"):
        assert not hasattr(Skill, gone), f"{gone} must be removed from Skill"
    print("PASS: duplicates removed from Skill")


def test_kept_members():
    for keep in ("retrieve_custom_property_value", "get_generated_files_dir", "update_config"):
        assert hasattr(Skill, keep), f"{keep} must stay on Skill"
    print("PASS: skill-owned members kept")


def test_log_present():
    src = inspect.getsource(Skill.__init__)
    assert "self.log" in src, "self.log wrapper must be set in __init__"
    print("PASS: self.log present")


if __name__ == "__main__":
    test_removed_members()
    test_kept_members()
    test_log_present()
    print("ALL OK")

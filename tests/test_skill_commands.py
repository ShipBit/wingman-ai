"""Run: PYTHONPATH=. venv/bin/python -m tests.test_skill_commands"""
import asyncio
from wingmen.facade import SkillCommands, CommandCategory


class _Cmd:
    def __init__(self, name): self.name = name; self.category_id = None


class _Cat:
    def __init__(self, id, name): self.id = id; self.name = name


class _Features: pass


class _Config:
    def __init__(self):
        self.commands = []
        self.command_categories = []


class _Exec:
    def __init__(self, cfg): self.cfg = cfg
    def get_command(self, name):
        return next((c for c in self.cfg.commands if c.name == name), None)


class _Tower:
    def save_wingman_commands(self, name): return True


class _W:
    name = "TestWingman"
    def __init__(self):
        self.config = _Config()
        self.command_executor = _Exec(self.config)
        self.tower = _Tower()


def test_add_remove():
    w = _W(); c = SkillCommands(w)
    c.add(_Cmd("Jump"))
    assert len(c.all()) == 1 and c.get("Jump") is not None
    c.remove("Jump")
    assert c.get("Jump") is None
    print("PASS: add/remove/get/all")


def test_categories():
    w = _W(); c = SkillCommands(w)
    cat = c.add_category("Combat")
    assert isinstance(cat, CommandCategory) and len(w.config.command_categories) == 1
    cat2 = c.add_category("Combat")  # idempotent by name
    assert cat2.id == cat.id and len(w.config.command_categories) == 1
    cmd = _Cmd("Jump")
    c.add(cmd, category=cat)
    assert cmd.category_id == cat.id
    print("PASS: categories idempotent + add(category=)")


if __name__ == "__main__":
    test_add_remove()
    test_categories()
    print("ALL OK")

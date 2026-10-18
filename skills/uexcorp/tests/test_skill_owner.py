"""Which Wingman owns the skill: the one that activates it, not the first one created.

No pytest. Run from the project root:

    python3 -m skills.uexcorp.tests.test_skill_owner

Exits non-zero on the first failed assertion or crash; prints "ALL OK" on success.

Why this exists
---------------
Data, trade run and HUD panel are shared by every Wingman with the skill, so only one may use it.
Every Wingman with the skill in its config gets a skill object at start, in parallel. The owner
used to be whichever was created first, even one that never activated UEX: another Wingman was
then told "already initialized with <a Wingman that is gone>" until Core restarted.
"""

from __future__ import annotations

import asyncio
import unittest
from os import path
from types import SimpleNamespace

import yaml

import skills.uexcorp.main as skill_module
from api.interface import SkillConfig


class _FakeHelper:
    """The parts of Helper the skill class uses, without a database in the user's folders."""

    _instance = None
    destroyed = 0
    settings_read_by: list[str] = []  # whose skill settings were read, in order

    @classmethod
    def get_instance(cls) -> "_FakeHelper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def destroy_instance(cls) -> None:
        cls.destroyed += 1
        cls._instance = None

    def __init__(self):
        self.prepared_by = None
        self.owner = None
        self.wingman = None
        self.debug = SimpleNamespace(write=lambda *a, **k: None)
        self.import_handler = SimpleNamespace(
            is_running=lambda: False, request_completion=lambda: None, prepare=lambda preload=False: None
        )

    def is_prepared(self) -> bool:
        return self.prepared_by is not None

    def prepare(self, run_in_thread, wingman) -> None:
        self.prepared_by = wingman.name
        self.wingman = wingman

    def get_owner(self):
        return self.owner

    def claim(self, wingman) -> None:
        self.owner, self.wingman = wingman.name, wingman

    def get_wingmen(self):
        return self.wingman

    def get_handler_debug(self):
        return self.debug

    def get_handler_import(self):
        return self.import_handler

    def get_handler_config(self):
        async def validate(errors, retrieve):
            _FakeHelper.settings_read_by.append(retrieve.__self__.wingman.name)
            return errors
        return SimpleNamespace(validate=validate)

    def get_handler_tool(self):
        async def execute_tool(name, parameters):
            return f"{name} ran", ""
        return SimpleNamespace(execute_tool=execute_tool, get_tools=lambda: [])

    def set_loaded(self, loaded: bool = True) -> None:
        pass


class _Benchmark:
    def start_snapshot(self, *args):
        pass

    def finish_snapshot(self):
        pass


def _wingman(name: str) -> SimpleNamespace:
    async def remove_info(title):
        return True

    return SimpleNamespace(
        name=name, run_in_thread=lambda *a, **k: None, hud=SimpleNamespace(remove_info=remove_info),
    )


class SkillOwnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original = skill_module.Helper
        skill_module.Helper = _FakeHelper
        _FakeHelper._instance = None
        _FakeHelper.destroyed = 0
        _FakeHelper.settings_read_by = []
        # The skill's own trade run HUD refresh needs the real store: not part of this test
        self._start = skill_module.UEXCorp._UEXCorp__start

        async def start(skill):
            pass

        skill_module.UEXCorp._UEXCorp__start = start
        with open(path.join(path.dirname(skill_module.__file__), "default_config.yaml"), encoding="utf-8") as file:
            self._config = yaml.safe_load(file)

    def tearDown(self) -> None:
        skill_module.Helper = self._original
        skill_module.UEXCorp._UEXCorp__start = self._start

    def _skill(self, name: str) -> skill_module.UEXCorp:
        return skill_module.UEXCorp(SkillConfig(**self._config), SimpleNamespace(), _wingman(name))

    def _activate(self, skill) -> None:
        asyncio.run(skill.validate())
        asyncio.run(skill.prepare())

    def _call(self, skill) -> str:
        return asyncio.run(skill.execute_tool("uex_get_trade_routes", {}, _Benchmark()))[0]

    def test_the_wingman_that_activates_it_owns_it_not_the_first_one_created(self) -> None:
        first, second = self._skill("Orionis"), self._skill("Computer")
        self.assertEqual(_FakeHelper.get_instance().prepared_by, "Orionis")  # the download starts early
        self._activate(second)
        self._activate(first)
        self.assertEqual(_FakeHelper.get_instance().get_owner(), "Computer")
        self.assertEqual(self._call(second), "uex_get_trade_routes ran")
        self.assertIn("already initialized with 'Computer'", self._call(first))

    def test_only_the_owner_ends_the_shared_helper(self) -> None:
        owner, other = self._skill("Computer"), self._skill("Orionis")
        self._activate(owner)
        self._activate(other)
        asyncio.run(other.unload())
        self.assertEqual(_FakeHelper.destroyed, 0)
        asyncio.run(owner.unload())
        self.assertEqual(_FakeHelper.destroyed, 1)

    def test_another_wingman_takes_over_once_the_owner_is_gone(self) -> None:
        owner, other = self._skill("Computer"), self._skill("Orionis")
        self._activate(owner)
        self._activate(other)
        asyncio.run(owner.unload())  # e.g. the Wingman was switched off
        self.assertEqual(self._call(other), "uex_get_trade_routes ran")
        self.assertEqual(_FakeHelper.get_instance().get_owner(), "Orionis")
        # The new owner's own settings, not the defaults
        self.assertEqual(_FakeHelper.settings_read_by, ["Computer", "Orionis"])

    def test_a_reloaded_wingman_keeps_the_helper_its_new_skill_claimed(self) -> None:
        old = self._skill("Orionis")
        self._activate(old)
        new = self._skill("Orionis")  # config saved: a new skill object, the old one unloads after
        self._activate(new)
        asyncio.run(old.unload())
        self.assertEqual(_FakeHelper.destroyed, 0)
        self.assertEqual(self._call(new), "uex_get_trade_routes ran")


def main() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SkillOwnerTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()

"""What a skill does with a HUD group of its own and with the shared info
panel through `self.wingman.hud`. A real HUD service and manager; nothing is
drawn."""

import asyncio
from types import SimpleNamespace

import pytest

from hud_server.constants import GROUP_INFO
from hud_server.hud_manager import HudManager
from services.hud_service import PERSISTENT, HudService
from wingmen import facade


@pytest.fixture
def hud():
    HudService._instance = None
    service = HudService()
    manager = HudManager()
    service._server = SimpleNamespace(is_running=True, manager=manager)
    wingman = SimpleNamespace(
        name="Bob", config=SimpleNamespace(hud=SimpleNamespace(chat=True, info=True)),
        get_avatar_path=lambda: None,
    )
    yield SimpleNamespace(skill=facade.SkillHud(wingman, "Mining"), manager=manager)
    HudService._instance = None


def _run(coroutine):
    return asyncio.run(coroutine)


def test_a_group_reads_and_clears_its_own_items(hud):
    group = hud.skill.group("cargo")
    _run(group.add_info("Gold", "12 SCU"))
    _run(group.add_info("Iron", "3 SCU"))

    assert [i["title"] for i in _run(group.info_items())] == ["Gold", "Iron"]
    assert _run(group.clear())
    assert _run(group.info_items()) == []


def test_a_panel_takes_a_picture_for_beside_its_title(hud):
    group = hud.skill.group("npc")
    _run(group.add_info("Lena Varga", "Lorville", icon="faces/lena.png"))
    _run(hud.skill.add_info("Cargo", "Gold", icon="icons/crate.png"))

    assert hud.manager.get_items("Bob_npc", PERSISTENT)[0]["icon"] == "faces/lena.png"
    assert hud.manager.get_items(GROUP_INFO, PERSISTENT)[0]["icon"] == "icons/crate.png"


def test_a_skill_reads_the_shared_panel_with_who_put_each_panel_there(hud):
    hud.manager.create_group(GROUP_INFO, PERSISTENT)
    hud.manager.add_item(GROUP_INFO, PERSISTENT, "Route", "Hurston", added_by="ATC")

    assert hud.skill.info_items() == [{"title": "Route", "text": "Hurston", "added_by": "ATC"}]


def test_a_skill_cannot_clear_or_hide_the_shared_containers(hud):
    hud.manager.create_group(GROUP_INFO, PERSISTENT)
    hud.manager.add_item(GROUP_INFO, PERSISTENT, "Route", "Hurston")

    assert not HudService().clear_info(GROUP_INFO)
    assert not HudService().set_group_visible(GROUP_INFO, PERSISTENT, False)
    assert len(hud.skill.info_items()) == 1


def test_a_hidden_group_keeps_what_it_holds(hud):
    group = hud.skill.group("cargo")
    _run(group.add_info("Gold", "12 SCU"))

    assert _run(group.hide())
    _run(group.add_info("Iron", "3 SCU"))
    assert _run(group.show())
    assert [i["title"] for i in _run(group.info_items())] == ["Gold", "Iron"]


def test_without_the_hud_every_call_says_so(hud):
    HudService()._server = None
    group = hud.skill.group("cargo")

    assert hud.skill.info_items() == []
    assert not _run(group.clear())
    assert not _run(group.hide())
    assert _run(group.info_items()) == []

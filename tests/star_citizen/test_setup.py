"""The answer to "Do you play Star Citizen?" switches every Star Citizen feature
on or off: the log reader, the bundled lists and the Star Citizen skills and
MCP servers on the shipped Wingmen."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.enums import StarCitizenFeatureKind
from api.interface import ConfigDirInfo, WingmanConfigFileInfo
from services.star_citizen import setup as sc_setup
from services.star_citizen.setup import StarCitizenSetupService

SKILLS = ("ScGameEvents", "SC_Accountant", "UEXCorp")
SERVERS = ("wingman_starhead", "wingman_galactapedia", "wingman_versetime")


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sc_setup.ModuleManager,
        "read_available_skills",
        staticmethod(
            lambda: [
                SimpleNamespace(
                    name=name,
                    config=SimpleNamespace(display_name=name, platforms=None, requires=None),
                )
                for name in SKILLS
            ]
        ),
    )
    monkeypatch.setattr(sc_setup, "find_game_folder", lambda: None)

    config_dir = ConfigDirInfo(
        name="Star Citizen", directory="Star Citizen", is_default=True, is_deleted=False
    )
    wingmen = {
        name: WingmanConfigFileInfo(
            name=name, file=f"{name}.yaml", is_deleted=False, avatar=""
        )
        for name in ("ATC", "Computer", "Mine")
    }
    config_manager = MagicMock()
    config_manager.get_config_dir.return_value = config_dir
    config_manager.get_wingmen_configs.return_value = list(wingmen.values())
    config_manager.can_restore_wingman_from_template.side_effect = (
        lambda config_dir, wingman_file: wingman_file.name != "Mine"
    )
    config_manager.mcp_config = SimpleNamespace(
        servers=[SimpleNamespace(name=name, display_name=name) for name in SERVERS]
    )
    config_manager.load_wingman_config.return_value = SimpleNamespace(
        discoverable_skills=["UEXCorp"], discoverable_mcps=[]
    )

    toggles = []

    async def toggle_skill(config_dir, wingman_file, name, enabled):
        toggles.append((wingman_file.name, name, enabled))

    async def toggle_mcp(config_dir, wingman_file, name, enabled):
        toggles.append((wingman_file.name, name, enabled))

    config_service = SimpleNamespace(
        config_manager=config_manager,
        toggle_wingman_skill=toggle_skill,
        toggle_wingman_mcp=toggle_mcp,
    )

    saved = []

    async def save_settings(settings):
        saved.append(settings)

    settings_service = SimpleNamespace(
        settings=SimpleNamespace(
            sc_gamelog=SimpleNamespace(enabled=True),
            pronunciation=SimpleNamespace(presets=["star_citizen"]),
            stt=SimpleNamespace(presets=["star_citizen", "elite"]),
            star_citizen=SimpleNamespace(plays=None, game_path=str(tmp_path / "missing")),
        ),
        save_settings=save_settings,
    )
    service = StarCitizenSetupService(config_service, settings_service)
    service.printr = MagicMock()
    service.toggles = toggles
    service.saved = saved
    return service


def test_no_switches_everything_off(service):
    asyncio.run(service.apply_answer(False))
    settings = service.saved[0]
    assert settings.sc_gamelog.enabled is False
    assert settings.pronunciation.presets == []
    assert settings.stt.presets == ["elite"]
    assert {(w, n) for w, n, on in service.toggles if not on} == {
        (w, n) for w in ("ATC", "Computer") for n in SKILLS + SERVERS
    }
    assert all(not on for _, _, on in service.toggles)


def test_yes_switches_on_what_is_on_by_default_and_leaves_the_rest(service):
    service.settings_service.settings.sc_gamelog.enabled = False
    service.settings_service.settings.pronunciation.presets = []
    asyncio.run(service.apply_answer(True))
    settings = service.saved[0]
    assert settings.sc_gamelog.enabled is True
    assert settings.pronunciation.presets == ["star_citizen"]
    assert sorted(service.toggles) == sorted(
        [
            ("ATC", "wingman_starhead", True),
            ("ATC", "wingman_galactapedia", True),
            ("Computer", "wingman_starhead", True),
            ("Computer", "wingman_galactapedia", True),
            ("Computer", "ScGameEvents", True),
            ("Computer", "SC_Accountant", True),
        ]
    )


def test_the_users_own_wingmen_are_not_touched(service):
    asyncio.run(service.apply_answer(False))
    assert all(wingman != "Mine" for wingman, _, _ in service.toggles)
    assert [w.wingman_file.name for w in service.get_setup().wingmen] == ["ATC", "Computer"]


def test_the_setup_lists_every_feature_with_its_state(service):
    computer = service.get_setup().wingmen[1]
    states = {f.name: (f.kind, f.enabled, f.on_by_default) for f in computer.features}
    assert states["UEXCorp"] == (StarCitizenFeatureKind.SKILL, True, False)
    assert states["wingman_galactapedia"] == (StarCitizenFeatureKind.MCP, False, True)


def test_a_skill_that_is_not_installed_is_left_out(service, monkeypatch):
    monkeypatch.setattr(
        sc_setup.ModuleManager, "read_available_skills", staticmethod(lambda: [])
    )
    names = {f.name for f in service.get_setup().wingmen[0].features}
    assert names == set(SERVERS)


def test_yes_takes_the_folder_core_found_when_the_set_one_is_not_the_game(
    service, monkeypatch, tmp_path
):
    game = tmp_path / "StarCitizen"
    (game / "LIVE").mkdir(parents=True)
    monkeypatch.setattr(sc_setup, "find_game_folder", lambda: str(game))
    asyncio.run(service.apply_answer(True))
    assert service.saved[0].star_citizen.game_path == str(game)


def test_a_picked_live_folder_checks_the_folder_above_it(service, tmp_path):
    (tmp_path / "LIVE").mkdir()
    folder = service.check_game_folder(str(tmp_path / "LIVE"))
    assert folder.path == str(tmp_path) and folder.environments == ["LIVE"]

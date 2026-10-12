"""The answer to "Do you play Star Citizen?" switches every Star Citizen feature
on or off: the log reader, the bundled lists and the Star Citizen skills and
MCP servers on the shipped Wingmen."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.enums import StarCitizenFeatureKind
from api.interface import ConfigDirInfo, WingmanConfigFileInfo
from services.star_citizen import setup as sc_setup
from services.star_citizen.setup import StarCitizenSetupService
from tests.support import template

SKILLS = ("ScGameEvents", "SC_Accountant", "UEXCorp", "HUD")
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
                    config=SimpleNamespace(
                        display_name=name,
                        platforms=None,
                        requires=["sc_gamelog"]
                        if name in ("ScGameEvents", "SC_Accountant")
                        else None,
                    ),
                )
                for name in SKILLS
            ]
        ),
    )
    monkeypatch.setattr(sc_setup, "find_game_folder", lambda: None)
    game = tmp_path / "StarCitizen"
    (game / "LIVE").mkdir(parents=True)

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
    files = {
        name: SimpleNamespace(discoverable_skills=["UEXCorp"], discoverable_mcps=[])
        for name in wingmen
    }
    config_manager.load_wingman_config.side_effect = (
        lambda config_dir, wingman_file: deepcopy(files[wingman_file.name])
    )
    writes = []

    def save_wingman_config(config_dir, wingman_file, wingman_config):
        writes.append(wingman_file.name)
        files[wingman_file.name] = wingman_config

    config_manager.save_wingman_config.side_effect = save_wingman_config

    reloads = []

    async def load_config(config_dir):
        reloads.append(config_dir.name)

    async def toggle(*args):
        raise AssertionError("the answer must not go through the single toggles")

    config_service = SimpleNamespace(
        config_manager=config_manager,
        current_config_dir=config_dir,
        load_config=load_config,
        toggle_wingman_skill=toggle,
        toggle_wingman_mcp=toggle,
    )

    saved = []

    async def save_settings(settings):
        saved.append(settings)

    settings_service = SimpleNamespace(
        settings=SimpleNamespace(
            sc_gamelog=SimpleNamespace(enabled=True),
            pronunciation=SimpleNamespace(presets=["star_citizen"]),
            stt=SimpleNamespace(presets=["star_citizen", "elite"]),
            star_citizen=SimpleNamespace(plays=None, game_path=str(game)),
        ),
        save_settings=save_settings,
    )
    service = StarCitizenSetupService(config_service, settings_service)
    service.printr = MagicMock()
    service.files = files
    service.writes = writes
    service.reloads = reloads
    service.saved = saved
    return service


def test_no_switches_everything_off(service):
    asyncio.run(service.apply_answer(False))
    settings = service.saved[0]
    assert settings.sc_gamelog.enabled is False
    assert settings.pronunciation.presets == []
    assert settings.stt.presets == ["elite"]
    assert settings.star_citizen.plays is False
    for name in ("ATC", "Computer"):
        assert service.files[name].discoverable_skills == []
        assert service.files[name].discoverable_mcps == []


def test_yes_switches_on_what_is_on_by_default_and_leaves_the_rest(service):
    service.settings_service.settings.sc_gamelog.enabled = False
    service.settings_service.settings.pronunciation.presets = []
    asyncio.run(service.apply_answer(True))
    settings = service.saved[0]
    assert settings.sc_gamelog.enabled is True
    assert settings.pronunciation.presets == ["star_citizen"]
    assert settings.star_citizen.plays is True
    assert service.files["ATC"].discoverable_skills == ["UEXCorp"]
    assert service.files["ATC"].discoverable_mcps == [
        "wingman_starhead",
        "wingman_versetime",
    ]
    assert service.files["Computer"].discoverable_skills == [
        "UEXCorp",
        "ScGameEvents",
    ]
    assert service.files["Computer"].discoverable_mcps == list(SERVERS)


def test_the_answer_writes_each_wingman_once_and_reloads_once(service):
    asyncio.run(service.apply_answer(True))
    assert sorted(service.writes) == ["ATC", "Computer"]
    assert service.reloads == ["Star Citizen"]


def test_no_reload_when_another_config_is_open(service):
    service.config_service.current_config_dir = SimpleNamespace(name="Elite")
    asyncio.run(service.apply_answer(True))
    assert sorted(service.writes) == ["ATC", "Computer"]
    assert service.reloads == []


def test_no_write_and_no_reload_when_nothing_changes(service):
    asyncio.run(service.apply_answer(True))
    service.writes.clear()
    service.reloads.clear()
    asyncio.run(service.apply_answer(True))
    assert service.writes == [] and service.reloads == []


def test_a_wingman_that_fails_does_not_stop_the_others(service):
    def save_wingman_config(config_dir, wingman_file, wingman_config):
        if wingman_file.name == "ATC":
            raise OSError("disk full")
        service.files[wingman_file.name] = wingman_config

    service.config_manager.save_wingman_config.side_effect = save_wingman_config
    setup = asyncio.run(service.apply_answer(True))
    assert "wingman_starhead" in service.files["Computer"].discoverable_mcps
    assert service.reloads == ["Star Citizen"]
    assert [w.wingman_file.name for w in setup.wingmen] == ["ATC", "Computer"]


def test_the_users_own_wingmen_are_not_touched(service):
    asyncio.run(service.apply_answer(False))
    assert "Mine" not in service.writes
    assert [w.wingman_file.name for w in service.get_setup().wingmen] == ["ATC", "Computer"]


def test_the_setup_lists_every_feature_with_its_state(service):
    computer = service.get_setup().wingmen[1]
    states = {f.name: (f.kind, f.enabled, f.on_by_default) for f in computer.features}
    assert states["UEXCorp"] == (StarCitizenFeatureKind.SKILL, True, False)
    assert states["wingman_galactapedia"] == (StarCitizenFeatureKind.MCP, False, True)


def test_galactapedia_is_on_by_default_for_the_computer_only(service):
    atc, computer = service.get_setup().wingmen

    def on(wingman):
        return {f.name for f in wingman.features if f.on_by_default}

    assert "wingman_galactapedia" not in on(atc)
    assert "wingman_galactapedia" in on(computer)


def test_uexcorp_is_listed_right_after_starhead(service):
    names = [f.name for f in service.get_setup().wingmen[0].features]
    assert names[names.index("wingman_starhead") + 1] == "UEXCorp"


def test_a_skill_that_is_not_installed_is_left_out(service, monkeypatch):
    monkeypatch.setattr(
        sc_setup.ModuleManager, "read_available_skills", staticmethod(lambda: [])
    )
    names = {f.name for f in service.get_setup().wingmen[0].features}
    assert names == set(SERVERS)


def test_yes_takes_the_folder_core_found_when_the_set_one_is_not_the_game(
    service, monkeypatch, tmp_path
):
    service.settings_service.settings.star_citizen.game_path = str(tmp_path / "missing")
    game = tmp_path / "Found" / "StarCitizen"
    (game / "LIVE").mkdir(parents=True)
    monkeypatch.setattr(sc_setup, "find_game_folder", lambda: str(game))
    asyncio.run(service.apply_answer(True))
    assert service.saved[0].star_citizen.game_path == str(game)


def test_yes_without_the_game_leaves_the_log_reader_and_its_skills_off(
    service, tmp_path
):
    service.settings_service.settings.star_citizen.game_path = str(tmp_path / "missing")
    asyncio.run(service.apply_answer(True))
    assert service.saved[0].sc_gamelog.enabled is False
    assert "ScGameEvents" not in service.files["Computer"].discoverable_skills
    assert "wingman_starhead" in service.files["Computer"].discoverable_mcps


def test_a_picked_live_folder_checks_the_folder_above_it(service, tmp_path):
    (tmp_path / "LIVE").mkdir()
    folder = service.check_game_folder(str(tmp_path / "LIVE"))
    assert folder.path == str(tmp_path) and folder.environments == ["LIVE"]


def test_a_shipped_server_missing_from_mcp_yaml_is_added_from_the_template(service):
    config_manager = service.config_manager
    config_manager.mcp_config.servers = [
        s for s in config_manager.mcp_config.servers if s.name != "wingman_galactapedia"
    ]
    config_manager.read_config.return_value = template("mcp.template.yaml")
    asyncio.run(service.apply_answer(True))
    assert "wingman_galactapedia" in {s.name for s in config_manager.mcp_config.servers}
    config_manager.save_mcp_config.assert_called_once()
    assert "wingman_galactapedia" in service.files["Computer"].discoverable_mcps


def test_no_adds_no_servers(service):
    service.config_manager.mcp_config.servers = []
    service.config_manager.read_config.return_value = template("mcp.template.yaml")
    asyncio.run(service.apply_answer(False))
    service.config_manager.save_mcp_config.assert_not_called()


@pytest.mark.parametrize("plays", [True, False])
def test_the_answer_leaves_the_hud_as_it_is(service, plays):
    service.files["ATC"].discoverable_skills = ["HUD"]
    asyncio.run(service.apply_answer(plays))
    assert "HUD" in service.files["ATC"].discoverable_skills
    assert "HUD" not in service.files["Computer"].discoverable_skills


def test_the_hud_is_listed_and_marked_as_not_star_citizen(service):
    service.files["ATC"].discoverable_skills = ["HUD"]
    hud = {f.name: f for f in service.get_setup().wingmen[0].features}["HUD"]
    assert hud.enabled is True
    assert hud.star_citizen is False
    assert hud.on_by_default is False


@pytest.mark.parametrize(
    "enabled, plays, runs",
    [(True, True, True), (True, None, False), (True, False, False), (False, True, False)],
)
def test_the_log_reader_runs_only_for_players(enabled, plays, runs):
    settings = SimpleNamespace(
        sc_gamelog=SimpleNamespace(enabled=enabled),
        star_citizen=SimpleNamespace(plays=plays),
    )
    assert sc_setup.log_reader_on(settings) is runs

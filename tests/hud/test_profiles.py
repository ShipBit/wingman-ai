"""HUD profiles: one default, a config in at most one profile, and what the
API allows."""

import asyncio
from os import path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.interface import CreateHudProfileRequest, HudProfile, HudProfilePreviewRequest
from services import hud_profiles
from services.hud_service import HudService
from tests.support import TEMPLATES, template


def _profile(profile_id: str, *, default=False, configs=()) -> HudProfile:
    data = template("settings.yaml")["hud_profiles"][0]
    return HudProfile(**{**data, "id": profile_id, "name": profile_id, "is_default": default,
                         "configs": list(configs)})


@pytest.fixture
def service():
    HudService._instance = None
    settings = SimpleNamespace(hud_profiles=[_profile("default", default=True)], user_name=None)
    config_manager = SimpleNamespace(
        settings_config=settings,
        save_settings_config=MagicMock(),
        templates_dir=path.dirname(TEMPLATES),
    )
    config_service = SimpleNamespace(
        current_config_dir=SimpleNamespace(name="Star Citizen"),
        config_events=MagicMock(),
    )
    hud = HudService()
    hud.configure(config_manager, config_service)
    asyncio.run(hud.channel_loaded("Star Citizen"))
    yield hud
    HudService._instance = None


def _run(coro):
    return asyncio.run(coro)


def test_the_last_profile_left_is_the_default():
    profiles = [_profile("a", default=True), _profile("b")]
    profiles[0].is_default = False
    hud_profiles.normalize(profiles)
    assert [p.is_default for p in profiles] == [True, False]


def test_a_config_named_by_a_profile_gets_it_others_get_the_default():
    profiles = [_profile("default", default=True), _profile("sc", configs=["Star Citizen"])]

    assert hud_profiles.active_profile(profiles, "Star Citizen").id == "sc"
    assert hud_profiles.active_profile(profiles, "Elite").id == "default"


def test_giving_a_config_to_a_profile_takes_it_from_the_other():
    profiles = [_profile("a", configs=["Star Citizen", "Elite"]), _profile("b")]

    hud_profiles.assign_configs(profiles, "b", ["Star Citizen"])

    assert profiles[0].configs == ["Elite"]
    assert profiles[1].configs == ["Star Citizen"]


def test_a_renamed_config_keeps_its_profile():
    profiles = [_profile("a", configs=["Star Citizen"])]

    hud_profiles.rename_config(profiles, "Star Citizen", "SC 4.0")

    assert profiles[0].configs == ["SC 4.0"]


def test_the_default_profile_cannot_be_deleted(service):
    with pytest.raises(HTTPException) as error:
        _run(service.delete_hud_profile("default"))
    assert error.value.status_code == 409


def test_a_new_profile_starts_from_the_template_and_is_not_the_default(service):
    state = _run(service.create_hud_profile(CreateHudProfileRequest(name="Racing")))

    new = state.profiles[-1]
    assert (new.name, new.is_default, new.configs) == ("Racing", False, [])
    assert new.chat == state.profiles[0].chat
    service.config_manager.save_settings_config.assert_called()


def test_making_another_profile_the_default_lets_the_old_one_be_deleted(service):
    state = _run(service.create_hud_profile(CreateHudProfileRequest(name="Racing")))
    racing = state.profiles[-1].id

    _run(service.set_default_hud_profile(racing))
    state = _run(service.delete_hud_profile("default"))

    assert [(p.id, p.is_default) for p in state.profiles] == [(racing, True)]


def test_an_update_cannot_take_the_default_away(service):
    stale = service.state().profiles[0].model_copy(update={"is_default": False, "name": "Main"})

    state = _run(service.update_hud_profile("default", stale))

    assert (state.profiles[0].name, state.profiles[0].is_default) == ("Main", True)


def test_the_profile_naming_the_loaded_config_is_active(service):
    state = _run(service.create_hud_profile(CreateHudProfileRequest(name="SC", copy_from="default")))
    sc = state.profiles[-1].model_copy(update={"configs": ["Star Citizen"]})

    state = _run(service.update_hud_profile(sc.id, sc))

    assert state.active_profile_id == sc.id


def test_only_one_profile_is_previewed(service):
    state = _run(service.create_hud_profile(CreateHudProfileRequest(name="Racing")))
    racing = state.profiles[-1].id

    _run(service.set_hud_profile_preview("default", HudProfilePreviewRequest(enabled=True)))
    state = _run(service.set_hud_profile_preview(racing, HudProfilePreviewRequest(enabled=True)))
    assert state.preview_profile_id == racing

    state = _run(service.set_hud_profile_preview("default", HudProfilePreviewRequest(enabled=False)))
    assert state.preview_profile_id == racing


def test_renaming_the_loaded_config_keeps_its_profile_on_the_hud(service):
    state = _run(service.create_hud_profile(CreateHudProfileRequest(name="SC")))
    sc = state.profiles[-1].model_copy(update={"configs": ["Star Citizen"]})
    _run(service.update_hud_profile(sc.id, sc))
    service._server = MagicMock(is_running=True)

    _run(service._on_config_renamed(("Star Citizen", "SC 4.0")))

    # Still the same profile on screen, under the config's new name
    state = service.state()
    assert state.profiles[-1].configs == ["SC 4.0"]
    assert state.active_profile_id == sc.id

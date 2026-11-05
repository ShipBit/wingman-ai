"""Star Citizen telemetry on a channel it has not reached yet: the code ships,
but the stream never starts and the UI shows none of its settings."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from services import features
from services.features import drop_unreleased_properties
from services.sc_telemetry.service import ScTelemetryService
from services.star_citizen import setup as sc_setup
from tests.support import REPO_ROOT

SC_EVENTS = Path(REPO_ROOT) / "skills" / "sc_game_events" / "default_config.yaml"


@pytest.fixture
def unreleased(monkeypatch):
    monkeypatch.setattr(features, "SC_TELEMETRY_RELEASED", False)


def _sc_events() -> dict:
    return yaml.safe_load(SC_EVENTS.read_text(encoding="utf-8"))


def _telemetry_groups(manifest: dict) -> set[str]:
    return {group["id"] for group in manifest["property_groups"] if group.get("feature") == features.SC_TELEMETRY}


def test_unreleased_telemetry_never_runs_even_when_switched_on(unreleased):
    settings = SimpleNamespace(
        sc_telemetry=SimpleNamespace(enabled=True),
        star_citizen=SimpleNamespace(plays=True),
    )
    assert sc_setup.telemetry_on(settings) is False


def test_unreleased_telemetry_says_so_in_its_status(unreleased):
    assert ScTelemetryService().status().released is False


def test_star_citizen_events_offers_no_telemetry_setting_while_unreleased(unreleased):
    manifest = _sc_events()
    telemetry_groups = _telemetry_groups(manifest)
    assert telemetry_groups

    offered = drop_unreleased_properties(manifest)

    assert not {group["id"] for group in offered["property_groups"]} & telemetry_groups
    assert not [prop["id"] for prop in offered["custom_properties"] if prop.get("group") in telemetry_groups]
    assert any(prop["id"] == "react_mission" for prop in offered["custom_properties"])


def test_released_telemetry_keeps_every_setting():
    manifest = _sc_events()
    count = len(manifest["custom_properties"])

    offered = drop_unreleased_properties(manifest)

    assert len(offered["custom_properties"]) == count
    assert _telemetry_groups(offered)

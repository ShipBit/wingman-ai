"""The Star Citizen tests run against a real log reader on a fake Game.log and a real telemetry reader on a fake
game server."""

import pytest

from services.sc_gamelog import reader as reader_module
from services.sc_gamelog import service as service_module
from services.sc_gamelog import tailer as tailer_module
from services.sc_gamelog.item_names import ItemNamesSource
from services.sc_gamelog.rules import RulesSource
from services.sc_telemetry import reader as telemetry_reader_module
from services.sc_telemetry import service as telemetry_module
from tests.star_citizen.telemetry import FakeGame


@pytest.fixture
def reader(tmp_path, monkeypatch):
    """A fresh log reader that keeps its data in tmp_path, polls fast and never
    reaches GitHub for its rules or item names."""
    monkeypatch.setattr(service_module, "get_generated_files_dir", lambda _: str(tmp_path / "data"))
    monkeypatch.setattr(service_module, "POLL_SECONDS", 0.02)
    # The parse budget is wall time. On a busy CI runner the reader thread can
    # wait longer than that for the CPU, and the line is dropped as too slow.
    monkeypatch.setattr(reader_module, "PARSE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(reader_module, "REGEX_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(tailer_module, "REGEX_TIMEOUT_SECONDS", 5.0)

    async def offline(self):
        raise OSError("offline in tests")

    monkeypatch.setattr(RulesSource, "_fetch", offline)
    monkeypatch.setattr(ItemNamesSource, "_fetch", offline)
    service_module.ScGameLogService._instance = None
    yield service_module.ScGameLogService()
    service_module.ScGameLogService._instance = None


@pytest.fixture
def game(monkeypatch):
    """A fake game with telemetry, and Core's telemetry pointed at it."""
    fake = FakeGame()
    monkeypatch.setattr(telemetry_reader_module, "ADDRESS", fake.address)
    yield fake
    fake.stop()


@pytest.fixture
def telemetry(tmp_path, monkeypatch):
    """A fresh telemetry service that keeps its data in tmp_path and never touches the Windows registry."""
    monkeypatch.setattr(telemetry_module, "get_generated_files_dir", lambda _: str(tmp_path / "telemetry"))
    monkeypatch.setattr(telemetry_module.windows_env, "MANAGED", False)
    monkeypatch.setattr(telemetry_module, "MONITOR_S", 0.05)
    monkeypatch.setattr(telemetry_reader_module, "RETRY_S", (0.1,))
    telemetry_module.ScTelemetryService._instance = None
    yield telemetry_module.ScTelemetryService()
    telemetry_module.ScTelemetryService._instance = None

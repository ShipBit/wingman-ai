"""The Star Citizen tests run against a real log reader on a fake Game.log."""

import pytest

from services.sc_gamelog import reader as reader_module
from services.sc_gamelog import service as service_module
from services.sc_gamelog import tailer as tailer_module
from services.sc_gamelog.item_names import ItemNamesSource
from services.sc_gamelog.rules import RulesSource


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

"""The Star Citizen tests run against a real log reader on a fake Game.log."""

import pytest

from services.sc_gamelog import service as service_module
from services.sc_gamelog.rules import RulesSource


@pytest.fixture
def reader(tmp_path, monkeypatch):
    """A fresh log reader that keeps its data in tmp_path, polls fast and never
    reaches GitHub for its rules."""
    monkeypatch.setattr(service_module, "get_generated_files_dir", lambda _: str(tmp_path / "data"))
    monkeypatch.setattr(service_module, "POLL_SECONDS", 0.02)

    async def offline(self):
        raise OSError("offline in tests")

    monkeypatch.setattr(RulesSource, "_fetch", offline)
    service_module.ScGameLogService._instance = None
    yield service_module.ScGameLogService()
    service_module.ScGameLogService._instance = None

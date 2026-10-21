"""Fixtures for the UEX skill tests: real sqlite databases in tmp_path, fake relay and helper."""

import pytest

from skills.uexcorp.uexcorp.api.uex import Uex
from skills.uexcorp.uexcorp.database.database import Database
from skills.uexcorp.uexcorp.handler.import_handler import ImportHandler
from skills.uexcorp.uexcorp.helper import Helper
from tests.skills.uexcorp.support import FakeHelper, FastStop, ImportEnv, ImportHelper


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """What the tools run on: a fake Helper with an empty database. Tests seed the tables they need."""
    fake = FakeHelper(str(tmp_path))
    monkeypatch.setattr(Helper, "_instance", fake)
    database = Database(str(tmp_path), version="test", helper=fake)
    fake.set_database(database)
    yield fake
    database.destroy()


@pytest.fixture
def db(helper):
    return helper.get_database()


@pytest.fixture
def import_env(tmp_path, monkeypatch):
    """An import handler with an empty database. Tests hand it a fake relay."""
    fake = ImportHelper()
    monkeypatch.setattr(Helper, "_instance", fake)
    fake.db = Database(str(tmp_path), version="test-import", helper=fake)
    importer = ImportHandler(fake)
    fake.importer = importer
    yield ImportEnv(fake, importer)
    fake.db.destroy()


@pytest.fixture
def relay_client():
    """The relay client with its retry waits skipped: stop.waited lists what it would have waited."""
    client = Uex(ImportHelper())
    client._Uex__stop = FastStop()
    return client

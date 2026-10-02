"""Secrets are kept on disk, survive a restart and never touch the real file.

SecretKeeper is a singleton that reads the secrets file once when it is first
created. Every test redirects the config folder into a tmp folder before that
first load and resets the singleton, so the user's own secrets file is never
read or written.
"""

import asyncio
from os import path

import pytest

from services.config_manager import SECRETS_FILE
from services.secret_keeper import SecretKeeper
from tests.support import read_yaml, write_yaml


class FakeConnectionManager:
    def __init__(self):
        self.sent = []

    async def broadcast(self, command):
        self.sent.append(command)


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    """A tmp config folder. The singleton is reset before and after the test."""
    import services.secret_keeper as keeper_module

    monkeypatch.setattr(keeper_module, "get_writable_dir", lambda *_: str(tmp_path))
    monkeypatch.setattr(SecretKeeper, "_instance", None)
    monkeypatch.setattr(SecretKeeper, "prompted_secrets", [])
    monkeypatch.setattr(SecretKeeper, "_connection_manager", FakeConnectionManager())
    return tmp_path


def secrets_file(folder):
    return path.join(str(folder), SECRETS_FILE)


def restart():
    """What a new Core start does: forget the instance, load from disk again."""
    SecretKeeper._instance = None
    return SecretKeeper()


# ── loading ──


def test_a_saved_secret_survives_a_restart(secrets_dir):
    keeper = SecretKeeper()
    assert asyncio.run(keeper.post_secrets({"openai": "sk-test-123"})) is None

    reloaded = restart()

    assert reloaded.config_file.startswith(str(secrets_dir))
    assert reloaded.secrets == {"openai": "sk-test-123"}


def test_a_missing_secrets_file_loads_as_no_secrets(secrets_dir):
    keeper = SecretKeeper()

    assert keeper.secrets == {}
    assert keeper.load() == {}


def test_an_empty_secrets_file_loads_as_no_secrets(secrets_dir):
    open(secrets_file(secrets_dir), "w").close()

    assert SecretKeeper().secrets == {}


def test_a_broken_secrets_file_loads_as_no_secrets_instead_of_raising(secrets_dir):
    with open(secrets_file(secrets_dir), "w", encoding="UTF-8") as f:
        f.write("openai: [unclosed")

    assert SecretKeeper().secrets == {}


# ── retrieve ──


def test_retrieve_returns_the_stored_secret_without_prompting(secrets_dir):
    write_yaml(secrets_file(secrets_dir), {"openai": "sk-test-123"})
    keeper = SecretKeeper()

    value = asyncio.run(keeper.retrieve("wingman", "openai", prompt_if_missing=False))

    assert value == "sk-test-123"
    assert keeper._connection_manager.sent == []


def test_retrieve_of_a_missing_secret_returns_empty_and_never_prompts_when_told_not_to(
    secrets_dir,
):
    keeper = SecretKeeper()

    value = asyncio.run(keeper.retrieve("wingman", "openai", prompt_if_missing=False))

    assert value == ""
    assert keeper._connection_manager.sent == []


def test_a_missing_secret_prompts_the_client_only_once(secrets_dir):
    keeper = SecretKeeper()

    async def ask_twice():
        await keeper.retrieve("wingman", "openai")
        await keeper.retrieve("wingman", "openai")

    asyncio.run(ask_twice())

    sent = keeper._connection_manager.sent
    assert len(sent) == 1
    assert sent[0].secret_name == "openai"
    assert sent[0].requester == "wingman"


# ── post_secrets ──


def test_posting_secrets_adds_new_keys_and_overwrites_existing_ones(secrets_dir):
    write_yaml(secrets_file(secrets_dir), {"openai": "sk-old", "hume": "hume-test-1"})
    keeper = SecretKeeper()

    asyncio.run(keeper.post_secrets({"openai": "sk-test-123", "inworld": "iw-test-1"}))

    expected = {"openai": "sk-test-123", "hume": "hume-test-1", "inworld": "iw-test-1"}
    assert keeper.secrets == expected
    assert read_yaml(secrets_file(secrets_dir)) == expected


"""The 3.1.6 config a user upgrades from has to end up loadable.

tests/fixtures/defaults_3_1_6.yaml is the `defaults.yaml` 3.1.6 shipped,
unchanged. Every user coming to v3 has that file or something derived from
it, and it names three things that no longer exist:
`wingman_pro.stt_provider: azure_speech`, `tts_provider: azure` and a whole
`azure:` section.
"""

from os import path
from unittest.mock import MagicMock

import pytest

from api.enums import WingmanProTtsProvider
from api.interface import NestedConfig
from services.config_sanitizer import sanitize
from services.migrations.migration_316_to_320 import Migration316To320, voice_to_inworld
from tests.support import FIXTURES, read_yaml


@pytest.fixture
def defaults_316() -> dict:
    return read_yaml(path.join(FIXTURES, "defaults_3_1_6.yaml"))


@pytest.fixture
def migration() -> Migration316To320:
    service = MagicMock()
    return Migration316To320(service)


def test_the_migration_makes_it_loadable(defaults_316, migration):
    migrated = migration.migrate_defaults(defaults_316)

    config = NestedConfig(**migrated)
    # `wingman_pro.stt_provider` is an intermediate value here: 3.2.2 drops it.
    assert migrated["wingman_pro"]["stt_provider"] == "cloud"
    assert config.wingman_pro.tts_provider is WingmanProTtsProvider.INWORLD
    assert "azure" not in migrated


def test_an_azure_deployment_name_becomes_the_plan_default(defaults_316, migration):
    """3.1.6 stored `gpt-4.1-mini`, an Azure deployment name that means nothing
    after 3.2. The empty value means "the plan's default". Writing a model name
    here instead would pin every upgrading user to the model that was default
    on release day."""
    assert defaults_316["wingman_pro"]["conversation_deployment"] == "gpt-4.1-mini"

    migrated = migration.migrate_defaults(defaults_316)

    assert migrated["wingman_pro"]["conversation_deployment"] == ""


def test_a_model_the_user_picked_survives(migration):
    """Someone who chose a specific model keeps it."""
    config = {"wingman_pro": {"conversation_deployment": "openai/gpt-4.1-mini"}}

    migrated = migration.migrate_wingman(config)

    assert migrated["wingman_pro"]["conversation_deployment"] == "openai/gpt-4.1-mini"


def test_the_language_list_survives_the_azure_section(migration):
    """`voice_activation.azure.languages` had nothing to do with Azure — it is
    what the cloud transcription auto-detects. Dropping the section must not
    drop the list."""
    config = {
        "voice_activation": {
            "stt_provider": "azure",
            "azure": {"languages": ["de-DE", "en-US"]},
        }
    }
    # voice_activation lives in settings.yaml, not in a wingman config.
    migrated = migration.migrate_settings(config)

    assert migrated["voice_activation"]["languages"] == ["de-DE", "en-US"]
    assert "azure" not in migrated["voice_activation"]
    assert migrated["voice_activation"]["stt_provider"] != "azure"


def test_a_wingman_without_a_pro_block_still_gets_fixed(migration):
    """Most per-wingman files only override a few keys and have no
    `wingman_pro:` section. The rewrite must not depend on one being there."""
    config = {
        "features": {
            "tts_provider": "azure",
            "stt_provider": "azure_speech",
            "conversation_provider": "azure",
        }
    }
    migrated = migration.migrate_wingman(config)
    features = migrated["features"]

    assert "azure" not in (features["tts_provider"], features["conversation_provider"])
    assert features["stt_provider"] not in ("azure", "azure_speech")
    # And no empty block invented, which would fail validation on its own.
    assert "wingman_pro" not in migrated


def test_the_sanitizer_catches_what_the_migration_skips(defaults_316):
    """Belt and braces: a config that never ran the migration — someone who
    edited the YAML by hand, or a path we did not think of — still loads."""
    untouched = dict(defaults_316)

    sanitize(NestedConfig, untouched)
    # The sanitizer only repairs enums; the `azure:` section is an unknown key,
    # which Pydantic ignores anyway.
    config = NestedConfig(**untouched)

    assert config.features.tts_provider.value != "azure"


def test_an_azure_voice_keeps_its_gender_and_language(migration):
    """An Azure name carries both: "de-DE-KatjaNeural" is a German woman, and a
    user who picked that should not wake up sounding like an English man."""
    config = {
        "features": {"tts_provider": "wingman_pro"},
        "wingman_pro": {"tts_provider": "azure"},
        "azure": {"tts": {"voice": "de-DE-ConradNeural"}},
    }
    migrated = migration.migrate_wingman(config)

    assert migrated["wingman_pro"]["tts_provider"] == "inworld"
    assert migrated["inworld"]["voice_id"] == "Matthias"


def test_an_openai_voice_also_moves_to_inworld(migration):
    """A config from the 3.2 previews has an OpenAI voice, not an Azure one.
    OpenAI speech is gone too, so that config needs the same treatment."""
    config = {
        "features": {"tts_provider": "wingman_pro"},
        "wingman_pro": {"tts_provider": "openai"},
        "openai": {"tts_voice": "onyx"},
    }
    migrated = migration.migrate_wingman(config)

    assert migrated["wingman_pro"]["tts_provider"] == "inworld"
    assert migrated["inworld"]["voice_id"] == "Edward"


@pytest.mark.parametrize(
    "old,expected",
    [
        ("de-DE-KatjaNeural", "Johanna"),
        ("de-DE-ConradNeural", "Matthias"),
        ("en-US-JennyNeural", "Ashley"),
        ("en-US-GuyNeural", "Edward"),
        ("nova", "Ashley"),
        ("onyx", "Edward"),
        # Unknown German name: language is still readable, gender is not.
        ("de-DE-Someone", "Johanna"),
        (None, "Ashley"),
        ("", "Ashley"),
    ],
)
def test_voice_mapping(old, expected):
    assert voice_to_inworld(old) == expected


def test_the_support_model_moves_to_the_cloud(migration):
    """A 3.1.6 config says where llama.cpp runs with a boolean. 3.2.0 has three
    places it can run, and everyone starts in the cloud: running it locally
    cost users RAM and CPU."""
    config = {"llama_cpp": {"run_locally": True, "n_ctx": 4096}}

    migrated = migration.migrate_settings(config)
    llama = migrated["llama_cpp"]

    assert llama["mode"] == "cloud"
    assert "run_locally" not in llama
    assert llama["support_cloud_model"] == ""
    # Untouched keys stay untouched.
    assert llama["n_ctx"] == 4096


def test_a_users_own_llama_server_stays_configured(migration):
    """Someone running llama-server on a second machine is moved to cloud like
    everyone else, but their host and port must survive: switching back has to
    be one click, not retyping an address they looked up months ago."""
    config = {
        "llama_cpp": {
            "run_locally": False,
            "support_remote_host": "http://192.168.1.50",
            "support_remote_port": 8080,
        }
    }

    llama = migration.migrate_settings(config)["llama_cpp"]

    assert llama["mode"] == "cloud"
    assert llama["support_remote_host"] == "http://192.168.1.50"
    assert llama["support_remote_port"] == 8080


def test_a_settings_file_without_a_llama_block_is_left_alone(migration):
    """Inventing a half-filled block would fail validation on its own — the
    required keys like n_ctx would be missing."""
    assert "llama_cpp" not in migration.migrate_settings({"debug_mode": False})


def test_the_old_azure_token_is_removed_from_secrets(migration):
    """Before 3.2 this key held a token for a different sign-in service. Core
    sends the key as a bearer token, so keeping it would send a credential
    for one service to another, and leave it on disk until the next sign-in."""
    secrets = migration.migrate_secrets(
        {"wingman_pro": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.azure", "openai": "sk-abc"}
    )

    assert "wingman_pro" not in secrets
    assert secrets["openai"] == "sk-abc"


def test_a_device_token_survives(migration):
    """Someone who already signed in to 3.2 before migrating has a valid
    token there. Throwing it away would sign them out for no reason."""
    secrets = migration.migrate_secrets({"wingman_pro": "wgd_live_abc123"})

    assert secrets["wingman_pro"] == "wgd_live_abc123"


def test_secrets_without_a_wingman_pro_key_are_left_alone(migration):
    assert migration.migrate_secrets({"openai": "sk-abc"}) == {"openai": "sk-abc"}


def test_an_empty_token_is_not_reported_as_removed(migration):
    """An empty string is not a credential, so there is nothing to warn about."""
    secrets = migration.migrate_secrets({"wingman_pro": ""})

    assert secrets["wingman_pro"] == ""


# ── summarisation thresholds ───────────────────────────────────────

def test_the_condense_thresholds_move_with_the_new_token_ceiling(migration):
    """3.2.0 raises the summarisation token ceiling from 16,000 to 40,000.

    If ``condense_max_messages`` stayed at 50, the message count would keep
    firing first and none of the new ceiling would reach the user.
    """
    config = {"features": {"condense_max_messages": 50, "condense_keep_recent": 6}}

    result = migration.migrate_wingman(config)

    assert result["features"]["condense_max_messages"] == 150
    assert result["features"]["condense_keep_recent"] == 12


def test_an_own_setting_is_not_overwritten(migration):
    """Anyone who set their own number keeps it. Only a config still sitting on
    the old default is touched."""
    config = {"features": {"condense_max_messages": 20, "condense_keep_recent": 30}}

    result = migration.migrate_wingman(config)

    assert result["features"]["condense_max_messages"] == 20
    assert result["features"]["condense_keep_recent"] == 30


def test_a_wingman_without_a_features_block_is_left_alone(migration):
    """Most wingman files only override what differs from the defaults and carry
    no ``features`` block at all."""
    assert "features" not in migration.migrate_wingman({"name": "Computer"})


def test_an_unused_pro_voice_does_not_overwrite_the_inworld_one(migration):
    """The shipped 3.1.6 default was `features.tts_provider: pocket_tts` with a
    dormant `wingman_pro.tts_provider: azure`. Someone who drives Inworld with
    their own key and picked a voice there must keep it — the Azure name in the
    Pro section was never spoken."""
    config = {
        "features": {"tts_provider": "inworld"},
        "wingman_pro": {"tts_provider": "azure"},
        "azure": {"tts": {"voice": "de-DE-ConradNeural"}},
        "inworld": {"voice_id": "Craig"},
    }
    migrated = migration.migrate_wingman(config)

    assert migrated["wingman_pro"]["tts_provider"] == "inworld"
    assert migrated["inworld"]["voice_id"] == "Craig"


def test_a_wingman_without_its_own_tts_provider_is_left_to_the_defaults(migration):
    """A per-wingman file that never set `features.tts_provider` inherits it.
    defaults.yaml is migrated in the same run, so nothing is lost by skipping."""
    config = {
        "wingman_pro": {"tts_provider": "azure"},
        "azure": {"tts": {"voice": "de-DE-ConradNeural"}},
    }
    migrated = migration.migrate_wingman(config)

    assert migrated["wingman_pro"]["tts_provider"] == "inworld"
    assert "inworld" not in migrated or "voice_id" not in migrated.get("inworld", {})

"""3.2.1 shipped ElevenLabs with a tool whitelist; 3.2.2 keeps every tool visible
and stores what is switched off. A user's mcp.yaml has to come out with the
matching disabled list and no glob fields left behind.
"""

from copy import deepcopy
from unittest.mock import MagicMock

from api.interface import McpConfig, NestedConfig, SettingsConfig
from services.migrations.migration_320_to_321 import ELEVENLABS_SERVER
from services.migrations.migration_321_to_322 import (
    ELEVENLABS_DISABLED_TOOLS,
    Migration321To322,
)
from tests.support import template


def _migration() -> Migration321To322:
    return Migration321To322(MagicMock())


def test_elevenlabs_whitelist_becomes_disabled_list():
    old = {"servers": [dict(ELEVENLABS_SERVER)]}
    out = _migration().migrate_mcp(old, {})
    server = out["servers"][0]
    assert "tools_allow" not in server
    assert "tools_deny" not in server
    assert server["disabled_tools"] == ELEVENLABS_DISABLED_TOOLS
    assert not set(ELEVENLABS_SERVER["tools_allow"]) & set(server["disabled_tools"])
    McpConfig(**out)


def test_disabled_list_matches_template():
    entry = next(s for s in template("mcp.template.yaml")["servers"] if s["name"] == "elevenlabs")
    assert entry["disabled_tools"] == ELEVENLABS_DISABLED_TOOLS
    assert len(entry["disabled_tools"]) == 104


def test_other_servers_lose_globs_and_keep_the_rest():
    old = {
        "servers": [
            {"name": "x", "display_name": "X", "type": "http", "url": "https://x", "tools_deny": ["a"]},
            {"name": "y", "display_name": "Y", "type": "http", "url": "https://y"},
        ]
    }
    out = _migration().migrate_mcp(old, {})
    assert "tools_deny" not in out["servers"][0]
    assert "disabled_tools" not in out["servers"][0]
    assert out["servers"][1] == old["servers"][1]


def test_hand_edited_disabled_list_wins():
    server = dict(ELEVENLABS_SERVER)
    server["disabled_tools"] = ["creative_generate_video"]
    out = _migration().migrate_mcp({"servers": [server]}, {})
    assert out["servers"][0]["disabled_tools"] == ["creative_generate_video"]


def test_missing_file_uses_template():
    new = {"servers": []}
    assert _migration().migrate_mcp({}, new) is new


# ── Inworld TTS prompt ────────────────────────────────────────────────


def test_the_inworld_prompt_is_replaced_for_everyone():
    config = {"name": "Computer", "inworld": {"voice_id": "Olivia", "tts_prompt": "Use [breathe] regularly."}}

    result = _migration().migrate_wingman(config)

    # Dropped here, backfilled from the template afterwards.
    assert "tts_prompt" not in result["inworld"]
    assert result["inworld"]["voice_id"] == "Olivia"


def test_defaults_lose_the_prompt_as_well():
    result = _migration().migrate_defaults({"inworld": {"tts_prompt": "anything"}, "features": {}})

    assert "tts_prompt" not in result["inworld"]


def test_a_config_without_an_inworld_block_is_left_alone():
    assert _migration().migrate_wingman({"name": "x"}) == {"name": "x"}


# --- speech-to-text becomes a global setting ---


def _settings_321() -> dict:
    return {
        "debug_mode": False,
        "voice_activation": {
            "enabled": True,
            "mute_toggle_key": "shift+x",
            "mute_toggle_key_codes": [42, 45],
            "energy_threshold": 0.02,
            "stt_provider": "wingman_pro",
            "languages": ["de-DE", "en-US"],
            "whispercpp": {"host": "http://10.0.0.5", "port": 8080, "enable": True},
            "whispercpp_config": {"temperature": 0.0},
            "fasterwhisper": {"model_size": "small", "device": "cuda", "compute_type": "auto"},
            "fasterwhisper_config": {
                "beam_size": 1,
                "best_of": 2,
                "temperature": 0,
                "no_speech_threshold": 0.7,
                "language_detection_threshold": 0.5,
                "multilingual": False,
                "hotwords": ["Quantum"],
                "additional_hotwords": [],
            },
            "parakeet": {
                "run_locally": False,
                "model_variant": "v3",
                "execution_provider": "cuda",
                "host": "http://10.0.0.5",
                "port": 9876,
            },
            "parakeet_config": {"temperature": 0.0, "language": "de"},
        },
    }


def test_settings_split_listening_from_transcribing():
    out = _migration().migrate_settings(_settings_321())

    assert out["voice_activation"] == {
        "enabled": True,
        "mute_toggle_key": "shift+x",
        "mute_toggle_key_codes": [42, 45],
        "sensitivity": 0.3,
    }
    stt = out["stt"]
    assert stt["provider"] == "parakeet"
    assert stt["languages"] == ["de-DE", "en-US"]
    # the engines 3.2.2 no longer ships leave nothing behind, hotwords included;
    # the vocabulary starts clean
    for key in ("whispercpp", "whispercpp_config", "fasterwhisper", "fasterwhisper_config"):
        assert key not in stt
    assert "vocabulary" not in stt
    assert stt["parakeet_config"] == {"temperature": 0.0}
    # a real server address survives, the template's own machine does not
    assert stt["parakeet"]["host"] == "http://10.0.0.5"
    out = _migration().migrate_settings(
        {"voice_activation": {"enabled": True, "parakeet": {"host": "http://127.0.0.1", "port": 9876}}}
    )
    assert out["stt"]["parakeet"]["host"] == ""


def test_energy_threshold_becomes_sensitivity():
    m = _migration()
    for threshold, expected in ((0.001, 0.8), (0.01, 0.5), (0.05, 0.3)):
        settings = _settings_321()
        settings["voice_activation"]["energy_threshold"] = threshold
        out = m.migrate_settings(settings)
        assert out["voice_activation"]["sensitivity"] == expected
        assert "energy_threshold" not in out["voice_activation"]


def test_everyone_lands_on_local_parakeet():
    out = _migration().migrate_settings(_settings_321())

    assert out["stt"]["provider"] == "parakeet"
    assert out["stt"]["parakeet"]["run_locally"] is True
    assert out["stt"]["parakeet"]["execution_provider"] == "cuda"


def test_migrated_settings_validate_after_template_backfill():
    """The real chain backfills from the template; what the hook writes has to
    fit the 3.2.2 schema after that."""
    shipped = template("settings.yaml")
    out = _migration().migrate_settings(_settings_321())

    merged = dict(shipped)
    merged["stt"] = {**shipped["stt"], **out["stt"]}
    merged["voice_activation"] = {**shipped["voice_activation"], **out["voice_activation"]}
    settings = SettingsConfig(**merged)
    assert settings.stt.provider.value == "parakeet"
    assert settings.voice_activation.enabled is True


def test_wingman_files_lose_every_stt_key():
    old = {
        "name": "Computer",
        "features": {"tts_provider": "pocket_tts", "stt_provider": "groq"},
        "parakeet": {"temperature": 0.0},
        "fasterwhisper": {"additional_hotwords": ["Aurora"]},
        "whispercpp": {"temperature": 0.2},
        "wingman_pro": {
            "stt_provider": "cloud",
            "tts_provider": "inworld",
            "languages": ["en-US"],
            "conversation_deployment": "",
        },
    }
    out = _migration().migrate_wingman(old)

    assert "stt_provider" not in out["features"]
    assert out["features"]["tts_provider"] == "pocket_tts"
    for key in ("parakeet", "fasterwhisper", "whispercpp"):
        assert key not in out
    assert out["wingman_pro"] == {"tts_provider": "inworld", "conversation_deployment": ""}


def test_defaults_lose_the_same_keys_and_stay_loadable():
    current = template("defaults.yaml")
    old = deepcopy(current)
    old["features"] = {**current["features"], "stt_provider": "parakeet"}
    old["parakeet"] = {"temperature": 0.0}
    old["wingman_pro"] = {**current["wingman_pro"], "stt_provider": "cloud", "languages": ["en-US"]}

    out = _migration().migrate_defaults(old)

    assert "stt_provider" not in out["features"]
    assert "parakeet" not in out
    assert "languages" not in out["wingman_pro"]
    # the chain backfills the Inworld prompt this migration drops on purpose
    NestedConfig(**{**out, "inworld": current["inworld"]})


def test_the_old_default_support_model_moves_to_the_4b():
    out = _migration().migrate_settings({"llama_cpp": {"mode": "local", "support_model": "Qwen3.5-2B-Q4_K_M.gguf"}})
    assert out["llama_cpp"]["support_model"] == "Qwen3.5-4B-Q4_K_M.gguf"


def test_a_support_model_the_user_picked_stays():
    out = _migration().migrate_settings({"llama_cpp": {"mode": "local", "support_model": "gemma-4-E2B-it-Q3_K_M.gguf"}})
    assert out["llama_cpp"]["support_model"] == "gemma-4-E2B-it-Q3_K_M.gguf"


def test_a_pinned_chat_model_is_unpinned_to_the_plan_default():
    out = _migration()._migrate_wingman_config(
        {"wingman_pro": {"conversation_deployment": "google/gemini-2.5-flash", "tts_provider": "wingman_pro"}}, "Computer")
    assert out["wingman_pro"]["conversation_deployment"] == ""
    assert out["wingman_pro"]["tts_provider"] == "wingman_pro"


def test_an_already_empty_chat_model_is_left_alone():
    out = _migration()._migrate_wingman_config({"wingman_pro": {"conversation_deployment": ""}}, "Computer")
    assert out["wingman_pro"]["conversation_deployment"] == ""


def test_a_config_without_a_wingman_pro_block_is_fine():
    out = _migration()._migrate_wingman_config({"name": "Computer"}, "Computer")
    assert out["name"] == "Computer"

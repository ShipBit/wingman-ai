"""The skill facade (`self.wingman` in a skill): audio devices, the voice,
command categories and the HUD connection."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import yaml

from api.enums import TtsProvider, WingmanProTtsProvider
from api.interface import AudioDeviceSettings, AudioSettings, CommandCategoryConfig
from wingmen import facade


def _run(coro):
    return asyncio.run(coro)


def test_switching_the_output_keeps_the_input():
    service = MagicMock()
    service._get_audio_settings_indexed.return_value = AudioSettings(input=3, output=5)
    service.set_audio_devices = AsyncMock()
    audio = facade.SkillAudio(SimpleNamespace(settings_service=service))

    assert _run(audio.set_output_device(7))
    service.set_audio_devices.assert_awaited_once_with(input_device=3, output_device=7)


def test_switching_the_input_keeps_the_output():
    service = MagicMock()
    service._get_audio_settings_indexed.return_value = AudioSettings(input=3, output=5)
    service.set_audio_devices = AsyncMock()
    audio = facade.SkillAudio(SimpleNamespace(settings_service=service))

    assert _run(audio.set_input_device(None))
    service.set_audio_devices.assert_awaited_once_with(input_device=None, output_device=5)


def test_a_stored_device_resolves_to_its_index(monkeypatch):
    import sounddevice as sd

    devices = [
        {"index": 0, "name": "Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        {"index": 1, "name": "Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setattr(sd, "query_devices", lambda: devices)

    stored = AudioDeviceSettings(name="Speakers", hostapi=0)
    assert facade._device_index(stored, "output") == 1
    assert facade._device_index(stored, "input") is None
    assert facade._device_index(AudioDeviceSettings(name="Gone", hostapi=0), "output") is None
    assert facade._device_index(4, "output") == 4
    assert facade._device_index(None, "output") is None


def _subscription_config(subprovider):
    return SimpleNamespace(
        features=SimpleNamespace(tts_provider=TtsProvider.WINGMAN_PRO),
        wingman_pro=SimpleNamespace(
            tts_provider=subprovider,
            azure=SimpleNamespace(voice="en-US-AndrewMultilingualNeural", output_streaming=True),
        ),
        inworld=SimpleNamespace(voice_id="Ashley", output_streaming=True),
    )


def test_the_subscription_voice_follows_its_voice_provider():
    inworld = _subscription_config(WingmanProTtsProvider.INWORLD)
    azure = _subscription_config(WingmanProTtsProvider.AZURE)

    assert facade.SkillTts(SimpleNamespace(config=inworld)).voice == "Ashley"
    assert facade.SkillTts(SimpleNamespace(config=azure)).voice == "en-US-AndrewMultilingualNeural"


def test_a_voice_is_applied_to_the_subscriptions_voice_provider():
    azure = _subscription_config(WingmanProTtsProvider.AZURE)
    assert facade.apply_voice_to_current_provider(azure, "de-DE-KatjaNeural") == (
        "de-DE-KatjaNeural", "Wingman Pro / Azure TTS"
    )
    assert azure.wingman_pro.azure.voice == "de-DE-KatjaNeural"
    assert azure.inworld.voice_id == "Ashley"

    inworld = _subscription_config(WingmanProTtsProvider.INWORLD)
    facade.apply_voice_to_current_provider(inworld, "Edward")
    assert inworld.inworld.voice_id == "Edward"
    assert inworld.inworld.output_streaming is False


def _pocket_wingman(voice_ids):
    pocket = SimpleNamespace(
        get_available_voices=AsyncMock(
            return_value=[SimpleNamespace(id=v) for v in voice_ids]
        )
    )
    return SimpleNamespace(
        config=SimpleNamespace(
            features=SimpleNamespace(tts_provider=TtsProvider.POCKET_TTS),
            pocket_tts=SimpleNamespace(voice="alba"),
        ),
        tts=SimpleNamespace(),
        _shared_providers={"pocket_tts": pocket},
    )


def test_a_pocket_tts_voice_without_its_file_is_missing():
    tts = facade.SkillTts(_pocket_wingman(["alba", "moxxi1"]))

    assert [v.id for v in _run(tts.voices())] == ["alba", "moxxi1"]
    assert _run(tts.missing_voices(["alba", "moxxi", "moxxi1"])) == ["moxxi"]


def test_a_missing_voice_is_not_set():
    wingman = _pocket_wingman(["alba"])

    result = _run(facade.SkillTts(wingman).set_voice("Fabieng"))

    assert "Fabieng" in result
    assert wingman.config.pocket_tts.voice == "alba"


def test_other_providers_have_no_missing_voices():
    tts = facade.SkillTts(SimpleNamespace(config=_subscription_config(WingmanProTtsProvider.INWORLD)))
    assert _run(tts.missing_voices(["Fabieng"])) == []


def test_categories_are_saved_with_the_commands(tmp_path, monkeypatch):
    from services.config_manager import ConfigManager

    manager = ConfigManager.__new__(ConfigManager)
    manager.config_dir = str(tmp_path)
    (tmp_path / "cfg").mkdir()
    path = tmp_path / "cfg" / "Bob.yaml"
    path.write_text(yaml.safe_dump({"name": "Bob"}))
    monkeypatch.setattr(manager, "read_default_config", lambda: {"commands": []}, raising=False)
    monkeypatch.setattr(
        manager, "write_config",
        lambda p, data: path.write_text(yaml.safe_dump(data)) or True, raising=False,
    )

    category = CommandCategoryConfig(id="c1", name="Learned")
    manager.save_wingman_commands(
        config_dir=SimpleNamespace(directory="cfg"),
        wingman_file=SimpleNamespace(file="Bob.yaml"),
        commands=[],
        command_categories=[category],
    )
    saved = yaml.safe_load(path.read_text())
    assert saved["command_categories"] == [{"id": "c1", "name": "Learned"}]

    # None leaves what the file has alone.
    manager.save_wingman_commands(
        config_dir=SimpleNamespace(directory="cfg"),
        wingman_file=SimpleNamespace(file="Bob.yaml"),
        commands=[],
    )
    assert yaml.safe_load(path.read_text())["command_categories"] == [{"id": "c1", "name": "Learned"}]


def test_a_lost_hud_group_is_made_again_and_the_call_repeated(monkeypatch):
    facade._hud_groups.clear()
    client = MagicMock()
    client.base_url = "http://hud"
    client.add_item = AsyncMock(side_effect=[None, {"ok": True}])
    hud = facade.SkillHud(SimpleNamespace(name="Bob"))
    made = []

    async def fake_client(element):
        made.append(element)
        return client

    monkeypatch.setattr(hud, "_client", fake_client)
    assert _run(hud.add_info("Fuel", "low"))
    assert len(made) == 2
    assert client.add_item.await_count == 2

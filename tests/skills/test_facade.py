"""The skill facade (`self.wingman` in a skill): audio devices, the voice,
command categories, the HUD connection and the Star Citizen folder."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
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


def test_a_pocket_tts_voice_cloned_only_for_another_model_is_missing():
    from api.enums import VoiceCloneState

    wingman = _pocket_wingman([])
    wingman._shared_providers["pocket_tts"].get_available_voices = AsyncMock(
        return_value=[
            SimpleNamespace(id="alba", clone_state=None),
            SimpleNamespace(id="sean_murray", clone_state=VoiceCloneState.MISSING),
            SimpleNamespace(id="moxxi", clone_state=VoiceCloneState.OUTDATED),
        ]
    )

    assert _run(facade.SkillTts(wingman).missing_voices(["alba", "sean_murray", "moxxi"])) == [
        "sean_murray"
    ]


def test_a_missing_voice_is_not_set():
    wingman = _pocket_wingman(["alba"])

    result = _run(facade.SkillTts(wingman).set_voice("Fabieng"))

    assert "Fabieng" in result
    assert wingman.config.pocket_tts.voice == "alba"


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


def _hud(monkeypatch, *, chat=True, info=True, skill=None):
    """A SkillHud for "Bob" (and `skill`) over a fake HUD service that runs."""
    from services.hud_service import HudService

    service = MagicMock(available=True)
    monkeypatch.setattr(HudService, "_instance", service)
    wingman = SimpleNamespace(
        name="Bob", config=SimpleNamespace(hud=SimpleNamespace(chat=chat, info=info)),
        get_avatar_path=lambda: None,
    )
    return facade.SkillHud(wingman, skill), service


def test_info_goes_to_the_shared_panel_with_who_added_it(monkeypatch):
    from hud_server.constants import GROUP_INFO

    hud, service = _hud(monkeypatch, skill="Star Citizen Events")

    assert _run(hud.add_info("Fuel", "low"))
    service.add_info.assert_called_once_with(
        GROUP_INFO, "Fuel", "low", color=None, duration=None,
        added_by="the Star Citizen Events skill of Bob",
    )


def test_a_wingman_with_its_info_switch_off_does_not_write_to_the_panel(monkeypatch):
    hud, service = _hud(monkeypatch, info=False)

    assert not _run(hud.add_info("Fuel", "low"))
    service.add_info.assert_not_called()


def test_a_skills_own_group_is_named_after_the_wingman_and_goes_with_the_skill(monkeypatch):
    hud, service = _hud(monkeypatch)

    group = hud.group("mic", anchor="top_right", width=72)
    _run(group.add_info(" ", "![](mic.png)"))
    hud._release()

    service.create_group.assert_called_with("Bob_mic", "persistent", {"anchor": "top_right", "width": 72})
    service.delete_group.assert_called_once_with("Bob_mic", "persistent")


def _star_citizen(game_path: str):
    settings = SimpleNamespace(star_citizen=SimpleNamespace(plays=True, game_path=game_path))
    return facade.SkillStarCitizen(SimpleNamespace(settings=settings))


def test_a_tool_shows_the_logo_of_a_skill_loaded_from_its_file(tmp_path):
    # As custom skills (and every skill in the release) are loaded: from the
    # file, without being registered as a module
    import importlib.util

    from PIL import Image

    folder = tmp_path / "uexcorp_beta"
    folder.mkdir()
    (folder / "main.py").write_text("class UEXCorpBeta:\n    def lookup(self):\n        return 1\n")
    Image.new("RGB", (8, 8)).save(folder / "logo.png")
    spec = importlib.util.spec_from_file_location("UEXCorpBeta", folder / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    wingman = SimpleNamespace(tool_skills={"uex_lookup": module.UEXCorpBeta()})

    assert facade.SkillTools(wingman).icon("uex_lookup") == str(folder / "logo.png")


def test_star_citizen_gives_skills_the_environment_folder(tmp_path):
    (tmp_path / "LIVE").mkdir()
    star_citizen = _star_citizen(str(tmp_path))
    assert star_citizen.found and star_citizen.environments == ("LIVE",)
    assert star_citizen.environment_path("live") == tmp_path / "LIVE"
    assert star_citizen.environment_path("PTU") is None


def test_star_citizen_is_read_only_for_skills():
    try:
        _star_citizen("").game_path = "C:\\elsewhere"
    except facade.FacadeError:
        return
    raise AssertionError("a skill could move the game folder")


def test_the_history_gives_skills_dicts_also_for_the_models_answers():
    from openai.types.chat import ChatCompletionMessage

    answer = ChatCompletionMessage(role="assistant", content="Timer set.")
    wingman = SimpleNamespace(
        conversation=SimpleNamespace(messages=[{"role": "user", "content": "Set a timer"}, answer])
    )

    history = facade.SkillConversation(wingman).history()

    assert [m.get("role") for m in history] == ["user", "assistant"]
    assert history[1]["content"] == "Timer set."


def test_a_spelling_a_skill_adds_is_shown_to_the_user(monkeypatch):
    from services.printr import Printr

    shown = []
    monkeypatch.setattr(Printr, "print", lambda self, text, **kw: shown.append((text, kw.get("source_name"))))
    vocabulary = []

    def add(entries):
        new = [e for e in entries if e not in vocabulary]
        vocabulary.extend(new)
        return new

    wingman = SimpleNamespace(name="Bob", settings_service=SimpleNamespace(add_vocabulary=add))
    stt = facade.SkillStt(wingman)

    assert stt.remember_spelling("Hurston", heard="Houston")
    assert not stt.remember_spelling("Hurston", heard="Houston")

    assert len(shown) == 1
    text, source = shown[0]
    assert "Houston" in text and "Hurston" in text and source == "Bob"


def test_the_clipboard_facade_goes_through_the_service(monkeypatch):
    from services import clipboard as service

    held = {"text": "hello"}
    monkeypatch.setattr(service, "read_text", lambda: held["text"])
    monkeypatch.setattr(service, "write_text", lambda text: held.__setitem__("text", text))
    board = facade.SkillClipboard()

    assert _run(board.read()) == "hello"
    _run(board.write("Coordinates: x:1 y:2 z:3"))
    assert held["text"] == "Coordinates: x:1 y:2 z:3"


def test_the_linux_clipboard_prefers_wayland_tools(monkeypatch):
    from services import clipboard as service

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/" + name)
    assert service._linux_tool(read=True) == ["wl-paste", "--no-newline"]
    assert service._linux_tool(read=False) == ["wl-copy"]

    monkeypatch.delenv("WAYLAND_DISPLAY")
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    with pytest.raises(service.ClipboardError):
        service._linux_tool(read=True)


def test_a_line_said_by_a_character_is_shown_under_their_name_and_noted(monkeypatch):
    from api.enums import LogSource, LogType
    from services.conversation_manager import NOTE_PREFIX
    from services.printr import Printr

    printed = []

    async def print_async(text, **kwargs):
        printed.append((text, kwargs))

    # The singleton instance, not the class: an earlier test may have put a
    # print_async on the instance, which would shadow a class patch.
    monkeypatch.setattr(Printr(), "print_async", print_async)
    wingman = SimpleNamespace(name="Computer", conversation=SimpleNamespace(messages=[]), _takeover=None)
    conversation = facade.SkillConversation(wingman)

    _run(conversation.said_by("Lena Varga", "Then we can talk.", skill_name="Star Citizen NPCs"))

    text, kwargs = printed[0]
    assert text == "Then we can talk."
    assert kwargs["color"] == LogType.CHARACTER and kwargs["source"] == LogSource.WINGMAN
    assert kwargs["source_name"] == "Lena Varga" and kwargs["wingman_name"] == "Computer"
    assert wingman.conversation.messages == [
        {"role": "user", "content": f'{NOTE_PREFIX}Lena Varga said: "Then we can talk."]'}
    ]


def test_a_registered_speaker_is_gone_after_unsubscribing():
    from wingmen.wingman import Wingman

    wingman = SimpleNamespace(_speakers={}, _speaker_descriptions={}, _takeover=None)
    wingman.register_speaker = Wingman.register_speaker.__get__(wingman)
    wingman.unregister_speaker = Wingman.unregister_speaker.__get__(wingman)
    conversation = facade.SkillConversation(wingman)

    async def opener(name, text):
        return True

    subscription = conversation.register_speaker("Lena", opener, description="the trader")
    assert wingman._speakers == {"Lena": opener} and conversation.takeover is None
    assert wingman._speaker_descriptions == {"Lena": "the trader"}

    subscription.unsubscribe()
    assert wingman._speakers == {} and wingman._speaker_descriptions == {}

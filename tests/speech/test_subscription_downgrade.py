"""A plan without Inworld (Free): at sign-in, Wingmen set to the subscription's
Inworld move to its Azure voices, with a voice of the same gender. Never back."""

import asyncio
from os import path
from types import SimpleNamespace

import yaml

from api.interface import SubscriptionTtsModel, SubscriptionTtsModels
from services.wingman_default_voices import (
    AZURE_FEMALE_VOICE,
    AZURE_MALE_VOICE,
    downgrade_config_to_azure,
    downgrade_inworld_to_azure,
)
from tests.support import FakeConfigManager

DEFAULTS = {
    "features": {"tts_provider": "pocket_tts"},
    "inworld": {"voice_id": "Deborah"},
    "wingman_pro": {"tts_provider": "inworld",
                    "azure": {"voice": AZURE_FEMALE_VOICE, "output_streaming": True}},
}


class DowngradeConfigManager(FakeConfigManager):
    def __init__(self, root, defaults):
        super().__init__(root)
        self.default_config_path = path.join(self.config_dir, "defaults.yaml")
        self.write_config(self.default_config_path, defaults)
        self.default_config = None

    def load_defaults_config(self, silent_on_error=False):
        return "reloaded"


def write(folder, name, content):
    (folder / f"{name}.yaml").write_text(yaml.safe_dump(content))


def read(folder, name):
    return yaml.safe_load((folder / f"{name}.yaml").read_text())


def test_one_config_moves_with_its_gender():
    atc = {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"}}
    assert downgrade_config_to_azure(atc, DEFAULTS)
    assert atc["wingman_pro"] == {"tts_provider": "azure", "azure": {"voice": AZURE_MALE_VOICE}}


def test_a_voice_the_user_picked_stays_and_other_providers_are_untouched():
    katja = {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"},
             "wingman_pro": {"tts_provider": "inworld", "azure": {"voice": "de-DE-KatjaNeural"}}}
    edge = {"features": {"tts_provider": "edge_tts"}}
    azure = {"features": {"tts_provider": "wingman_pro"}, "wingman_pro": {"tts_provider": "azure"}}

    assert downgrade_config_to_azure(katja, DEFAULTS)
    assert katja["wingman_pro"]["azure"]["voice"] == "de-DE-KatjaNeural"
    assert not downgrade_config_to_azure(edge, DEFAULTS)
    assert not downgrade_config_to_azure(azure, DEFAULTS)


def test_all_configs_on_disk(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    write(folder, "ATC", {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"}})
    write(folder, "Computer", {"inworld": {"voice_id": "Olivia"}})  # Pocket TTS from the defaults
    cm = DowngradeConfigManager(tmp_path, DEFAULTS)

    changed = downgrade_inworld_to_azure(cm)

    assert changed == ["Star Citizen/ATC"]
    assert read(folder, "ATC")["wingman_pro"]["tts_provider"] == "azure"
    assert "wingman_pro" not in read(folder, "Computer")
    # The defaults do not speak through the subscription, so they stay.
    assert yaml.safe_load(open(cm.default_config_path))["wingman_pro"]["tts_provider"] == "inworld"


def test_defaults_on_the_subscription_move_too(tmp_path):
    (tmp_path / "configs").mkdir()
    defaults = {**DEFAULTS, "features": {"tts_provider": "wingman_pro"}}
    cm = DowngradeConfigManager(tmp_path, defaults)

    assert downgrade_inworld_to_azure(cm) == ["defaults"]
    assert yaml.safe_load(open(cm.default_config_path))["wingman_pro"]["tts_provider"] == "azure"
    assert cm.default_config == "reloaded"


def _handler(models, cm):
    from services.command_handler import CommandHandler

    lines = []

    async def get_models():
        return models

    async def print_async(text, **kwargs):
        lines.append(text)

    handler = CommandHandler.__new__(CommandHandler)
    handler.source_name = "test"
    handler.core = SimpleNamespace(get_wingman_tts_models=get_models, config_manager=cm)
    handler.printr = SimpleNamespace(print_async=print_async)
    return handler, lines


def _models(inworld_available):
    return SubscriptionTtsModels(default="azure-neural", models=[
        SubscriptionTtsModel(id="azure-neural", name="Azure", provider="azure", available=True, usage_factor=3),
        SubscriptionTtsModel(id="inworld-tts-2-flash", name="Inworld", provider="inworld",
                             available=inworld_available, usage_factor=1),
    ])


def test_sign_in_rewrites_only_for_a_plan_without_inworld(tmp_path):
    folder = tmp_path / "configs" / "Star Citizen"
    folder.mkdir(parents=True)
    write(folder, "ATC", {"features": {"tts_provider": "wingman_pro"}, "inworld": {"voice_id": "Clive"}})
    cm = DowngradeConfigManager(tmp_path, DEFAULTS)

    pro, pro_lines = _handler(_models(True), cm)
    unknown, _ = _handler(SubscriptionTtsModels(), cm)  # the backend did not answer
    assert asyncio.run(pro._downgrade_subscription_tts()) is False
    assert asyncio.run(unknown._downgrade_subscription_tts()) is False
    assert read(folder, "ATC").get("wingman_pro") is None and pro_lines == []

    free, free_lines = _handler(_models(False), cm)
    assert asyncio.run(free._downgrade_subscription_tts()) is True
    assert read(folder, "ATC")["wingman_pro"]["tts_provider"] == "azure"
    assert len(free_lines) == 1 and "Star Citizen/ATC" in free_lines[0]


def test_a_voice_of_a_main_market_keeps_its_language():
    from services.wingman_default_voices import azure_voice_for_inworld

    assert azure_voice_for_inworld("Johanna") == "de-DE-KatjaNeural"
    assert azure_voice_for_inworld("Matthias") == "de-DE-ConradNeural"
    assert azure_voice_for_inworld("Hélène") == "fr-FR-DeniseNeural"
    assert azure_voice_for_inworld("Alain") == "fr-FR-HenriNeural"
    assert azure_voice_for_inworld("Mercedes") == "es-ES-ElviraNeural"
    assert azure_voice_for_inworld("Alvaro") == "es-ES-AlvaroNeural"
    # English and unknown names: the multilingual pair, by gender.
    assert azure_voice_for_inworld("Clive") == "en-US-AndrewMultilingualNeural"
    assert azure_voice_for_inworld("Nobody") == "en-US-JennyMultilingualNeural"

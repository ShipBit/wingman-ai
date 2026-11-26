"""Audio devices come in as an index or as the name + host API the settings
store. The settings form sends back what it read, so after one device was
picked the other side arrives in the stored form."""

import asyncio
from types import SimpleNamespace

import pytest
import sounddevice as sd

from api.interface import AudioDeviceSettings, AudioSettings
from services import settings_service
from services.settings_service import SettingsService, device_index

DEVICES = [
    {"index": 0, "name": "Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
    {"index": 1, "name": "Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
]


@pytest.fixture(autouse=True)
def _devices(monkeypatch):
    def query_devices(device=None):
        return DEVICES if device is None else DEVICES[device]

    monkeypatch.setattr(sd, "query_devices", query_devices)
    monkeypatch.setattr(settings_service.sd, "query_devices", query_devices)


def test_a_stored_device_resolves_to_its_index():
    stored = AudioDeviceSettings(name="Speakers", hostapi=0)
    assert device_index(stored, "output") == 1
    assert device_index(stored, "input") is None
    assert device_index(AudioDeviceSettings(name="Gone", hostapi=0), "output") is None
    assert device_index(4, "output") == 4
    assert device_index(None, "output") is None


def test_a_stored_device_next_to_a_picked_one_is_saved():
    published = []

    async def publish(event, data):
        published.append((event, data))

    service = SettingsService.__new__(SettingsService)
    service.config_manager = SimpleNamespace(settings_config=SimpleNamespace(audio=None))
    service.settings_events = SimpleNamespace(publish=publish)
    service.printr = SimpleNamespace(print=lambda *a, **kw: None)

    asyncio.run(
        service.set_audio_devices(0, AudioDeviceSettings(name="Speakers", hostapi=0))
    )

    assert service.config_manager.settings_config.audio == AudioSettings(
        input=AudioDeviceSettings(name="Mic", hostapi=0),
        output=AudioDeviceSettings(name="Speakers", hostapi=0),
    )
    assert published == [("audio_devices_changed", (0, 1))]

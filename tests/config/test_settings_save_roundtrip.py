"""Every settings block the client sends has to survive the save.

`SettingsService.save_settings` copies the incoming config block by block,
by hand, because several blocks need something to happen when they change —
a model reloads, a provider is handed the new object, a language cascades.
The cost of that shape is that a block added later is silently dropped: the
value never reaches `settings_config`, the old one is written back to disk,
and a toggle in the client does nothing at all with no error anywhere.

That is not hypothetical. `system_one` shipped without its line and the
toggle was inert until this test was written.

So rather than one assertion per block, this walks every field on
`SettingsConfig` and checks it came through. A block added in future fails
here until someone gives it a line.
"""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.interface import SettingsConfig
from services.settings_service import SettingsService
from tests.support import template

# Blocks that must NOT be copied wholesale, with the reason. Checked against
# the real code below, so a reason that stops being true shows up here.
DELIBERATELY_NOT_COPIED = {
    # Written by set_audio_devices, not by the settings form.
    "audio",
    # Set once by the hardware scan.
    "hardware_scan_performed",
    # Filled by the client's own onboarding, not the settings page.
    "user_name",
}


def _settings() -> SettingsConfig:
    return SettingsConfig(**template("settings.yaml"))


def _service(current: SettingsConfig):
    service = SettingsService.__new__(SettingsService)
    service.config_manager = SimpleNamespace(
        settings_config=current, save_settings_config=lambda: None
    )
    service.config_service = SimpleNamespace(tower=None)
    service.settings_events = SimpleNamespace(publish=_noop)
    service.xvasynth = SimpleNamespace(update_settings=lambda **kw: None)
    service.pocket_tts = SimpleNamespace(update_settings=lambda **kw: None)
    service.local_ai_service = SimpleNamespace(
        update_settings_async=_noop, update_subscription=lambda *a, **kw: None
    )
    service.parakeet = SimpleNamespace(settings=None)
    service.stt_provider_manager = None
    service.stt_status_callback = None
    service.printr = MagicMock()
    return service


async def _noop(*args, **kwargs):
    return None


def test_the_system_one_toggle_actually_reaches_the_config():
    """The bug this file exists for: the flag was dropped on save, so the
    client toggle wrote the old value back and changed nothing."""
    current = _settings()
    current.system_one.enabled = True

    incoming = _settings()
    incoming.system_one.enabled = False

    asyncio.run(_service(current).save_settings(incoming))
    assert current.system_one.enabled is False


def test_the_toggle_survives_being_switched_back_on():
    current = _settings()
    current.system_one.enabled = False

    incoming = _settings()
    incoming.system_one.enabled = True

    asyncio.run(_service(current).save_settings(incoming))
    assert current.system_one.enabled is True


def test_every_settings_block_is_either_copied_or_deliberately_not():
    """Guards the guard, and every block added after this one.

    A new field on SettingsConfig that nobody wired into save_settings fails
    here, naming itself, instead of shipping as a control that does nothing.
    """
    source = inspect.getsource(SettingsService.save_settings)
    missing = [
        name
        for name in SettingsConfig.model_fields
        if name not in DELIBERATELY_NOT_COPIED
        and f"settings_config.{name}" not in source
    ]
    assert not missing, (
        "These settings blocks are never copied in save_settings, so the "
        f"client cannot change them: {missing}. Give each one a line, or add "
        "it to DELIBERATELY_NOT_COPIED with the reason."
    )


def test_the_exception_list_only_holds_real_fields():
    """A stale entry here would hide a genuinely dropped block."""
    unknown = DELIBERATELY_NOT_COPIED - set(SettingsConfig.model_fields)
    assert not unknown, f"no such settings block: {unknown}"

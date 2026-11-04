"""A skill setting for some systems only, like Vision AI's DXCam capture on
Windows: Core drops it from the manifest elsewhere, so the UI never shows it."""

import services.platform_utils as platform_utils
from services.platform_utils import drop_other_platform_properties


def _manifest():
    return {
        "name": "Vision",
        "custom_properties": [
            {"id": "display", "value": 1},
            {"id": "use_dxcam", "value": False, "platforms": ["windows"]},
        ],
    }


def _ids(manifest):
    return [prop["id"] for prop in manifest["custom_properties"]]


def test_a_windows_setting_is_offered_on_windows(monkeypatch):
    monkeypatch.setattr(platform_utils.sys, "platform", "win32")

    assert _ids(drop_other_platform_properties(_manifest())) == ["display", "use_dxcam"]


def test_a_windows_setting_is_dropped_on_macos(monkeypatch):
    monkeypatch.setattr(platform_utils.sys, "platform", "darwin")

    assert _ids(drop_other_platform_properties(_manifest())) == ["display"]

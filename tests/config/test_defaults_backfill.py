"""A defaults.yaml already on the current version but older than a new
required field (wingman_pro.azure in 3.2.6) gets it from the template on load.
The migration chain does not run then, so nothing else would add it."""

from os import path
from types import SimpleNamespace

from api.interface import NestedConfig
from services.config_manager import ConfigManager
from tests.support import REPO_ROOT, read_yaml, template, write_yaml


def manager(tmp_path, lines):
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config_path = str(tmp_path / "defaults.yaml")
    cm.templates_dir = path.join(REPO_ROOT, "templates")
    cm.log_source_name = "test"
    cm.printr = SimpleNamespace(print=lambda text, **kw: lines.append((text, kw.get("server_only"))))
    return cm


def test_a_missing_section_comes_from_the_template_and_user_values_stay(tmp_path):
    defaults = template("defaults.yaml")
    del defaults["wingman_pro"]["azure"]
    defaults["wingman_pro"]["tts_provider"] = "azure"
    defaults["inworld"]["voice_id"] = "Clive"
    write_yaml(str(tmp_path / "defaults.yaml"), defaults)
    lines = []

    config = manager(tmp_path, lines).read_default_config()

    loaded = NestedConfig(**config)
    assert loaded.wingman_pro.azure.voice == "en-US-JennyMultilingualNeural"
    assert loaded.wingman_pro.tts_provider.value == "azure"
    assert loaded.inworld.voice_id == "Clive"
    assert lines == [("defaults: added missing 'wingman_pro.azure' from the template", True)]
    # Written back, so the next start has nothing to fill.
    assert "azure" in read_yaml(str(tmp_path / "defaults.yaml"))["wingman_pro"]


def test_a_complete_defaults_file_is_left_alone(tmp_path):
    write_yaml(str(tmp_path / "defaults.yaml"), template("defaults.yaml"))
    lines = []

    manager(tmp_path, lines).read_default_config()

    assert lines == []

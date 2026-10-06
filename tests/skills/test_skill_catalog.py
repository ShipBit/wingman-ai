"""The catalog decides which skill folders are allowed to load.

Before anything is instantiated, every skill manifest is read once and gets a
verdict. A v3 skill for this platform is eligible. A skill from before v3 or
with a broken manifest is not, and the verdict says why, because the Wingman
configs auto-disable exactly those skills. A skill that crashes later at
runtime is reported once, not on every Wingman.

The folders are tiny fakes in tmp_path. The import probe is replaced, so no
skill code is imported.
"""

import pytest

from services import module_manager
from services.module_manager import ModuleManager
from services.platform_utils import normalize_platform
from services.skill_catalog import SkillCatalog, SkillVerdict
from tests.support import write_yaml


def manifest(name, **overrides):
    content = {
        "module": f"skills.{name.lower()}.main",
        "name": name,
        "api_version": 3,
        "display_name": name,
        "description": {"en": "A fake skill."},
    }
    content.update(overrides)
    return {k: v for k, v in content.items() if v is not None}


@pytest.fixture
def skills_root(tmp_path, monkeypatch):
    """Empty bundled and custom skill folders, the only ones the scan sees."""
    bundled = tmp_path / "bundled"
    custom = tmp_path / "custom"
    bundled.mkdir()
    custom.mkdir()
    monkeypatch.setattr(module_manager, "get_bundled_skills_dir", lambda: str(bundled))
    monkeypatch.setattr(module_manager, "get_custom_skills_dir", lambda: str(custom))
    monkeypatch.setattr(module_manager, "SKILLS_DIR", str(bundled))
    monkeypatch.setattr(
        ModuleManager, "_get_untracked_skill_folders", staticmethod(lambda _d: set())
    )
    monkeypatch.setattr(ModuleManager, "probe_import", staticmethod(lambda _c: None))
    monkeypatch.setattr(SkillCatalog, "_instance", None)
    return bundled, custom


def add_skill(folder_root, folder, content):
    skill_dir = folder_root / folder
    skill_dir.mkdir()
    if content is not None:
        write_yaml(str(skill_dir / "default_config.yaml"), content)


def scan():
    catalog = SkillCatalog()
    catalog.scan()
    return catalog


# ── eligible ───────────────────────────────────────────────────────────


def test_a_v3_skill_is_eligible(skills_root):
    bundled, _ = skills_root
    add_skill(bundled, "good", manifest("Good"))

    catalog = scan()

    assert catalog.is_eligible("good")
    assert catalog.entry_for_folder("good").verdict == SkillVerdict.OK
    assert catalog.ineligible_folders() == set()


def test_a_skill_for_another_platform_stays_eligible_without_an_import_probe(
    skills_root, monkeypatch
):
    bundled, _ = skills_root
    other = "linux" if normalize_platform() != "linux" else "windows"
    add_skill(bundled, "elsewhere", manifest("Elsewhere", platforms=[other]))

    def must_not_probe(_config):
        raise AssertionError("the probe must not run for another platform")

    monkeypatch.setattr(ModuleManager, "probe_import", staticmethod(must_not_probe))

    catalog = scan()

    assert catalog.is_eligible("elsewhere")


# ── not eligible ───────────────────────────────────────────────────────


def test_a_skill_without_api_version_is_legacy(skills_root):
    bundled, _ = skills_root
    add_skill(bundled, "old", manifest("Old", api_version=None))

    catalog = scan()

    entry = catalog.entry_for_folder("old")
    assert entry.verdict == SkillVerdict.LEGACY
    assert entry.outcome == "legacy_v2"
    assert not catalog.is_eligible("old")


def test_an_unsupported_api_version_is_legacy_and_says_which(skills_root):
    bundled, _ = skills_root
    add_skill(bundled, "v2", manifest("Two", api_version=2))

    entry = scan().entry_for_folder("v2")

    assert entry.verdict == SkillVerdict.LEGACY
    assert entry.api_version == 2
    assert "2" in entry.reason


def test_a_manifest_missing_required_fields_is_invalid(skills_root):
    bundled, _ = skills_root
    add_skill(bundled, "broken", {"name": "Broken", "api_version": 3})

    entry = scan().entry_for_folder("broken")

    assert entry.verdict == SkillVerdict.INVALID
    assert entry.outcome == "quarantined"


def test_an_empty_manifest_is_invalid(skills_root):
    bundled, _ = skills_root
    skill_dir = bundled / "empty"
    skill_dir.mkdir()
    (skill_dir / "default_config.yaml").write_text("")

    entry = scan().entry_for_folder("empty")

    assert entry.verdict == SkillVerdict.INVALID
    assert entry.reason == "manifest unreadable"


def test_a_skill_whose_import_probe_fails_is_invalid(skills_root, monkeypatch):
    bundled, _ = skills_root
    add_skill(bundled, "nomodule", manifest("NoModule"))

    def failing_probe(_config):
        raise ImportError("no module")

    monkeypatch.setattr(ModuleManager, "probe_import", staticmethod(failing_probe))

    entry = scan().entry_for_folder("nomodule")

    assert entry.verdict == SkillVerdict.INVALID
    assert "import probe failed" in entry.reason


def test_a_custom_skill_that_core_took_over_never_loads(skills_root):
    _, custom = skills_root
    add_skill(custom, "sc_log_reader", manifest("ScLogReader"))

    catalog = scan()

    assert not catalog.is_eligible("sc_log_reader")
    assert catalog.entry_for_folder("sc_log_reader").origin == "custom"


# ── what the Wingman configs consume ───────────────────────────────────


def test_ineligible_names_and_folders_list_only_the_skills_that_cannot_load(
    skills_root,
):
    bundled, _ = skills_root
    add_skill(bundled, "good", manifest("Good"))
    add_skill(bundled, "old", manifest("Old", api_version=None))
    add_skill(bundled, "broken", {"api_version": 3})

    catalog = scan()

    assert catalog.eligible_folders() == {"good"}
    assert catalog.ineligible_folders() == {"old", "broken"}
    # The broken manifest has no name, so only the legacy skill is listed.
    assert catalog.ineligible_skill_names() == {"Old"}


# ── runtime failures ───────────────────────────────────────────────────


def test_a_runtime_failure_is_recorded_only_once(skills_root):
    bundled, _ = skills_root
    add_skill(bundled, "good", manifest("Good"))
    catalog = scan()

    first = catalog.record_runtime_failure("good", "boom")
    second = catalog.record_runtime_failure("good", "boom again")

    assert first["outcome"] == "failed"
    assert first["skill"] == "Good"
    assert second is None
    assert len(catalog.drain_runtime_records()) == 1

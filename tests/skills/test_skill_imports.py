"""Bundled skills import only what the v3 facade allows.

A skill reaches Core through `self.wingman`. Imports of Core internals tie it
to code that changes without notice. The allowed set is documented in
skills/AGENTS.md ("Allowed imports"); the exceptions below are bundled skills
that predate a facade capability for what they do. Shrink the list, do not
grow it: a new need belongs on the facade.
"""

import ast
from pathlib import Path

from tests.support import REPO_ROOT

SKILLS = Path(REPO_ROOT) / "skills"

ALLOWED_PREFIXES = (
    "api.",
    "skills.skill_base",
    "services.skill_local_ai",       # SamplingPreset
    "services.benchmark",            # type hint of the legacy execute_tool
    "services.image_generation",     # image helpers next to ai.generate_image
    "wingmen.wingman_context",       # TYPE_CHECKING only
)

EXCEPTIONS = {
    # Core's own HUD clients: the facade's hud has no images, timers, progress.
    "hud": ("hud_server.", "services.file", "services.printr"),
    "mic_status": ("hud_server.",),
    # Prompt file shipped in templates/prompts.
    "radio_chatter": ("services.file",),
    # Maintained by UEX; own data dir, console logging and secret handling.
    "uexcorp": ("services.file", "services.printr", "services.secret_keeper"),
}

CORE_ROOTS = {"api", "services", "wingmen", "providers", "hud_server", "skills"}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno


def _skill_dirs():
    return sorted(
        p for p in SKILLS.iterdir()
        if p.is_dir() and (p / "default_config.yaml").exists()
    )


def test_skills_import_only_the_facade():
    problems = []
    for skill in _skill_dirs():
        allowed = ALLOWED_PREFIXES + (f"skills.{skill.name}",) + EXCEPTIONS.get(skill.name, ())
        for path in skill.rglob("*.py"):
            parts = path.relative_to(skill).parts
            if parts[0] in ("venv", "tests", "__pycache__"):
                continue
            for module, line in _imports(path):
                if module.split(".")[0] not in CORE_ROOTS:
                    continue
                if not any(module == a.rstrip(".") or module.startswith(a.rstrip(".") + ".") or module.startswith(a) for a in allowed):
                    problems.append(f"{path.relative_to(SKILLS.parent)}:{line} imports {module}")
    assert not problems, "Core internals imported by skills:\n" + "\n".join(problems)


def test_every_manifest_declares_the_v3_api():
    import yaml

    for skill in _skill_dirs():
        manifest = yaml.safe_load((skill / "default_config.yaml").read_text(encoding="utf-8"))
        assert manifest.get("api_version") == 3, skill.name
        assert manifest.get("module") == f"skills.{skill.name}.main", skill.name

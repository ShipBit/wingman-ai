"""Recover duplicate configuration directories without discarding user content."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from services.elite_runtime_identity import capture as capture_elite_module

capture_elite_module(__file__)


def config_name(directory):
    return directory.removeprefix(".").removeprefix("_")


def template_copy(directory, templates):
    """Only classify exact template files as disposable copies; unknown files count as edits."""
    candidates = [p for p in templates.iterdir() if p.is_dir()
                  and config_name(p.name).casefold() == config_name(directory.name).casefold()]
    for template in candidates:
        expected = {p.relative_to(template).as_posix().replace(".template.yaml", ".yaml"): p.read_bytes()
                    for p in template.rglob("*") if p.is_file()}
        actual = {p.relative_to(directory).as_posix(): p.read_bytes()
                  for p in directory.rglob("*") if p.is_file()}
        if actual and all(expected.get(name) == data for name, data in actual.items()):
            return True
    return False


def repair_config_directories(configs, templates, preferred_default=None):
    """Back up first, archive exact clones, retain differing copies under unique names.

    Only direct children are renamed. A template underscore must never create a
    second default. Returns the backup path, or None when no repair is needed.
    """
    configs, templates = Path(configs).resolve(), Path(templates).resolve()
    directories = sorted((p for p in configs.iterdir() if p.is_dir()), key=lambda p: p.name.casefold())
    if any(p.is_symlink() or p.resolve().parent != configs for p in directories):
        raise ValueError("Configuration directory links must be resolved before repair")
    groups = {}
    for directory in directories:
        groups.setdefault(config_name(directory.name).casefold(), []).append(directory)
    moves, survivors = [], []
    occupied = {config_name(p.name).casefold() for p in directories}
    for group in groups.values():
        if len(group) == 1:
            survivors.append((group[0], group[0].name))
            continue
        # A deletion marker is an explicit user decision, including when an old
        # startup has recreated an unprefixed template beside it.
        ranked = sorted(group, key=lambda p: (not p.name.startswith("."),
                        template_copy(p, templates), p.name != preferred_default,
                        not p.name.startswith("_"), p.name.casefold()))
        canonical = ranked[0]
        canonical_name = canonical.name
        if not canonical_name.startswith(".") and any(p.name.startswith("_") for p in group):
            canonical_name = "_" + config_name(canonical_name)
        survivors.append((canonical, canonical_name))
        for duplicate in ranked[1:]:
            if template_copy(duplicate, templates):
                moves.append((duplicate, None))  # Archive in the backup, outside configs.
            else:
                base = config_name(duplicate.name) + " Recovered"
                name, index = base, 2
                while name.casefold() in occupied:
                    name, index = f"{base} {index}", index + 1
                occupied.add(name.casefold())
                survivors.append((duplicate, name))
    defaults = [(p, n) for p, n in survivors if n.startswith("_")]
    if len(defaults) > 1:
        selected = next((p for p, n in defaults if n == preferred_default), defaults[0][0])
        survivors = [(p, n.removeprefix("_") if n.startswith("_") and p != selected else n)
                     for p, n in survivors]
    moves += [(p, configs / name) for p, name in survivors if p.name != name]
    if not moves:
        return None
    # Validate all resolved targets before moving any directory.
    sources = {p for p, _ in moves}
    for _, target in moves:
        if target is not None and (target.resolve().parent != configs or (target.exists() and target not in sources)):
            raise ValueError("Configuration repair destination already exists")
    backup = configs.parent / "config-backups" / datetime.now(timezone.utc).strftime("repair-%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copytree(configs, backup / "original")
    manifest = [{"from": p.name, "to": target.name if target else None} for p, target in moves]
    (backup / "repair.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Stage every source outside the live directory first, avoiding rename collisions.
    holding = backup / "archived"
    holding.mkdir()
    staged, completed = [], []
    try:
        for source, target in moves:
            temporary = holding / source.name
            source.rename(temporary)
            staged.append((source, temporary))
        for source, target in moves:
            if target is not None:
                if target.exists():
                    raise ValueError("Configuration changed during repair")
                temporary = holding / source.name
                temporary.rename(target)
                completed.append((target, temporary))
    except Exception:
        for target, temporary in reversed(completed):
            target.rename(temporary)
        for source, temporary in reversed(staged):
            temporary.rename(source)
        raise
    return backup

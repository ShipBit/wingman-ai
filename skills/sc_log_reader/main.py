"""V3 catalog registration. Reader initialization waits for skill construction."""

from skills.skill_base import Skill


class SCLogReader(Skill):
    def __new__(cls, config, settings, wingman):
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent
        dependencies = root / "dependencies"
        if not dependencies.is_dir():
            dependencies = root / "venv" / "Lib" / "site-packages"
        if not dependencies.is_dir():
            raise ImportError("SC Log Reader packaged dependencies are missing")
        for name in ("sc_log_reader", "regex"):
            existing = sys.modules.get(name)
            if existing and not Path(existing.__file__).resolve().is_relative_to(
                dependencies
            ):
                raise ImportError(
                    "SC Log Reader dependency conflicts with an already loaded package: "
                    + name
                )

        # Absolute package paths support delayed imports after the loader removes
        # its temporary path. Catalog import does not load native dependencies.
        sys.path.insert(0, str(dependencies))
        try:
            from sc_log_reader.main import SCLogReader as ReaderSkill

            return ReaderSkill(config=config, settings=settings, wingman=wingman)
        finally:
            sys.path.remove(str(dependencies))


# Saved profiles may still request the pre-release class by name.
# This is the same class, not a second registered skill.
SCLogReader2 = SCLogReader

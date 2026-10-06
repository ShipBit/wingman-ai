"""Elite Dangerous controls: Elite's own key bindings become Wingman commands.

The skill reads the bindings the pilot set up in the game (keyboard only) and
keeps one command per control in the categories "Elite Ship", "Elite SRV" and
"Elite On Foot". Core presses the keys like for any other command, so instant
activation works without the AI, and the AI picks them through execute_command.
When the pilot changes a binding in the game, the commands follow.

The skill owns the keys of the commands in those categories. Instant phrases,
responses and descriptions the user adds stay. A command with the same name
in another category is the user's own and is left alone.
"""

# A custom skill is loaded from its file, without a package, so the absolute
# imports of its own modules below would not resolve. Register this folder as
# the package when nothing else provides it (a bundled copy wins).
import importlib.util as _util
import sys as _sys
import types as _types
from pathlib import Path as _Path

_PACKAGE = "skills.elite_dangerous_controls"
if _PACKAGE not in _sys.modules and _util.find_spec("skills") is not None:
    try:
        _missing = _util.find_spec(_PACKAGE) is None
    except ModuleNotFoundError:
        _missing = True
    if _missing:
        _package = _types.ModuleType(_PACKAGE)
        _package.__path__ = [str(_Path(__file__).parent)]
        _sys.modules[_PACKAGE] = _package

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from api.interface import CommandActionConfig, CommandConfig, SettingsConfig, SkillConfig
from skills.elite_dangerous_controls.bindings import (
    Bindings,
    blocked_keys,
    control_schemes_dirs,
    default_bindings_dir,
    game_dirs,
    read_bindings,
)
from skills.elite_dangerous_controls.catalog import CATALOG, CATEGORIES
from skills.skill_base import Skill, command_action

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

WATCH_SECONDS = 5


def _same_actions(command, actions: list[CommandActionConfig]) -> bool:
    current = [a.model_dump(exclude_none=True) for a in (command.actions or [])]
    return current == [a.model_dump(exclude_none=True) for a in actions]


def apply_bindings(commands, bindings: Bindings) -> bool:
    """Add, update and remove the Elite commands. True if anything changed.

    `commands` is the facade's SkillCommands.
    """
    existing = {c.name for c in commands.categories()}
    changed = False
    for mode, rows in CATALOG.items():
        bound = any(name in bindings.actions for _, name in rows)
        if not bound and CATEGORIES[mode] not in existing:
            continue  # No empty category for a mode without keys.
        category = commands.add_category(CATEGORIES[mode])
        for _, name in rows:
            command = commands.get(name)
            ours = command is not None and command.category_id == category.id
            if name not in bindings.actions:
                if ours:
                    commands.remove(name)
                    changed = True
                continue
            actions = [CommandActionConfig.model_validate(a) for a in bindings.actions[name]]
            if command is None:
                commands.add(
                    CommandConfig(
                        name=name,
                        instant_activation=[name.lower()],
                        actions=actions,
                    ),
                    category=category,
                )
                changed = True
            elif ours and not _same_actions(command, actions):
                command.actions = actions
                changed = True
    return changed


class EliteDangerousControls(Skill):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext"
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._run_id = 0
        self._lock = threading.Lock()
        """The watcher and the command action may sync at the same time."""
        self._last_error = ""
        self._last_summary = ""

    # --- settings, read fresh -------------------------------------------------

    def _bindings_dir(self) -> Path:
        value = self.retrieve_custom_property_value("bindings_directory", [])
        return Path(value).expanduser() if value else default_bindings_dir()

    def _schemes(self) -> list[Path]:
        value = self.retrieve_custom_property_value("game_directory", [])
        roots = [Path(value).expanduser()] if value else game_dirs()
        return [folder for root in roots for folder in control_schemes_dirs(root)]

    # --- lifecycle --------------------------------------------------------------

    async def validate(self):
        errors = await super().validate()
        self.retrieve_custom_property_value("bindings_directory", errors)
        self.retrieve_custom_property_value("game_directory", errors)
        return errors

    async def prepare(self) -> None:
        await super().prepare()
        self._run_id += 1
        # Voice requests run on loops that close after the reply, so the
        # watcher gets its own thread and loop.
        self.wingman.run_in_thread(self._watch, self._run_id)

    async def unload(self) -> None:
        self._run_id += 1
        await super().unload()

    # --- keeping the commands in step ---------------------------------------------

    def _stamp(self) -> tuple:
        """Changes when the pilot saves other bindings or picks another preset."""
        folder = self._bindings_dir()
        try:
            return tuple(sorted(
                (p.name, p.stat().st_mtime_ns)
                for p in folder.iterdir()
                if p.suffix in (".binds", ".start")
            )) + (str(folder),)
        except OSError:
            return (str(folder),)

    async def _watch(self, run_id: int) -> None:
        stamp = None
        while run_id == self._run_id:
            try:
                current = await asyncio.to_thread(self._stamp)
                if current != stamp:
                    stamp = current
                    await self.sync()
            except Exception as error:  # A half-written file; the next round reads it.
                self.log.warning(f"Elite bindings: {error}", server_only=True)
            await asyncio.sleep(WATCH_SECONDS)

    async def sync(self) -> str:
        """Bring the Elite commands in line with the game's bindings."""
        config = self.wingman.config
        blocked = blocked_keys(config.record_key, list(config.record_key_codes or []))
        try:
            bindings = await asyncio.to_thread(
                read_bindings, self._bindings_dir(), self._schemes(), blocked
            )
        except (OSError, ValueError) as error:
            message = f"Could not read your Elite key bindings. {error}."
            if message != self._last_error:
                self._last_error = message
                self.log.warning(message)
            return message
        self._last_error = ""
        with self._lock:
            changed = apply_bindings(self.wingman.commands, bindings)
        if changed:
            await self.wingman.commands.save()
        summary = (
            f"{len(bindings.actions)} Elite controls are ready as commands. "
            f"{len(bindings.unbound)} have no keyboard key in Elite."
        )
        if summary != self._last_summary:
            self._last_summary = summary
            self.log.info(summary, server_only=True)
        return summary

    @command_action(
        label="Read Elite Bindings",
        description="Read the key bindings from Elite again and say how many controls are ready.",
        respond="speak",
    )
    async def sync_elite_bindings(self) -> str:
        return await self.sync()

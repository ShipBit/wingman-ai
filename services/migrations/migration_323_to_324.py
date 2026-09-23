"""Migration from version 3.2.3 to 3.2.4.

3.2.4 adds a System One model: a decision layer in front of the main model.
It answers Wingman's typed questions — which command was asked for, which
skills a turn needs, whether the microphone heard a request at all, whether a
word the speech model wrote is a game name or the everyday word it looks like
— in about 300 ms, where a chat model takes over a second.

Two things follow for a config written by 3.2.3.

`settings.yaml` gains a `system_one` block, both switches on. The second one,
`commands`, is separate because it is the only decision that runs on spec:
every other use waits until there is something to resolve. Measured
2026-09-21 against gpt-4.1-mini on the shipped Star Citizen config, it puts
the keypress at 0.48 s instead of 1.13 s and the spoken confirmation at
1.49 s instead of 2.13 s; a request that is not a command costs 0.46 s and
changes nothing.

Commands gain a `description`, and the ones that came from a shipped template
get theirs filled in. It is what tells two commands apart that read alike —
"Autoland", "Autodock", "Toggle Landing System" and "Landing Sequence" all
mean "land the ship" to a reader who only has the names. Measured 2026-09-20
on 152 spoken transcripts: the chat model went from 0.884 to 0.952 with them
and the System One model from 0.863 to 0.973.

Only commands that still carry the shipped name and have no description are
touched. A command the user wrote, renamed or already described is left
alone, and the field stays optional: most commands never need one.

On by default because there is nothing to weigh up. The model behind it is a
fixed role of every plan, like transcription and speech, so it costs the user
nothing extra; and every decision it takes has the old path behind it, so a
plan without access or a backend that is down costs latency and changes no
answer. A user who turns it off gets exactly 3.2.3's behaviour.

The field is required on `SystemOneSettings`, so a settings.yaml without the
block would not load at all. It is still added here rather than left to the
repair that fills a stale settings.yaml from the template on load: the repair
is a safety net for files that skipped a migration, and a value the user is
meant to own belongs in the chain where the log says it was set.

`settings.yaml` also gains `show_token_count`, off. It decides whether the
client shows token counts on Wingman messages and in the status bar; those
counts are now what the provider reported for the whole turn, not an estimate
of the message text.
"""

import os
from os import path

import yaml

from services.migrations.base_migration import BaseMigration


class Migration323To324(BaseMigration):
    """Migration from 3.2.3 to 3.2.4."""

    old_version = "3_2_3"
    new_version = "3_2_4"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._descriptions: dict[str, str] | None = None

    def _shipped_descriptions(self) -> dict[str, str]:
        """Command name to description, from every template this build ships.

        Read from the templates rather than pasted in here because there are
        67 of them and two copies would drift. The risk that usually argues
        against this — a migration whose result depends on the installed
        files — does not apply: the templates ship with the build that runs
        the migration.
        """
        if self._descriptions is not None:
            return self._descriptions

        self._descriptions = {}
        configs = path.join(self.templates_dir, "configs")
        for root, _dirs, files in os.walk(configs):
            for file_name in files:
                if not file_name.endswith(".template.yaml"):
                    continue
                try:
                    with open(path.join(root, file_name), encoding="utf-8") as f:
                        template = yaml.safe_load(f) or {}
                except Exception as e:
                    self.log_warning(f"- could not read {file_name}: {e}")
                    continue
                for command in template.get("commands") or []:
                    name, text = command.get("name"), command.get("description")
                    if name and text:
                        self._descriptions[name] = text
        return self._descriptions

    def migrate_wingman(self, old: dict) -> dict:
        """Fill in the descriptions for commands that came from a template."""
        commands = old.get("commands")
        if not isinstance(commands, list):
            return old

        shipped = self._shipped_descriptions()
        if not shipped:
            self.log_warning("- no command descriptions found in the templates; skipping")
            return old

        filled = 0
        for command in commands:
            if not isinstance(command, dict) or command.get("description"):
                continue
            text = shipped.get(command.get("name"))
            if text:
                command["description"] = text
                filled += 1

        if filled:
            self.log(
                f"- {filled} command(s) got the description the template ships, "
                "which is what tells two commands that read alike apart"
            )
        return old

    def migrate_settings(self, old: dict) -> dict:
        """Add the token count switch, off, and the System One block, on,
        unless the user already has them."""
        if "show_token_count" not in old:
            # Off: the counts on each message were an estimate of the message
            # text alone, which read like a cost and was not one. The real
            # counts are there for whoever wants them, behind a switch.
            old["show_token_count"] = False
            self.log("- show_token_count: off — token counts are hidden unless switched on")

        block = old.get("system_one")
        if isinstance(block, dict):
            # Written by the load-time repair before this ran. Whatever it
            # says is the user's now — overwriting it here would switch the
            # feature back on for someone who had already turned it off. Only
            # a key that is missing outright is filled in, so the file still
            # satisfies a model where both fields are required.
            if "enabled" not in block:
                block["enabled"] = True
            if "commands" not in block:
                block["commands"] = True
            return old

        old["system_one"] = {"enabled": True, "commands": True}
        self.log(
            "- system_one: on — misheard names, stray noise and which command "
            "a request means are decided by a System One model first"
        )
        return old

"""Migration from version 3.2.2 to 3.2.3.

Two voice activation defaults change, because the shipped values hurt in
practice:

- `max_utterance_s` was 12. It is a hard cut, so a sentence longer than 12
  seconds was split mid-word: the half-word went to the LLM as its own message
  (a second call, paid twice) and numbers came out wrong. It is meant as an
  emergency stop for a microphone that never goes quiet, not as a pacing knob,
  so it moves to 160.
- `end_pause_ms` was 700 and moves to 500. That is the knob for "send sooner",
  and 500 ms saves 200 ms per command with no misfires in testing.

Both are only rewritten when the user still has the old default. A value the
user changed is kept.

A `system_one` block is added, switched on. It is a new required field, so a
settings.yaml without it would not load; the model behind it comes from the
subscription as a fixed role, the way transcription and speech do.

3.2.3 also fixes how an existing settings.yaml is read: a file that predates
the current models is filled from the shipped template when it is loaded,
which needs no migration step.

The system prompt is reset to the shipped one, the same way 3.1.2 did it. It
is not user content: it carries the tool-calling contract, the output format
and the placeholders the backend fills in, and every release moves it. A user
who edited it once keeps an old contract forever and gets worse answers from a
backend that has moved on. `defaults.yaml` is overwritten with the shipped
prompt, and a per-Wingman override is deleted outright so the Wingman falls
back to that one prompt. Backstories are untouched — that IS user content.
"""

from os import path
from typing import Optional

from services.migrations.base_migration import BaseMigration

OLD_MAX_UTTERANCE_S = 12
NEW_MAX_UTTERANCE_S = 160

OLD_END_PAUSE_MS = 700
NEW_END_PAUSE_MS = 500


class Migration322To323(BaseMigration):
    """Migration from 3.2.2 to 3.2.3."""

    old_version = "3_2_2"
    new_version = "3_2_3"

    def _shipped_system_prompt(self) -> Optional[str]:
        """The system prompt from the templates shipped with THIS build."""
        defaults_path = path.join(self.templates_dir, "configs", "defaults.yaml")
        if not path.exists(defaults_path):
            return None
        template = self.config_manager.read_config(defaults_path)
        if not template:
            return None
        return (template.get("prompts") or {}).get("system_prompt")

    def migrate_settings(self, old: dict) -> dict:
        # The System One block is new in 3.2.3 and the field is required, so a
        # settings.yaml without it would not load at all. On by default: the
        # model behind it is a fixed role of every plan, and every decision it
        # takes falls back to the old path when it is unavailable.
        if not isinstance(old.get("system_one"), dict):
            old["system_one"] = {"enabled": True}
            self.log("- system_one.enabled: added, on (decisions get a System One model)")

        va = old.get("voice_activation")
        if not isinstance(va, dict):
            return old

        if va.get("max_utterance_s") == OLD_MAX_UTTERANCE_S:
            va["max_utterance_s"] = NEW_MAX_UTTERANCE_S
            self.log(
                f"- voice_activation.max_utterance_s: {OLD_MAX_UTTERANCE_S} -> "
                f"{NEW_MAX_UTTERANCE_S} (no more mid-word cuts)"
            )

        if va.get("end_pause_ms") == OLD_END_PAUSE_MS:
            va["end_pause_ms"] = NEW_END_PAUSE_MS
            self.log(
                f"- voice_activation.end_pause_ms: {OLD_END_PAUSE_MS} -> "
                f"{NEW_END_PAUSE_MS} (faster send)"
            )

        return old

    def migrate_defaults(self, old: dict) -> dict:
        """Put the shipped system prompt back into defaults.yaml."""
        shipped = self._shipped_system_prompt()
        if not shipped:
            self.log_warning(
                "- could not read the shipped system prompt; leaving defaults.yaml alone"
            )
            return old

        prompts = old.get("prompts")
        if not isinstance(prompts, dict) or "system_prompt" not in prompts:
            return old

        if prompts["system_prompt"] != shipped:
            prompts["system_prompt"] = shipped
            self.log("- defaults: system prompt reset to the shipped one")
        return old

    def migrate_wingman(self, old: dict) -> dict:
        """Drop a Wingman's own system prompt so it uses the shipped one.

        Deleted rather than overwritten: with the key gone the Wingman inherits
        from defaults.yaml, so the next release moves it along with everyone
        else instead of pinning today's text into the file forever.
        """
        prompts = old.get("prompts")
        if not isinstance(prompts, dict) or "system_prompt" not in prompts:
            return old

        prompts.pop("system_prompt")
        # An empty prompts block is noise in the file.
        if not prompts:
            old.pop("prompts")
        self.log(
            f"- {old.get('name', 'wingman')}: removed its own system prompt; "
            "it uses the shipped one now"
        )
        return old

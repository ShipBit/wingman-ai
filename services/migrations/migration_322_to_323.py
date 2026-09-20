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

3.2.3 also fixes how an existing settings.yaml is read: a file that predates
the current models is filled from the shipped template when it is loaded,
which needs no migration step.
"""

from services.migrations.base_migration import BaseMigration

OLD_MAX_UTTERANCE_S = 12
NEW_MAX_UTTERANCE_S = 160

OLD_END_PAUSE_MS = 700
NEW_END_PAUSE_MS = 500


class Migration322To323(BaseMigration):
    """Migration from 3.2.2 to 3.2.3."""

    old_version = "3_2_2"
    new_version = "3_2_3"

    def migrate_settings(self, old: dict) -> dict:
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

"""Migration from version 3.2.3 to 3.2.4.

3.2.4 adds a System One model: a decision layer in front of the main model.
It answers Wingman's typed questions — which command was asked for, which
skills a turn needs, whether the microphone heard a request at all, whether a
word the speech model wrote is a game name or the everyday word it looks like
— in about 300 ms, where a chat model takes over a second.

One thing follows for a config written by 3.2.3: `settings.yaml` gains a
`system_one` block, switched on.

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
"""

from services.migrations.base_migration import BaseMigration


class Migration323To324(BaseMigration):
    """Migration from 3.2.3 to 3.2.4."""

    old_version = "3_2_3"
    new_version = "3_2_4"

    def migrate_settings(self, old: dict) -> dict:
        """Add the System One block, on, unless the user already has one."""
        if isinstance(old.get("system_one"), dict):
            # Written by the load-time repair before this ran. Whatever it says
            # is the user's now — overwriting it here would switch the feature
            # back on for someone who had already turned it off.
            return old

        old["system_one"] = {"enabled": True}
        self.log(
            "- system_one.enabled: on — commands, skill choice and misheard "
            "names are decided by a System One model first"
        )
        return old

"""Migration from version 3.2.4 to 3.2.5.

3.2.5 changes how the client installs an update: a toast with download
progress, and a restart once it is installed. None of that is configured.

It also works out every limit on what Wingman sends from the main model's
context window instead of fixed numbers (services/context_budget.py,
docs/context-and-shortening.md). Four settings made for the old numbers go,
from defaults and every Wingman:

- `features.compress_tool_responses`: a tool response over the limit is now
  always cut, never summarized. On real text the summary kept none of three
  facts and made the pilot wait 25 seconds; the cut kept two.
- `features.skill_max_input_tokens`: the limit is 32,000 tokens, or a quarter
  of a smaller model's window.
- `features.condense_keep_recent_tokens` and `features.condense_max_messages`:
  the history limit decides when and how much is summarized.

`features.condense_conversation` stays, the one switch left.
"""

from services.migrations.base_migration import BaseMigration

_REMOVED_FEATURES = (
    "compress_tool_responses",
    "skill_max_input_tokens",
    "condense_keep_recent_tokens",
    "condense_max_messages",
)


class Migration324To325(BaseMigration):
    """Migration from 3.2.4 to 3.2.5."""

    old_version = "3_2_4"
    new_version = "3_2_5"

    def _drop_fixed_limits(self, old: dict) -> None:
        features = old.get("features")
        if not isinstance(features, dict):
            return
        for key in _REMOVED_FEATURES:
            if key in features:
                del features[key]
                self.log(f"- removed features.{key} (limits follow the model's window now)")

    def migrate_defaults(self, old: dict) -> dict:
        self._drop_fixed_limits(old)
        return old

    def migrate_wingman(self, old: dict) -> dict:
        self._drop_fixed_limits(old)
        return old

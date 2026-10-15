"""3.2.9: the system prompt learns when to run a command and how long to talk,
inside the user's own prompt."""

from unittest.mock import MagicMock

from services.migrations.migration_328_to_329 import Migration328To329
from tests.support import template

OLD_PROMPT = (
    "# OUTPUT FORMAT\n"
    "- Keep responses concise (1-3 sentences unless more detail is needed)\n\n"
    "# YOUR CAPABILITIES\nUse tools.\n"
)


def migration():
    return Migration328To329(MagicMock())


def test_the_shipped_prompt_has_the_rules_after_migrating():
    shipped = template("defaults.yaml")["prompts"]["system_prompt"]
    out = migration().migrate_defaults({"prompts": {"system_prompt": OLD_PROMPT}})
    prompt = out["prompts"]["system_prompt"]
    assert "# ACTIONS" in prompt and "# ACTIONS" in shipped
    assert "1-3 sentences, the answer first" in prompt
    assert prompt.index("# ACTIONS") < prompt.index("# YOUR CAPABILITIES")


def test_an_edited_prompt_keeps_its_edits():
    mine = OLD_PROMPT + "Always speak like a pirate.\n"
    out = migration().migrate_wingman({"name": "KAT", "prompts": {"system_prompt": mine}})
    assert "Always speak like a pirate." in out["prompts"]["system_prompt"]
    assert "# ACTIONS" in out["prompts"]["system_prompt"]


def test_running_twice_adds_nothing():
    once = migration().migrate_defaults({"prompts": {"system_prompt": OLD_PROMPT}})
    twice = migration().migrate_defaults(once)
    assert twice["prompts"]["system_prompt"].count("# ACTIONS") == 1


def test_a_wingman_without_its_own_prompt_is_left_alone():
    assert migration().migrate_wingman({"name": "KAT"}) == {"name": "KAT"}


def test_the_328_prompt_becomes_exactly_the_shipped_one():
    from services.migrations.migration_328_to_329 import (
        ACTIONS_BLOCK,
        NEW_LENGTH_RULE,
        OLD_LENGTH_RULE,
    )

    shipped = template("defaults.yaml")["prompts"]["system_prompt"]
    before = shipped.replace(ACTIONS_BLOCK, "").replace(NEW_LENGTH_RULE, OLD_LENGTH_RULE)
    assert before != shipped
    out = migration().migrate_defaults({"prompts": {"system_prompt": before}})
    assert out["prompts"]["system_prompt"] == shipped

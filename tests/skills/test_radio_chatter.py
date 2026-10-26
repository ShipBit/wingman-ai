"""Radio chatter when the model writes no JSON: a warning, the next round
tries again. Small models do this now and then; it is no bug to report."""

import asyncio
from types import SimpleNamespace

from skills.radio_chatter.main import RadioChatter


class Log:
    def __init__(self):
        self.lines = []

    def warning(self, message, server_only=False):
        self.lines.append(("warning", message))

    def error(self, message, server_only=False):
        self.lines.append(("error", message))


def test_an_answer_that_is_no_json_is_a_warning():
    skill = object.__new__(RadioChatter)
    skill.run_id, skill.radio_status, skill.loaded = 1, True, True
    skill.retrieve_custom_property_value = lambda prop, errors: None
    skill.log = Log()

    async def generate(prompt, system=None, auto_shorten=False):
        return "Sure! Here is a dialog: Pilot: Hello."

    skill.wingman = SimpleNamespace(
        ai=SimpleNamespace(generate=generate),
        language=SimpleNamespace(name="English"),
    )

    asyncio.run(skill._generate_chatter(1))

    assert [level for level, _message in skill.log.lines] == ["warning"]

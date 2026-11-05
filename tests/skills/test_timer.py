"""Timer skill: what set_timer accepts as function arguments."""

import asyncio
from types import SimpleNamespace

from skills.timer.main import Timer


def _timer_skill():
    skill = object.__new__(Timer)
    skill.timers = {}
    skill.wingman = SimpleNamespace(
        tools=SimpleNamespace(has=lambda name: name == "remind_me"),
        commands=SimpleNamespace(get=lambda name: None),
    )
    return skill


def _set(skill, arguments):
    return asyncio.run(
        Timer.set_timer(skill, delay=5, function_name="remind_me", function_arguments_json=arguments, is_loop=True)
    )


def test_arguments_as_an_object_set_the_timer():
    skill = _timer_skill()

    result = _set(skill, {"message": "Hello"})

    assert result.startswith("Timer set")
    (timer,) = skill.timers.values()
    assert timer.function_arguments == {"message": "Hello"}


def test_arguments_as_a_json_string_set_the_timer():
    skill = _timer_skill()

    _set(skill, '{"message": "Hello"}')

    (timer,) = skill.timers.values()
    assert timer.function_arguments == {"message": "Hello"}


def test_arguments_that_are_no_object_are_refused():
    skill = _timer_skill()

    assert _set(skill, "not json").startswith("Error")
    assert _set(skill, "[1, 2]").startswith("Error")
    assert skill.timers == {}

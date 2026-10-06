"""Which sentence fires an instant activation command. The speech model adds
punctuation and capitals, and with voice activation the sentence opens with
the wingman's name; the phrase in the config has neither."""

import asyncio
from types import SimpleNamespace

import pytest

from services.command_executor import CommandExecutor


def executor_with(*phrases, wingman_name="Computer"):
    commands = [
        SimpleNamespace(name=f"cmd{i}", instant_activation=list(phrase_list))
        for i, phrase_list in enumerate(phrases)
    ]
    config = SimpleNamespace(commands=commands)
    executor = CommandExecutor(
        config=config,
        audio_library=None,
        wingman_name=wingman_name,
        on_reset_history=None,
    )
    executed = []

    async def fake_execute(command, is_instant=False):
        executed.append(command.name)
        return f"{command.name} done", None

    executor.execute_command = fake_execute
    return executor, executed


def fired(executor, executed, transcript):
    executed.clear()
    asyncio.run(executor.try_instant_activation(transcript))
    return list(executed)


def test_plain_phrase_fires():
    executor, executed = executor_with(["landing gear"])
    assert fired(executor, executed, "landing gear") == ["cmd0"]


def test_punctuation_and_capitals_do_not_matter():
    executor, executed = executor_with(["landing gear"])
    assert fired(executor, executed, "Landing gear.") == ["cmd0"]
    assert fired(executor, executed, "Landing Gear!") == ["cmd0"]


def test_wingman_name_in_front_is_ignored():
    executor, executed = executor_with(["landing gear"])
    assert fired(executor, executed, "Computer, landing gear.") == ["cmd0"]
    assert fired(executor, executed, "Hey Computa, landing gear") == ["cmd0"]


def test_more_words_than_the_phrase_do_not_fire():
    executor, executed = executor_with(["landing gear"])
    assert fired(executor, executed, "Computer, landing gear please") == []
    assert fired(executor, executed, "raise the landing gear") == []


def test_only_the_own_name_is_stripped():
    executor, executed = executor_with(["landing gear"], wingman_name="Ava")
    assert fired(executor, executed, "Computer, landing gear") == []
    assert fired(executor, executed, "Ava, landing gear") == ["cmd0"]


def test_two_commands_on_one_phrase_both_fire():
    executor, executed = executor_with(["lights"], ["lights"])
    assert fired(executor, executed, "Computer, lights") == ["cmd0", "cmd1"]


def test_empty_phrase_never_matches_a_bare_name():
    executor, executed = executor_with([""], ["landing gear"])
    assert fired(executor, executed, "Computer.") == []

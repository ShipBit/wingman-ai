"""Wingman endpoints before sign-in and while the config reloads.

There is no Tower then, and the client may already call. Each endpoint answers
as for a Wingman that is not loaded instead of raising on ``None``.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import wingman_core
from wingmen.open_ai_wingman import OpenAiWingman


def _core(tower=None):
    core = wingman_core.WingmanCore.__new__(wingman_core.WingmanCore)
    core.tower = tower
    core.printr = MagicMock()
    return core


def test_wingman_endpoints_answer_without_a_tower():
    core = _core()

    assert asyncio.run(core.ask_wingman_conversation_provider("Computer", "Hi")) is None
    assert asyncio.run(core.generate_image("a ship", "Computer")) is None
    assert asyncio.run(core.send_text_to_wingman(text="Hi", wingman_name="Computer")) is None
    assert asyncio.run(core.send_audio_to_wingman("Computer", file=None)) is None
    assert asyncio.run(core.reset_conversation_history("Computer")) is True
    assert asyncio.run(core.reset_conversation_history()) is True
    assert asyncio.run(core.condense_conversation("Computer")) is False
    assert core.get_wingman_context("Computer") == ""
    assert core.get_wingman_conversation("Computer") == []


def _wingman(completion):
    wingman = OpenAiWingman.__new__(OpenAiWingman)

    async def actual_llm_call(messages, *args, **kwargs):
        return completion

    wingman.actual_llm_call = actual_llm_call
    return wingman


def _tower(wingman):
    return SimpleNamespace(get_wingman_by_name=lambda name: wingman)


@pytest.mark.parametrize("completion", [None, SimpleNamespace(choices=[])])
def test_asking_the_provider_without_an_answer_is_none(completion):
    core = _core(_tower(_wingman(completion)))

    assert asyncio.run(core.ask_wingman_conversation_provider("Computer", "Hi")) is None


def test_a_failed_backstory_enhancement_is_no_server_error():
    """The provider failed and the user was told. A 5xx would be reported as
    a bug in Core."""
    core = _core(_tower(_wingman(None)))

    with pytest.raises(HTTPException) as raised:
        asyncio.run(core.api_enhance_backstory(wingman_name="Computer", backstory="A pilot."))

    assert 400 <= raised.value.status_code < 500

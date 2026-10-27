"""A skill takes over the conversation: what the user says goes to its
handler, the Wingman's name takes it back, and silence ends it."""

import asyncio
from types import SimpleNamespace

from services.conversation_manager import NOTE_PREFIX
from wingmen.wingman import Wingman


def _wingman(name="Computer"):
    wingman = SimpleNamespace(
        config=SimpleNamespace(name=name),
        conversation=SimpleNamespace(messages=[]),
        _takeover=None,
        _speakers={},
    )
    for method in ("take_over", "_takeover_released", "register_speaker", "unregister_speaker",
                   "_takeover_turn", "_note_said_to", "_takeover_failed"):
        setattr(wingman, method, getattr(Wingman, method).__get__(wingman))
    return wingman


def _notes(wingman):
    return [m["content"][len(NOTE_PREFIX):-1] for m in wingman.conversation.messages]


class Tecia:
    """A handler that keeps the conversation until the pilot says bye."""

    def __init__(self):
        self.heard = []

    async def __call__(self, text):
        self.heard.append(text)
        return "bye" not in text.lower()


def test_while_taken_over_the_handler_hears_the_user_and_the_model_does_not():
    wingman = _wingman()
    tecia = Tecia()
    takeover = wingman.take_over("Tecia Varga", tecia)

    handled = asyncio.run(wingman._takeover_turn("Do you have work for me?"))

    assert handled and tecia.heard == ["Do you have work for me?"]
    assert takeover.active and wingman._takeover is takeover
    assert _notes(wingman) == ['The user said to Tecia Varga: "Do you have work for me?"']


def test_the_handler_ends_the_conversation():
    wingman = _wingman()
    takeover = wingman.take_over("Tecia Varga", Tecia())

    assert asyncio.run(wingman._takeover_turn("Thanks, bye."))
    assert not takeover.active and wingman._takeover is None


def test_the_wingmans_name_takes_the_conversation_back():
    wingman = _wingman("Computer")
    tecia = Tecia()
    takeover = wingman.take_over("Tecia Varga", tecia)

    handled = asyncio.run(wingman._takeover_turn("Computa, what time is it?"))

    assert not handled and not takeover.active and tecia.heard == []
    assert wingman.conversation.messages == []  # the model gets the sentence as usual


def test_silence_ends_the_conversation():
    wingman = _wingman()
    tecia = Tecia()
    takeover = wingman.take_over("Tecia Varga", tecia, idle_s=60)
    takeover.last_at -= 61

    assert not asyncio.run(wingman._takeover_turn("Still there?"))
    assert not takeover.active and tecia.heard == []


def test_a_failing_handler_releases_and_the_turn_counts_as_handled():
    wingman = _wingman()

    async def broken(text):
        raise RuntimeError("no model")

    async def quiet(*args, **kwargs):
        pass

    wingman._takeover_failed = quiet
    takeover = wingman.take_over("Tecia Varga", broken)

    assert asyncio.run(wingman._takeover_turn("Hello?"))
    assert not takeover.active


def test_a_registered_speaker_is_addressed_by_name_like_a_wingman():
    wingman = _wingman("Computer")
    opened = []

    async def opener(name, text):
        opened.append((name, text))
        wingman.take_over(name, Tecia())
        return True

    wingman.register_speaker("Tecia", opener)

    assert asyncio.run(wingman._takeover_turn("Tesia, do you have work?"))
    assert opened == [("Tecia", "Tesia, do you have work?")]
    assert wingman._takeover is not None and wingman._takeover.speaker == "Tecia"
    assert _notes(wingman) == ['The user said to Tecia: "Tesia, do you have work?"']


def test_an_opener_that_declines_leaves_no_trace():
    wingman = _wingman()

    async def opener(name, text):
        return False

    wingman.register_speaker("Tecia", opener)

    assert not asyncio.run(wingman._takeover_turn("Tecia is a nice name."))
    assert wingman.conversation.messages == []


def test_the_wingman_wins_over_a_speaker_when_both_fit():
    wingman = _wingman("Marek")
    opened = []

    async def opener(name, text):
        opened.append(name)
        return True

    wingman.register_speaker("Marek Varga", opener)

    assert not asyncio.run(wingman._takeover_turn("Marek, gear up."))
    assert opened == []


def test_unregistering_a_speaker_and_a_new_takeover_replacing_the_old():
    wingman = _wingman()
    first = wingman.take_over("Tecia Varga", Tecia())
    second = wingman.take_over("Marek Varga", Tecia())

    assert not first.active and second.active and wingman._takeover is second

    wingman.register_speaker("Tecia", None)
    wingman.unregister_speaker("Tecia")
    assert wingman._speakers == {}

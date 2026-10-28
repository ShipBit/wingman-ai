"""A skill takes over the conversation: what the user says goes to its
handler, the Wingman's name takes it back, and silence ends it."""

import asyncio
from types import SimpleNamespace

from services.conversation_manager import NOTE_PREFIX
from wingmen.wingman import Wingman


def _wingman(name="Computer"):
    wingman = SimpleNamespace(
        name=name,
        config=SimpleNamespace(name=name),
        conversation=SimpleNamespace(messages=[]),
        _takeover=None,
        _speakers={},
        _speaker_descriptions={},
    )
    for method in ("take_over", "_takeover_released", "register_speaker", "unregister_speaker",
                   "_takeover_turn", "_open_speaker", "_note_said_to", "_takeover_failed",
                   "speaker_names", "speakers"):
        setattr(wingman, method, getattr(Wingman, method).__get__(wingman))
    return wingman


def _notes(wingman):
    return [m["content"][len(NOTE_PREFIX):-1] for m in wingman.conversation.messages]


class Lena:
    """A handler that keeps the conversation until the pilot says bye."""

    def __init__(self):
        self.heard = []

    async def __call__(self, text):
        self.heard.append(text)
        return "bye" not in text.lower()


def test_while_taken_over_the_handler_hears_the_user_and_the_model_does_not():
    wingman = _wingman()
    lena = Lena()
    takeover = wingman.take_over("Lena Varga", lena)

    handled = asyncio.run(wingman._takeover_turn("Do you have work for me?"))

    assert handled and lena.heard == ["Do you have work for me?"]
    assert takeover.active and wingman._takeover is takeover
    assert _notes(wingman) == ['The user said to Lena Varga: "Do you have work for me?"']


def test_the_handler_ends_the_conversation():
    wingman = _wingman()
    takeover = wingman.take_over("Lena Varga", Lena())

    assert asyncio.run(wingman._takeover_turn("Thanks, bye."))
    assert not takeover.active and wingman._takeover is None


def test_the_wingmans_name_takes_the_conversation_back():
    wingman = _wingman("Computer")
    lena = Lena()
    takeover = wingman.take_over("Lena Varga", lena)

    handled = asyncio.run(wingman._takeover_turn("Computa, what time is it?"))

    assert not handled and not takeover.active and lena.heard == []
    assert wingman.conversation.messages == []  # the model gets the sentence as usual


def test_silence_ends_the_conversation():
    wingman = _wingman()
    lena = Lena()
    takeover = wingman.take_over("Lena Varga", lena, idle_s=60)
    takeover.last_at -= 61

    assert not asyncio.run(wingman._takeover_turn("Still there?"))
    assert not takeover.active and lena.heard == []


def test_a_failing_handler_releases_and_the_turn_counts_as_handled():
    wingman = _wingman()

    async def broken(text):
        raise RuntimeError("no model")

    async def quiet(*args, **kwargs):
        pass

    wingman._takeover_failed = quiet
    takeover = wingman.take_over("Lena Varga", broken)

    assert asyncio.run(wingman._takeover_turn("Hello?"))
    assert not takeover.active


def test_a_registered_speaker_is_addressed_by_name_like_a_wingman():
    wingman = _wingman("Computer")
    opened = []

    async def opener(name, text):
        opened.append((name, text))
        wingman.take_over(name, Lena())
        return True

    wingman.register_speaker("Lena", opener)

    assert asyncio.run(wingman._takeover_turn("Lehna, do you have work?"))
    assert opened == [("Lena", "Lehna, do you have work?")]
    assert wingman._takeover is not None and wingman._takeover.speaker == "Lena"
    assert _notes(wingman) == ['The user said to Lena: "Lehna, do you have work?"']


def test_an_opener_that_declines_leaves_no_trace():
    wingman = _wingman()

    async def opener(name, text):
        return False

    wingman.register_speaker("Lena", opener)

    assert not asyncio.run(wingman._takeover_turn("Lena is a nice name."))
    assert wingman.conversation.messages == []


def test_the_wingman_wins_over_a_speaker_when_both_fit():
    wingman = _wingman("Jonas")
    opened = []

    async def opener(name, text):
        opened.append(name)
        return True

    wingman.register_speaker("Jonas Varga", opener)

    assert not asyncio.run(wingman._takeover_turn("Jonas, gear up."))
    assert opened == []


def test_unregistering_a_speaker_and_a_new_takeover_replacing_the_old():
    wingman = _wingman()
    first = wingman.take_over("Lena Varga", Lena())
    second = wingman.take_over("Jonas Varga", Lena())

    assert not first.active and second.active and wingman._takeover is second

    wingman.register_speaker("Lena", None)
    wingman.unregister_speaker("Lena")
    assert wingman._speakers == {}


def test_the_routers_choice_opens_a_speaker_without_a_name_in_the_sentence():
    wingman = _wingman("Computer")
    opened = []

    async def opener(name, text):
        opened.append((name, text))
        wingman.take_over(name, Lena())
        return True

    wingman.register_speaker("Lena", opener, "the trader at Tammany and Sons")

    assert asyncio.run(wingman._takeover_turn("Do you have work for me?", speaker="Lena"))
    assert opened == [("Lena", "Do you have work for me?")]
    assert wingman.speakers() == {"Lena": ("the trader at Tammany and Sons", "Computer")}
    assert wingman.speaker_names() == ["Lena"]

    # The Wingman's own name still wins, whatever the router thought.
    wingman = _wingman("Computer")
    wingman.register_speaker("Lena", opener)
    assert not asyncio.run(wingman._takeover_turn("Computer, what time is it?", speaker="Lena"))


def test_a_wingman_is_taken_over_only_while_the_conversation_is_alive():
    wingman = _wingman()
    wingman.taken_over = property(lambda self: Wingman.taken_over.fget(self))  # noqa: not used on namespace
    assert Wingman.taken_over.fget(wingman) is False

    takeover = wingman.take_over("Lena Varga", Lena(), idle_s=60)
    assert Wingman.taken_over.fget(wingman) is True

    takeover.last_at -= 61
    assert Wingman.taken_over.fget(wingman) is False

    takeover.last_at += 61
    takeover.release()
    assert Wingman.taken_over.fget(wingman) is False

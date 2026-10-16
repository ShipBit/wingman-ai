"""When the user counts as busy: nothing a wingman says on its own may land
over a held key, in the middle of a sentence or between question and answer."""

from services.user_activity import UserActivity


def test_idle_by_default():
    assert not UserActivity().busy


def test_a_held_key_a_running_turn_and_a_sentence_in_progress_are_busy():
    activity = UserActivity()
    activity.set_holding(True)
    assert activity.busy
    activity.set_holding(False)
    activity.turn_started()
    assert activity.busy
    activity.turn_finished()
    capturing = [True]
    activity.set_capture_probe(lambda: capturing[0])
    assert activity.busy  # Voice activation, mid-sentence.
    capturing[0] = False
    assert not activity.busy


def test_a_broken_probe_does_not_block_reactions():
    activity = UserActivity()

    def broken():
        raise RuntimeError("stream gone")

    activity.set_capture_probe(broken)
    assert not activity.busy

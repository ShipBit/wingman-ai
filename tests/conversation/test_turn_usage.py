"""Token usage of one Wingman turn, summed over every model request."""

from unittest.mock import MagicMock

from api.commands import LogCommand
from api.enums import LogType
from api.interface import TokenUsage
from services.turn_metrics import TurnMetrics


def _usage(i: int, c: int, o: int) -> TokenUsage:
    return TokenUsage(input_tokens=i, cached_tokens=c, output_tokens=o)


def _metrics() -> TurnMetrics:
    return TurnMetrics("Test", MagicMock(), MagicMock())


def test_a_turn_with_tool_calls_adds_up_every_request():
    """Each request sends the whole conversation again, so the input of the
    first request is paid for as well as the input of the last."""
    metrics = _metrics()
    metrics.start_turn_usage()
    metrics.add_call_usage(_usage(3000, 2800, 20))
    metrics.add_call_usage(_usage(3200, 3000, 40))
    assert metrics.take_turn_usage() == _usage(6200, 5800, 60)


def test_the_usage_is_handed_out_once():
    metrics = _metrics()
    metrics.add_call_usage(_usage(10, 0, 1))
    assert metrics.take_turn_usage() is not None
    assert metrics.take_turn_usage() is None


def test_a_turn_without_a_model_call_has_no_usage():
    """Instant commands and System One answers never ask the model; what a
    turn before them used must not show up on their message."""
    metrics = _metrics()
    metrics.add_call_usage(_usage(10, 0, 1))
    metrics.start_turn_usage()
    assert metrics.take_turn_usage() is None


def test_a_provider_that_reports_nothing_adds_nothing():
    metrics = _metrics()
    metrics.add_call_usage(_usage(0, 0, 0))
    assert metrics.take_turn_usage() is None


def test_the_first_request_is_not_changed_by_later_ones():
    first = _usage(10, 0, 1)
    metrics = _metrics()
    metrics.add_call_usage(first)
    metrics.add_call_usage(_usage(10, 0, 1))
    assert first == _usage(10, 0, 1)


def test_the_log_command_carries_it_to_the_client():
    command = LogCommand(text="hi", log_type=LogType.POSITIVE, token_usage=_usage(5, 2, 1))
    assert command.model_dump()["token_usage"] == {
        "input_tokens": 5,
        "cached_tokens": 2,
        "output_tokens": 1,
    }

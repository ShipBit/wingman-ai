"""Token usage of one Wingman turn, summed over every model request."""

from unittest.mock import MagicMock

from api.interface import TokenUsage
from services.turn_metrics import TurnMetrics


def _usage(i: int, c: int, o: int) -> TokenUsage:
    return TokenUsage(input_tokens=i, cached_tokens=c, output_tokens=o)


def _metrics() -> TurnMetrics:
    return TurnMetrics("Test", MagicMock(), MagicMock())


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


def test_every_request_is_kept_on_its_own():
    """The client shows the context size, which is the input of the last
    request, and says what each request was for."""
    metrics = _metrics()
    metrics.start_turn_usage()
    metrics.add_call_usage(_usage(5500, 5100, 30), ["activate_capability"])
    metrics.add_call_usage(_usage(12100, 0, 40), ["uex_get_trade_routes"])
    metrics.add_call_usage(_usage(12500, 12100, 200))
    usage = metrics.take_turn_usage()
    assert (usage.input_tokens, usage.cached_tokens, usage.output_tokens) == (30100, 17200, 270)
    assert [r.tool_calls for r in usage.requests] == [
        ["activate_capability"],
        ["uex_get_trade_routes"],
        [],
    ]
    assert usage.requests[-1].input_tokens == 12500

"""What reaches Sentry, and what must never reach it.

The events are caught by a fake transport, so nothing leaves the machine. The
privacy half of these tests matters as much as the reporting half: an API key
or a line the user said in a Sentry event is a leak, not a bug report.
"""

import os
import threading

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from api.enums import LogType
from services import error_reporting
from services.printr import Printr


class CaptureTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def sentry(tmp_path, monkeypatch):
    """Error reporting with its state file in tmp_path and a fake transport."""
    monkeypatch.setattr(error_reporting, "get_users_dir", lambda: str(tmp_path))
    monkeypatch.setenv("WINGMAN_SENTRY", "1")
    transport = CaptureTransport()
    real_init = sentry_sdk.init
    monkeypatch.setattr(
        sentry_sdk, "init", lambda **kw: real_init(transport=transport, **kw)
    )
    for name, value in {
        "_started": False,
        "_enabled": None,
        "_install_id": None,
        "_user_id": None,
        "_channel": None,
        "_sent_keys": set(),
        "_sent_count": 0,
        "_tag_provider": None,
    }.items():
        monkeypatch.setattr(error_reporting, name, value)

    yield transport

    sentry_sdk.get_client().close(timeout=1)
    sentry_sdk.get_global_scope().set_user(None)


def flush():
    sentry_sdk.flush(timeout=2)


def log_error(message: str, exc: Exception):
    try:
        raise exc
    except Exception:
        Printr().print(message, color=LogType.ERROR, server_only=True)


def test_nothing_is_sent_before_the_user_chose(sentry):
    error_reporting.init()
    log_error("Failed", ValueError("boom"))
    flush()

    assert error_reporting.get_enabled() is None
    assert sentry.events == []


def test_error_logged_in_except_block_is_reported(sentry):
    error_reporting.set_enabled(True)
    log_error("Failed to load wingman", ValueError("boom"))
    flush()

    assert len(sentry.events) == 1
    event = sentry.events[0]
    assert event["exception"]["values"][-1]["type"] == "ValueError"
    assert event["contexts"]["log"]["message"] == "Failed to load wingman"
    assert event["user"]["id"] == error_reporting._install_id


def test_error_message_without_exception_is_only_a_breadcrumb(sentry):
    error_reporting.set_enabled(True)
    Printr().print("No API key set", color=LogType.ERROR, server_only=True)
    log_error("Later failure", ValueError("boom"))
    flush()

    assert len(sentry.events) == 1
    crumbs = [c["message"] for c in sentry.events[0]["breadcrumbs"]["values"]]
    assert "No API key set" in crumbs


def test_conversation_never_becomes_a_breadcrumb(sentry):
    error_reporting.set_enabled(True)
    printr = Printr()
    printr.print("my bank PIN is 1234", color=LogType.USER, server_only=True)
    printr.print("Here is your answer", color=LogType.POSITIVE, server_only=True)
    printr.print("Memory stored: lives in Berlin", color=LogType.MEMORY, server_only=True)
    printr.print("Wingman ready", color=LogType.WINGMAN, server_only=True)
    log_error("Failed", ValueError("boom"))
    flush()

    crumbs = [c["message"] for c in sentry.events[0]["breadcrumbs"]["values"]]
    assert "Wingman ready" in crumbs
    joined = " ".join(crumbs)
    assert "PIN" not in joined
    assert "answer" not in joined
    assert "Berlin" not in joined


def test_secrets_and_home_path_are_scrubbed(sentry, monkeypatch):
    from services.secret_keeper import SecretKeeper

    keeper = SecretKeeper.__new__(SecretKeeper)
    monkeypatch.setattr(SecretKeeper, "_instance", keeper)
    monkeypatch.setattr(keeper, "secrets", {"custom": "my-own-secret-value"}, raising=False)
    error_reporting.set_enabled(True)

    home = os.path.expanduser("~")
    log_error(
        f"Request failed: Bearer abcdefghijklmnop, key sk-proj-abcdefghijklmnopqrstuv, "
        f"file {home}/config.yaml, value my-own-secret-value, url https://x.io/v1?key=AIzaSECRET",
        ValueError(f"at {home}/wingman"),
    )
    flush()

    raw = repr(sentry.events[0])
    assert "abcdefghijklmnop" not in raw
    assert "sk-proj-abcdefghijklmnopqrstuv" not in raw
    assert "my-own-secret-value" not in raw
    assert "AIzaSECRET" not in raw
    assert home not in raw


def test_same_error_is_sent_once_per_session(sentry):
    error_reporting.set_enabled(True)
    for _ in range(3):
        log_error("Failed", ValueError("boom"))
    flush()

    assert len(sentry.events) == 1


def test_session_cap(sentry, monkeypatch):
    monkeypatch.setattr(error_reporting, "MAX_EVENTS_PER_SESSION", 2)
    error_reporting.set_enabled(True)
    log_error("a", ValueError("a"))
    log_error("b", KeyError("b"))
    log_error("c", TypeError("c"))
    flush()

    assert len(sentry.events) == 2


def test_problems_on_the_users_side_are_dropped(sentry):
    class AuthenticationError(Exception):
        pass

    error_reporting.set_enabled(True)
    log_error("Invalid API key", AuthenticationError("401"))
    log_error("Offline", ConnectionError("no route"))
    flush()

    assert sentry.events == []


def test_signed_in_user_id_is_used(sentry):
    error_reporting.set_enabled(True)
    error_reporting.set_user("3f1c-user")
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events[0]["user"]["id"] == "3f1c-user"


def test_user_id_from_before_the_opt_in_is_kept(sentry):
    error_reporting.set_user("3f1c-user")
    error_reporting.set_enabled(True)
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events[0]["user"]["id"] == "3f1c-user"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_unhandled_thread_exception_is_reported(sentry):
    error_reporting.set_enabled(True)

    def crash():
        raise RuntimeError("thread died")

    thread = threading.Thread(target=crash)
    thread.start()
    thread.join()
    flush()

    assert sentry.events[0]["exception"]["values"][-1]["type"] == "RuntimeError"


def test_opt_out_is_stored_and_stops_sending(sentry, tmp_path):
    error_reporting.set_enabled(True)
    error_reporting.set_enabled(False)
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events == []
    error_reporting._enabled = None
    error_reporting.init()
    assert error_reporting.get_enabled() is False


def test_tags_are_read_when_the_event_is_sent(sentry):
    plan = {"value": "Free"}
    error_reporting.set_tag_provider(lambda: {"plan": plan["value"]})
    error_reporting.set_enabled(True)
    plan["value"] = "Pro"
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events[0]["tags"]["plan"] == "Pro"


def test_channel_is_tagged_and_kept_for_the_next_start(sentry):
    error_reporting.set_channel("unstable")
    error_reporting.set_enabled(True)
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events[0]["tags"]["channel"] == "unstable"
    error_reporting._channel = None
    error_reporting.init()
    assert error_reporting._channel == "unstable"


def test_channel_change_while_running(sentry):
    error_reporting.set_enabled(True)
    error_reporting.set_channel("stable")
    log_error("Failed", ValueError("boom"))
    flush()

    assert sentry.events[0]["tags"]["channel"] == "stable"

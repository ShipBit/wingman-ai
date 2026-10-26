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
        self.attachments = []

    def capture_envelope(self, envelope):
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)
            self.attachments.append(
                {
                    item.headers.get("filename"): item.payload.get_bytes()
                    for item in envelope.items
                    if item.type == "attachment"
                }
            )


@pytest.fixture
def sentry(tmp_path, monkeypatch):
    """Error reporting with its state file in tmp_path and a fake transport.
    The session log is a file in tmp_path that starts out missing."""
    monkeypatch.setattr(error_reporting, "get_users_dir", lambda: str(tmp_path))
    Printr()
    monkeypatch.setattr(Printr, "log_file_path", str(tmp_path / "session.log"))
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


# ─── Noise that never reaches Sentry ──────────────────────────────────────────


def openai_error(name: str, status_code: int, message: str = "error"):
    """An exception that looks like one of the openai SDK, without a request."""

    cls = type(name, (Exception,), {"__module__": "openai._exceptions"})
    exc = cls(message)
    exc.status_code = status_code
    exc.message = message
    return exc


@pytest.mark.parametrize("status", [401, 429])
def test_openai_errors_of_the_users_provider_are_dropped(sentry, status):
    error_reporting.set_enabled(True)
    log_error("Provider said no", openai_error("APIStatusError", status))
    flush()

    assert sentry.events == []


def test_openai_unknown_model_is_dropped(sentry):
    error_reporting.set_enabled(True)
    log_error(
        "Model missing",
        openai_error("BadRequestError", 400, "The model `gpt-9` does not exist"),
    )
    log_error(
        "Model missing",
        openai_error("BadRequestError", 400, "Error code: 400 - model_not_found"),
    )
    flush()

    assert sentry.events == []


def test_other_openai_bad_requests_are_reported(sentry):
    error_reporting.set_enabled(True)
    log_error(
        "Bad payload",
        openai_error("BadRequestError", 400, "messages[3].content must be a string"),
    )
    flush()

    assert len(sentry.events) == 1


def test_same_status_outside_openai_is_reported(sentry):
    class APIStatusError(Exception):
        status_code = 404

    error_reporting.set_enabled(True)
    log_error("Our own 404", APIStatusError("missing"))
    flush()

    assert len(sentry.events) == 1


@pytest.mark.parametrize(
    "message",
    [
        "Incorrect API key provided: sk-xx***",
        "No models loaded. Please load a model in the developer page",
        "This model does not support image input",
    ],
)
def test_openai_bad_requests_from_the_users_setup_are_dropped(sentry, message):
    error_reporting.set_enabled(True)
    log_error("Provider said no", openai_error("BadRequestError", 400, message))
    flush()

    assert sentry.events == []


def requests_error(status: int, url: str):
    import requests

    response = requests.Response()
    response.status_code = status
    response.url = url
    return requests.HTTPError(f"{status} Client Error for url: {url}", response=response)


def httpx_error(status: int, url: str):
    import httpx

    request = httpx.Request("GET", url)
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status} for {url}", request=request, response=response)


@pytest.mark.parametrize("status", [401, 402, 403, 429])
@pytest.mark.parametrize("make", [requests_error, httpx_error])
def test_a_third_party_refusing_key_or_quota_is_dropped(sentry, make, status):
    error_reporting.set_enabled(True)
    log_error("Provider said no", make(status, "https://api.example-tts.com/v1/speak"))
    flush()

    assert sentry.events == []


@pytest.mark.parametrize("make", [requests_error, httpx_error])
def test_our_backend_refusing_is_reported(sentry, make):
    error_reporting.set_enabled(True)
    log_error("Backend said no", make(401, "https://api.wingman-ai.com/api/v1/audio/speech"))
    flush()

    assert len(sentry.events) == 1


def test_a_third_party_server_error_is_reported(sentry):
    error_reporting.set_enabled(True)
    log_error("Provider broke", requests_error(400, "https://api.example-tts.com/v1/speak"))
    flush()

    assert len(sentry.events) == 1


def test_a_provider_sdk_refusal_without_url_is_dropped(sentry):
    cls = type("ApiError", (Exception,), {"__module__": "elevenlabs.core.api_error"})
    exc = cls("status_code: 401, body: invalid api key")
    exc.status_code = 401

    error_reporting.set_enabled(True)
    log_error("Provider said no", exc)
    flush()

    assert sentry.events == []


def test_cores_own_refusal_without_url_is_reported(sentry):
    cls = type("SubscriptionError", (Exception,), {"__module__": "providers.wingman_subscription"})
    exc = cls("unauthorized")
    exc.status_code = 401

    error_reporting.set_enabled(True)
    log_error("Our own 401", exc)
    flush()

    assert len(sentry.events) == 1


def test_mcp_authorization_inside_an_exception_group_is_dropped(sentry):
    from services.mcp_oauth import NeedsAuthorization

    error_reporting.set_enabled(True)
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [NeedsAuthorization("Server")])])
    sentry_sdk.capture_exception(group)
    flush()

    assert sentry.events == []


def test_an_exception_group_with_a_real_bug_is_reported(sentry):
    from services.mcp_oauth import NeedsAuthorization

    error_reporting.set_enabled(True)
    group = ExceptionGroup("outer", [NeedsAuthorization("Server"), ValueError("bug")])
    sentry_sdk.capture_exception(group)
    flush()

    assert len(sentry.events) == 1


def disk_full_windows():
    exc = OSError(28, "There is not enough space on the disk")
    exc.winerror = 112
    return exc


@pytest.mark.parametrize(
    "exc",
    [
        OSError(28, "No space left on device"),
        disk_full_windows(),
        RuntimeError("[enforce fail at inline_container.cc:778] . not enough space on the disk"),
    ],
)
def test_a_full_disk_is_dropped(sentry, exc):
    error_reporting.set_enabled(True)
    log_error("Could not write", exc)
    flush()

    assert sentry.events == []


def test_a_proxy_breaking_certificates_is_dropped(sentry):
    import ssl

    exc = ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
    )
    error_reporting.set_enabled(True)
    log_error("Download failed", exc)
    log_error(
        "Download failed",
        RuntimeError(
            "HTTPSConnectionPool(host='huggingface.co', port=443): Max retries exceeded "
            "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]')))"
        ),
    )
    flush()

    assert sentry.events == []


def test_a_broken_certificate_of_our_own_host_is_reported(sentry):
    error_reporting.set_enabled(True)
    log_error(
        "Backend unreachable",
        RuntimeError(
            "HTTPSConnectionPool(host='api.wingman-ai.com', port=443): "
            "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]')))"
        ),
    )
    flush()

    assert len(sentry.events) == 1


def test_futures_scheduled_during_shutdown_are_dropped(sentry):
    error_reporting.set_enabled(True)
    log_error("Late", RuntimeError("cannot schedule new futures after shutdown"))
    flush()

    assert sentry.events == []


def test_skill_and_context_errors_are_dropped(sentry):
    from services.context_budget import ContextOverflowError
    from wingmen.facade import FacadeError

    error_reporting.set_enabled(True)
    log_error("Skill wrote config", FacadeError("read-only"))
    log_error("Too long", ContextOverflowError("window"))
    flush()

    assert sentry.events == []


def raised_in(filename: str, exc: BaseException) -> BaseException:
    """``exc`` with a traceback whose last frame is in ``filename``."""
    code = compile("raise exc", filename, "exec")
    try:
        exec(code, {"exc": exc})
    except BaseException as e:
        return e
    raise AssertionError("not raised")


def windows_oserror(winerror: int) -> OSError:
    exc = OSError(22, "The parameter is incorrect")
    exc.winerror = winerror
    return exc


@pytest.mark.parametrize("winerror, module", [(10054, "proactor_events.py"), (995, "windows_events.py")])
def test_windows_asyncio_oserrors_are_dropped(sentry, winerror, module):
    error_reporting.set_enabled(True)
    exc = raised_in(f"C:\\Python311\\Lib\\asyncio\\{module}", windows_oserror(winerror))
    sentry_sdk.capture_exception(exc)
    flush()

    assert sentry.events == []


def test_same_oserror_outside_asyncio_is_reported(sentry):
    error_reporting.set_enabled(True)
    sentry_sdk.capture_exception(raised_in("C:\\wingman\\services\\x.py", windows_oserror(10022)))
    flush()

    assert len(sentry.events) == 1


def test_invalid_state_error_from_windows_event_loop_is_dropped(sentry):
    import asyncio

    error_reporting.set_enabled(True)
    sentry_sdk.capture_exception(
        raised_in("C:\\Python311\\Lib\\asyncio\\windows_events.py", asyncio.InvalidStateError("x"))
    )
    flush()

    assert sentry.events == []


def test_event_loop_handler_drops_windows_noise(sentry):
    import asyncio

    error_reporting.set_enabled(True)
    loop = asyncio.new_event_loop()
    try:
        error_reporting.watch_event_loop(loop)
        handler = loop.get_exception_handler()
        noise = raised_in("/usr/lib/python3.11/asyncio/proactor_events.py", windows_oserror(10054))
        handler(loop, {"message": "noise", "exception": noise})
        handler(loop, {"message": "bug", "exception": raised_in("core.py", ValueError("bug"))})
    finally:
        loop.close()
    flush()

    assert [e["exception"]["values"][-1]["type"] for e in sentry.events] == ["ValueError"]


# ─── Session log attachment ───────────────────────────────────────────────────


def test_session_log_is_attached(sentry, tmp_path):
    (tmp_path / "session.log").write_text("line one\nUSER: hello\n", encoding="utf-8")
    error_reporting.set_enabled(True)
    log_error("Failed", ValueError("boom"))
    flush()

    log = sentry.attachments[0][error_reporting.LOG_ATTACHMENT_NAME]
    assert log.decode("utf-8") == "line one\nUSER: hello\n"


def test_each_event_gets_the_log_as_it_is_then(sentry, tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("first\n", encoding="utf-8")
    error_reporting.set_enabled(True)
    log_error("a", ValueError("a"))
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("second\n")
    log_error("b", KeyError("b"))
    flush()

    logs = [a[error_reporting.LOG_ATTACHMENT_NAME].decode() for a in sentry.attachments]
    assert logs == ["first\n", "first\nsecond\n"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_unhandled_exception_gets_the_log_too(sentry, tmp_path):
    (tmp_path / "session.log").write_text("before the crash\n", encoding="utf-8")
    error_reporting.set_enabled(True)

    def crash():
        raise RuntimeError("thread died")

    thread = threading.Thread(target=crash)
    thread.start()
    thread.join()
    flush()

    assert sentry.attachments[0][error_reporting.LOG_ATTACHMENT_NAME] == b"before the crash\n"


def test_long_log_is_cut_to_its_end_at_a_whole_line(sentry, tmp_path, monkeypatch):
    monkeypatch.setattr(error_reporting, "LOG_TAIL_MAX_BYTES", 100)
    lines = [f"line {i:04d} ü" for i in range(50)]
    (tmp_path / "session.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tail = error_reporting._read_log_tail(str(tmp_path / "session.log"), 100)

    assert len(tail.encode("utf-8")) <= 100
    assert tail.endswith("line 0049 ü\n")
    assert tail.splitlines()[0] in lines
    assert "\ufffd" not in tail


def test_attached_log_is_scrubbed(sentry, tmp_path, monkeypatch):
    from services.secret_keeper import SecretKeeper

    keeper = SecretKeeper.__new__(SecretKeeper)
    monkeypatch.setattr(SecretKeeper, "_instance", keeper)
    monkeypatch.setattr(keeper, "secrets", {"custom": "my-own-secret-value"}, raising=False)
    home = os.path.expanduser("~")
    (tmp_path / "session.log").write_text(
        f"key sk-proj-abcdefghijklmnopqrstuv\nvalue my-own-secret-value\n"
        f"Bearer abcdefghijklmnop\nurl https://x.io/v1?key=AIzaSECRET\nfile {home}/config.yaml\n",
        encoding="utf-8",
    )
    error_reporting.set_enabled(True)
    log_error("Failed", ValueError("boom"))
    flush()

    log = sentry.attachments[0][error_reporting.LOG_ATTACHMENT_NAME].decode("utf-8")
    assert "abcdefghijklmnopqrstuv" not in log
    assert "my-own-secret-value" not in log
    assert "abcdefghijklmnop" not in log
    assert "AIzaSECRET" not in log
    assert home not in log
    assert "~/config.yaml" in log


def test_unreadable_log_still_sends_the_event(sentry, monkeypatch, tmp_path):
    (tmp_path / "session.log").mkdir()
    error_reporting.set_enabled(True)
    log_error("Failed", ValueError("boom"))
    flush()

    assert len(sentry.events) == 1
    assert sentry.attachments == [{}]


def test_dropped_event_reads_no_log(sentry, monkeypatch):
    reads = []
    monkeypatch.setattr(error_reporting, "_read_log_tail", lambda *a: reads.append(a))
    error_reporting.set_enabled(True)
    log_error("Offline", ConnectionError("no route"))
    flush()

    assert reads == []


# ─── User folders (WINGMAN-CORE-W) ────────────────────────────────────────────


WINDOWS_TMP = r"C:\Users\larse\AppData\Roaming\ShipBit\WingmanAI\models\x.yaml.23608.tmp"


def test_windows_user_folder_is_scrubbed_from_exception_and_log(sentry, tmp_path):
    exc = PermissionError(13, "Permission denied", WINDOWS_TMP)
    # str() puts the repr of the path in: 'C:\\Users\\larse\\...'
    assert r"C:\\Users\\larse" in str(exc)
    (tmp_path / "session.log").write_text(
        f"Failed to load PocketTTS model: {exc}\nsaving {WINDOWS_TMP}\n", encoding="utf-8"
    )
    error_reporting.set_enabled(True)
    log_error(f"Failed to load PocketTTS model: {exc}", exc)
    flush()

    raw = repr(sentry.events[0])
    log = sentry.attachments[0][error_reporting.LOG_ATTACHMENT_NAME].decode("utf-8")
    assert "larse" not in raw
    assert "larse" not in log
    value = sentry.events[0]["exception"]["values"][-1]["value"]
    assert r"~\\AppData\\Roaming" in value


@pytest.mark.parametrize(
    "text",
    [
        r"C:\Users\larse\AppData",
        r"'C:\\Users\\larse\\AppData'",
        r"C:\\\\Users\\\\larse\\\\AppData",
        "c:/users/larse/AppData",
        r"D:\Documents and Settings\larse\AppData",
        r"C:\Users\Lars Erik\AppData",
        "/home/larse/.cache",
        "/Users/larse/Library",
    ],
)
def test_user_folders_are_scrubbed_in_every_form(text):
    scrubbed = error_reporting._scrub_text(text, [], [])
    assert "lars" not in scrubbed.lower()
    assert scrubbed.lstrip("'").startswith("~")


def test_home_path_is_scrubbed_in_repr_form_and_any_case(monkeypatch):
    monkeypatch.setattr(error_reporting.path, "expanduser", lambda _: r"E:\Profiles\larse")
    homes = error_reporting._home_paths()

    for text in [r"E:\Profiles\larse\x", r"E:\\Profiles\\larse\\x", r"e:\profiles\LARSE\x"]:
        assert "larse" not in error_reporting._scrub_text(text, [], homes).lower()


def test_urls_with_users_in_the_path_stay():
    text = "https://api.example.com/Users/123"
    assert error_reporting._scrub_text(text, [], []) == text

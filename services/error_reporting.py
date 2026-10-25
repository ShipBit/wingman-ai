"""Error reports to Sentry.

What goes out: unhandled exceptions (main thread, worker threads, asyncio
tasks, FastAPI routes) and every ``printr`` error that is logged inside an
``except`` block, with its stack trace. Each event carries the end of the
current session log (``wingman-core.<timestamp>.log``, the last
``LOG_TAIL_MAX_BYTES``) as the attachment ``wingman-core.log``. That log can
contain what the user said to their Wingmen and what they answered; the client
says so where the user turns reporting on. The last few log lines also ride
along as breadcrumbs, but those leave out the conversation types (USER,
POSITIVE, MEMORY, LOCALMODEL).

What never goes out: API keys and other secrets (the stored secrets, Bearer
tokens, ``sk-``/``AIza`` keys and ``?key=`` style parameters are replaced in
the event and in the log), the user's home path and any user folder like
``C:\\Users\\<name>`` or ``/home/<name>``, also in the doubled-backslash form of
exception messages (replaced with ``~``, in the event and in the log), request
bodies and headers, local variables, the hostname and the IP (turned off in
the Sentry project).

Not sent at all: problems on the user's side (wrong key, quota, no internet,
provider down or a model the provider does not know, a full disk, a proxy that
breaks certificates, an MCP server waiting for authorization), mistakes in a
user's own skill code, and asyncio noise from CPython bugs on Windows or from
the interpreter shutting down. See the filters at the end of this module.

The user decides in the client. The choice lives outside the versioned config
folder, in ``WingmanAI/error_reporting.json``: Core reads it before the config
migration has run, and an update must not reset an opt-out to the template
default. As long as the file holds no choice, nothing is sent.

The free Sentry plan shares 5,000 errors a month between Core, client and
backend. Each error is sent once per session, and a session sends at most
``MAX_EVENTS_PER_SESSION`` (20). The plan has 1 GB of attachments a month: at
512 KB a log, that is about 2,000 events with a full log, and a session can
use at most 20 x 512 KB = 10 MB. Most session logs are much shorter than
512 KB. Should the attachment quota run out, Sentry drops the attachments, not
the events.
"""

import json
import os
import platform
import re
import sys
import threading
import uuid
from os import path
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlparse

from services.file import get_users_dir
from services.system_manager import LOCAL_VERSION

SENTRY_DSN = "https://fc500b8581e7b6abd3a27e02b0718789@o4512134262030336.ingest.de.sentry.io/4512134275727440"
STATE_FILE = "error_reporting.json"
MAX_EVENTS_PER_SESSION = 20
BREADCRUMB_MAX_CHARS = 160
LOG_TAIL_MAX_BYTES = 512 * 1024
LOG_ATTACHMENT_NAME = "wingman-core.log"

# Log types that may carry what the user said, what the AI answered, or what
# it remembers about the user. They never become breadcrumbs.
_PRIVATE_LOG_TYPES = {"user", "positive", "memory", "localmodel"}

# Problems on the user's side (wrong key, no internet, provider down, quota).
# They are errors for the user but not bugs in Core, and they would use up the
# quota within days. Matched by class name so no provider SDK is imported here.
_IGNORED_EXCEPTIONS = {
    "AuthenticationError",
    "PermissionDeniedError",
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ServiceUnavailableError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "ClientConnectorError",
    "ServerDisconnectedError",
    "CancelledError",
    "KeyboardInterrupt",
    "WebSocketDisconnect",
    # A skill wrote to the read-only Wingman config or used a removed API: a
    # mistake in the skill's code, shown to its author (WINGMAN-CORE-N).
    "FacadeError",
    # The conversation no longer fits the model's context window. Core shows
    # it to the user; it is a usage limit, not a bug.
    "ContextOverflowError",
    # An OAuth MCP server waits for the user to press Authorize. It arrives
    # inside the ExceptionGroup of the MCP transport.
    "NeedsAuthorization",
}

# HTTP status codes of the openai SDK that mean the user's own provider said
# no: bad or missing key (401, 403), no credit (402), unknown model or path
# (404), timeout (408), conflict (409), request too big (413), rate limit
# (429). The openai SDK only talks to providers the user configured (Wingman
# Pro goes through ``requests``), so this never hides a backend error. Other
# 400s stay: they can be a payload Core built wrong.
_IGNORED_OPENAI_STATUS = {401, 402, 403, 404, 408, 409, 413, 429}
# 400s of the openai SDK that are the user's setup, not a payload Core built
# wrong: an unknown model, a wrong key (some providers send it as 400), a local
# server without a model loaded, an image sent to a model without vision.
_OPENAI_USER_400_HINTS = (
    "not found",
    "does not exist",
    "model_not_found",
    "incorrect api key",
    "no models loaded",
    "does not support image",
)

# Any other HTTP client or provider SDK: a bad key (401, 403), no credit (402)
# or a rate limit (429) from a service the user configured. Our own backend
# (wingman-ai.com) stays reported: a 401 there can be a bug in Core's sign-in.
_IGNORED_THIRD_PARTY_STATUS = {401, 402, 403, 429}
_OWN_DOMAIN = "wingman-ai.com"
# Modules whose exceptions are Core's own, not a provider SDK's.
_CORE_MODULES = {
    "api",
    "builtins",
    "hud_server",
    "main",
    "providers",
    "services",
    "skills",
    "wingman_core",
    "wingmen",
}

# The disk is full: ENOSPC and ERROR_DISK_FULL, and the text libraries put in
# their own exceptions for it.
_DISK_FULL_ERRNOS = {28}
_DISK_FULL_WINERRORS = {112}
_DISK_FULL_HINTS = (
    "no space left on device",
    "not enough space",
    "not enough free disk space",
)

# A future submitted to an executor while Python shuts down: nothing is lost,
# the process is ending.
_SHUTDOWN_HINTS = ("cannot schedule new futures after shutdown",)

# Windows error codes the asyncio proactor raises for sockets that were closed
# under it: WSAEINVAL (10022), WSAECONNRESET (10054) and
# ERROR_OPERATION_ABORTED (995). CPython bugs, nothing Core can fix
# (WINGMAN-CORE-3, WINGMAN-CORE-A).
_IGNORED_WINERRORS = {10022, 10054, 995}

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(sk-(?:ant-|proj-)?)[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(AIza)[A-Za-z0-9_-]{20,}"),
    re.compile(
        r'([?&][a-zA-Z_]*(?:key|token|secret|password|auth)[a-zA-Z_]*=)[^&\s"\']+',
        re.IGNORECASE,
    ),
]

# User folders in paths: the folder name is often the person's name. The home
# of this machine is replaced first (_home_paths); these catch the rest, also
# in the repr form Python puts in OSError messages, with doubled backslashes,
# and doubled again when that text was escaped once more (JSON in a log line).
_SEP = r"(?:\\{1,4}|/)"
_USER_DIR_PATTERNS = [
    re.compile(
        r"\b[A-Za-z]:" + _SEP + r"(?:Users|Documents and Settings)" + _SEP
        # Greedy up to the next separator or quote: names can have spaces.
        + r"[^\\/:*?\"'<>|\r\n]+",
        re.IGNORECASE,
    ),
    re.compile(r"(?<![\w.:/~])/(?:Users|home)/[^/\s'\"]+"),
]

_lock = threading.Lock()
_started = False
_enabled: Optional[bool] = None
_install_id: Optional[str] = None
_user_id: Optional[str] = None
_channel: Optional[str] = None
_sent_keys: set[str] = set()
_tag_provider: Optional[Callable[[], dict]] = None
_sent_count = 0


def _state_path() -> str:
    return path.join(get_users_dir(), STATE_FILE)


def _read_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict):
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _is_allowed_build() -> bool:
    """Packaged builds report. A run from source only does with WINGMAN_SENTRY=1,
    so development errors do not use up the quota."""
    return getattr(sys, "frozen", False) or os.environ.get("WINGMAN_SENTRY") == "1"


def init():
    """Called once at startup, before the config is loaded, so a crash in the
    migration is reported too."""
    global _enabled, _install_id, _channel
    state = _read_state()
    _install_id = state.get("install_id")
    _channel = state.get("channel")
    enabled = state.get("enabled")
    _enabled = enabled if isinstance(enabled, bool) else None
    if _enabled:
        _start()


def get_enabled() -> Optional[bool]:
    """True or False once the user has chosen, None before that."""
    return _enabled


def set_enabled(enabled: bool):
    global _enabled, _install_id, _started
    state = _read_state()
    state["enabled"] = enabled
    if not state.get("install_id"):
        state["install_id"] = str(uuid.uuid4())
    _install_id = state["install_id"]
    _write_state(state)
    _enabled = enabled

    if enabled and not _started:
        _start()
    elif not enabled and _started:
        import sentry_sdk

        sentry_sdk.get_client().close(timeout=2)
        _started = False


def _start():
    global _started, _install_id
    if _started or not _is_allowed_build():
        return
    if not _install_id:
        state = _read_state()
        state["install_id"] = str(uuid.uuid4())
        _write_state(state)
        _install_id = state["install_id"]

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            release=f"wingman-core@{LOCAL_VERSION}",
            environment="production" if getattr(sys, "frozen", False) else "development",
            server_name="wingman-core",
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            traces_sample_rate=0,
            auto_session_tracking=False,
            attach_stacktrace=True,
            max_breadcrumbs=30,
            # The auto-enabled integrations include the OpenAI, Anthropic, Google
            # and MCP ones, which record prompts. Only the web framework is wanted.
            auto_enabling_integrations=False,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
                # printr sends stderr to a logger at ERROR level; with the default
                # integration every library warning would become an event.
                # Breadcrumbs come from printr instead (add_breadcrumb below).
                LoggingIntegration(level=None, event_level=None),
            ],
            before_send=_before_send,
            before_breadcrumb=_before_breadcrumb,
        )
        # The global scope: user and tags set on the current scope would only
        # stick to the request (or websocket) that happens to be running.
        scope = sentry_sdk.get_global_scope()
        scope.set_user({"id": _user_id or _install_id})
        scope.set_tag("install_id", _install_id)
        scope.set_tag("os", platform.system())
        scope.set_tag("os_version", platform.release())
        scope.set_tag("arch", platform.machine())
        if _channel:
            scope.set_tag("channel", _channel)
        _started = True
    except Exception as e:
        # Error reporting must never be the reason Core does not start.
        sys.__stderr__.write(f"Sentry init failed: {e}\n")


def set_user(user_id: Optional[str]):
    """The Supabase user ID while signed in, the install ID otherwise. The ID
    alone; email and name stay in the backend. Kept for a later start, in case
    the user turns reporting on after signing in."""
    global _user_id
    _user_id = user_id
    if not _started:
        return
    import sentry_sdk

    sentry_sdk.get_global_scope().set_user({"id": user_id or _install_id})


def set_channel(channel: str):
    """The update channel (stable, unstable) the client was installed from.
    Core cannot tell by itself, so the client sends it. Stored, so a crash on
    the next start, before the client connects, carries it too."""
    global _channel
    _channel = channel
    state = _read_state()
    if state.get("channel") != channel:
        state["channel"] = channel
        _write_state(state)
    if _started:
        import sentry_sdk

        sentry_sdk.get_global_scope().set_tag("channel", channel)


def set_tag_provider(provider: Callable[[], dict]):
    """Tags read when an event goes out (STT provider, plan, ...). They change
    while Core runs, so setting them once at startup would go stale."""
    global _tag_provider
    _tag_provider = provider


def add_breadcrumb(text: str, log_type: str, source_name: str = ""):
    """The log lines before an error. Conversation types are left out and each
    line is cut short."""
    if not _started or log_type in _PRIVATE_LOG_TYPES:
        return
    import sentry_sdk

    sentry_sdk.add_breadcrumb(
        category=source_name or "core",
        message=str(text)[:BREADCRUMB_MAX_CHARS],
        level="error" if log_type == "error" else "info",
    )


def watch_event_loop(loop):
    """Reports exceptions from asyncio tasks nobody awaited ("Task exception
    was never retrieved"). Sentry's own asyncio integration also reports task
    exceptions the awaiting code handles, so it is not used."""
    previous = loop.get_exception_handler()

    def handler(loop, context):
        exc = context.get("exception")
        if _started and exc is not None:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def capture_logged_error(text: str, source_name: str = ""):
    """An error printr logged. Reported only when it was logged inside an
    ``except`` block, with that exception: a plain error message without one is
    almost always an expected problem ("no API key") shown to the user."""
    if not _started:
        return
    exc = sys.exc_info()[1]
    if exc is None:
        return
    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        scope.set_context(
            "log", {"message": str(text)[:500], "source": source_name or "core"}
        )
        if source_name:
            scope.set_tag("source", source_name)
        sentry_sdk.capture_exception(exc)


# ─── Filters ──────────────────────────────────────────────────────────────────


def _is_ignored(exc_type_names: list[str]) -> bool:
    return any(name in _IGNORED_EXCEPTIONS for name in exc_type_names)


def _hint_exception(hint: dict) -> Optional[BaseException]:
    exc_info = hint.get("exc_info")
    if not exc_info or len(exc_info) < 2:
        return None
    exc = exc_info[1]
    return exc if isinstance(exc, BaseException) else None


def _is_openai_user_error(exc: BaseException) -> bool:
    """The user's own provider refused the request (see _IGNORED_OPENAI_STATUS)."""
    if not type(exc).__module__.startswith("openai"):
        return False
    status = getattr(exc, "status_code", None)
    if status in _IGNORED_OPENAI_STATUS:
        return True
    if status == 400:
        text = f"{getattr(exc, 'message', '') or ''} {exc}".lower()
        return any(hint in text for hint in _OPENAI_USER_400_HINTS)
    return False


def _http_status(exc: BaseException) -> Optional[int]:
    """The HTTP status of an HTTP client or SDK error: ``requests`` and
    ``httpx`` keep it on ``response``, most SDKs on ``status_code``."""
    response = getattr(exc, "response", None)
    for value in (
        getattr(response, "status_code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _http_host(exc: BaseException) -> Optional[str]:
    """The host the failed request went to, when the error knows it."""
    for owner in (getattr(exc, "response", None), exc):
        if owner is None:
            continue
        try:
            request = getattr(owner, "request", None)
        except Exception:
            # httpx raises when a response has no request attached.
            request = None
        for url in (getattr(owner, "url", None), getattr(request, "url", None)):
            if url is None:
                continue
            host = getattr(url, "host", None) or urlparse(str(url)).hostname
            if host:
                return str(host).lower()
    return None


def _is_own_host(host: str) -> bool:
    return host == _OWN_DOMAIN or host.endswith("." + _OWN_DOMAIN)


def _is_third_party_refusal(exc: BaseException) -> bool:
    """A service the user configured refused the key or the quota (see
    _IGNORED_THIRD_PARTY_STATUS)."""
    if _http_status(exc) not in _IGNORED_THIRD_PARTY_STATUS:
        return False
    host = _http_host(exc)
    if host:
        return not _is_own_host(host)
    # No URL on the error: only an SDK's own exception counts, never one of
    # Core's, whose status may well come from our backend.
    module = (type(exc).__module__ or "").split(".")[0]
    return module not in _CORE_MODULES and module not in ("requests", "httpx")


def _is_disk_full(exc: BaseException) -> bool:
    if isinstance(exc, OSError) and (
        exc.errno in _DISK_FULL_ERRNOS
        or getattr(exc, "winerror", None) in _DISK_FULL_WINERRORS
    ):
        return True
    text = str(exc).lower()
    return any(hint in text for hint in _DISK_FULL_HINTS)


def _is_cert_verification_failure(exc: BaseException) -> bool:
    """A proxy or antivirus on the user's network replaced the certificate
    (seen on Hugging Face downloads). Our own hosts stay reported: a broken
    certificate there would be ours to fix."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    text = str(exc)
    if "SSLCertVerificationError" not in names and "CERTIFICATE_VERIFY_FAILED" not in text:
        return False
    return _OWN_DOMAIN not in text.lower()


def _is_shutdown_noise(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, RuntimeError) and any(h in text for h in _SHUTDOWN_HINTS)


def _last_frame_file(exc: BaseException) -> str:
    tb = exc.__traceback__
    if tb is None:
        return ""
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code.co_filename.replace("\\", "/").lower()


def _is_windows_asyncio_noise(exc: BaseException) -> bool:
    """CPython bugs in the Windows event loop (see _IGNORED_WINERRORS)."""
    names = [cls.__name__ for cls in type(exc).__mro__]
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in _IGNORED_WINERRORS:
        filename = _last_frame_file(exc)
        return "asyncio" in filename and (
            "proactor_events" in filename or "windows_events" in filename
        )
    if "InvalidStateError" in names:
        filename = _last_frame_file(exc)
        return "asyncio" in filename and "windows_events" in filename
    return False


def _leaves(exc: BaseException) -> Iterator[BaseException]:
    """The exceptions inside an ExceptionGroup, however deep (anyio task groups
    wrap a transport's error in one or more), or the exception itself."""
    nested = getattr(exc, "exceptions", None)
    if isinstance(exc, BaseExceptionGroup) and nested:
        for inner in nested:
            yield from _leaves(inner)
    else:
        yield exc


def _is_noise_leaf(exc: BaseException) -> bool:
    return (
        _is_ignored([cls.__name__ for cls in type(exc).__mro__])
        or _is_openai_user_error(exc)
        or _is_windows_asyncio_noise(exc)
        or _is_third_party_refusal(exc)
        or _is_disk_full(exc)
        or _is_cert_verification_failure(exc)
        or _is_shutdown_noise(exc)
    )


def _is_noise(exc: Optional[BaseException]) -> bool:
    """Noise when the exception is, or for a group when every exception in
    it is: one real bug among them still gets the group reported."""
    if exc is None:
        return False
    try:
        return all(_is_noise_leaf(leaf) for leaf in _leaves(exc))
    except Exception:
        return False


def _exception_type_names(hint: dict) -> list[str]:
    exc_info = hint.get("exc_info")
    if not exc_info or exc_info[0] is None:
        return []
    return [cls.__name__ for cls in exc_info[0].__mro__]


def _dedup_key(event: dict) -> str:
    """Same exception type at the same place in the code = same error."""
    values = (event.get("exception") or {}).get("values") or []
    if values:
        last = values[-1]
        frames = (last.get("stacktrace") or {}).get("frames") or []
        top = frames[-1] if frames else {}
        return f"{last.get('type')}|{top.get('module')}|{top.get('function')}|{top.get('lineno')}"
    message = event.get("message") or (event.get("logentry") or {}).get("message") or ""
    return re.sub(r"\d+", "#", str(message))[:120]


def _secret_values() -> list[str]:
    try:
        from services.secret_keeper import SecretKeeper

        # The instance, not SecretKeeper(): a crash before startup created it
        # must not be the moment it loads the secrets file.
        keeper = SecretKeeper._instance
        secrets = getattr(keeper, "secrets", None) or {}
        return [v for v in secrets.values() if isinstance(v, str) and len(v) >= 8]
    except Exception:
        return []


def _home_paths() -> list[str]:
    home = path.expanduser("~")
    if not home or home == "~":
        return []
    variants = {
        home,
        home.replace("\\", "/"),
        home.replace("/", "\\"),
        home.replace("/", "\\").replace("\\", "\\\\"),
    }
    return sorted(variants, key=len, reverse=True)


def _scrub_text(text: str, secrets: list[str], homes: list[str]) -> str:
    for value in secrets:
        if value in text:
            text = text.replace(value, "[secret]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[redacted]", text)
    for home in homes:
        # Windows paths are not case sensitive (c:\\users\\Name).
        text = re.sub(re.escape(home), "~", text, flags=re.IGNORECASE)
    for pattern in _USER_DIR_PATTERNS:
        text = pattern.sub("~", text)
    return text


def _scrub(obj: Any, secrets: list[str], homes: list[str]) -> Any:
    if isinstance(obj, str):
        return _scrub_text(obj, secrets, homes)
    if isinstance(obj, dict):
        return {k: _scrub(v, secrets, homes) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, secrets, homes) for v in obj]
    return obj


def _log_file_path() -> Optional[str]:
    try:
        from services.printr import Printr

        return Printr.log_file_path
    except Exception:
        return None


def _read_log_tail(file_path: Optional[str], max_bytes: int = LOG_TAIL_MAX_BYTES) -> Optional[str]:
    """The last ``max_bytes`` of the log, starting at a whole line. None when
    there is no log or it cannot be read."""
    if not file_path:
        return None
    try:
        with open(file_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read(max_bytes)
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    if start > 0:
        # The first line is cut off (maybe in the middle of a character).
        newline = text.find("\n")
        text = text[newline + 1 :] if newline != -1 else ""
    return text


def _attach_log(hint: dict, secrets: list[str], homes: list[str]):
    """Adds the scrubbed session log to the event. The SDK builds the envelope
    from ``hint["attachments"]`` after before_send, so an attachment added here
    goes out with this event only, read fresh when it is sent."""
    try:
        from sentry_sdk.attachments import Attachment

        text = _read_log_tail(_log_file_path())
        if not text:
            return
        attachments = hint.get("attachments")
        if not isinstance(attachments, list):
            return
        attachments.append(
            Attachment(
                bytes=_scrub_text(text, secrets, homes).encode("utf-8"),
                filename=LOG_ATTACHMENT_NAME,
                content_type="text/plain",
            )
        )
    except Exception:
        # A log that cannot be attached must not stop the report.
        pass


def _before_breadcrumb(crumb: dict, hint: dict) -> Optional[dict]:
    # HTTP breadcrumbs from the stdlib integration: host and path are useful,
    # the query string can hold an API key (Gemini puts it in ?key=).
    data = crumb.get("data")
    if isinstance(data, dict):
        data.pop("http.query", None)
        data.pop("http.fragment", None)
    return crumb


def _before_send(event: dict, hint: dict) -> Optional[dict]:
    global _sent_count
    if not _enabled:
        return None
    if _is_ignored(_exception_type_names(hint)) or _is_noise(_hint_exception(hint)):
        return None

    with _lock:
        key = _dedup_key(event)
        if key in _sent_keys or _sent_count >= MAX_EVENTS_PER_SESSION:
            return None
        _sent_keys.add(key)
        _sent_count += 1

    if _tag_provider is not None:
        try:
            event.setdefault("tags", {}).update(
                {k: str(v) for k, v in _tag_provider().items() if v is not None}
            )
        except Exception:
            pass

    # Only method and URL of a failing route; headers and body can hold keys.
    request = event.get("request")
    if isinstance(request, dict):
        event["request"] = {
            "method": request.get("method"),
            "url": request.get("url"),
        }

    secrets, homes = _secret_values(), _home_paths()
    _attach_log(hint, secrets, homes)
    return _scrub(event, secrets, homes)

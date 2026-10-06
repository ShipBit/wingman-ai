"""Error reports to Sentry.

What goes out: unhandled exceptions (main thread, worker threads, FastAPI
routes) and every ``printr`` error that is logged inside an ``except`` block,
with its stack trace. The last few non-conversation log lines ride along as
breadcrumbs. What never goes out: conversation text (USER, POSITIVE, MEMORY,
LOCALMODEL), request bodies, local variables, the hostname, the IP (turned off
in the Sentry project), secrets and the user's home path.

The user decides in the client. The choice lives outside the versioned config
folder, in ``WingmanAI/error_reporting.json``: Core reads it before the config
migration has run, and an update must not reset an opt-out to the template
default. As long as the file holds no choice, nothing is sent.

The free Sentry plan shares 5,000 errors a month between Core, client and
backend. Each error is sent once per session, and a session sends at most
``MAX_EVENTS_PER_SESSION``.
"""

import json
import os
import platform
import re
import sys
import threading
import uuid
from os import path
from typing import Any, Callable, Optional

from services.file import get_users_dir
from services.system_manager import LOCAL_VERSION

SENTRY_DSN = "https://fc500b8581e7b6abd3a27e02b0718789@o4512134262030336.ingest.de.sentry.io/4512134275727440"
STATE_FILE = "error_reporting.json"
MAX_EVENTS_PER_SESSION = 20
BREADCRUMB_MAX_CHARS = 160

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
}

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(sk-(?:ant-|proj-)?)[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(AIza)[A-Za-z0-9_-]{20,}"),
    re.compile(
        r'([?&][a-zA-Z_]*(?:key|token|secret|password|auth)[a-zA-Z_]*=)[^&\s"\']+',
        re.IGNORECASE,
    ),
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
    return sorted({home, home.replace("\\", "/"), home.replace("/", "\\")}, key=len, reverse=True)


def _scrub_text(text: str, secrets: list[str], homes: list[str]) -> str:
    for value in secrets:
        if value in text:
            text = text.replace(value, "[secret]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[redacted]", text)
    for home in homes:
        text = text.replace(home, "~")
    return text


def _scrub(obj: Any, secrets: list[str], homes: list[str]) -> Any:
    if isinstance(obj, str):
        return _scrub_text(obj, secrets, homes)
    if isinstance(obj, dict):
        return {k: _scrub(v, secrets, homes) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, secrets, homes) for v in obj]
    return obj


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
    if _is_ignored(_exception_type_names(hint)):
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

    return _scrub(event, _secret_values(), _home_paths())

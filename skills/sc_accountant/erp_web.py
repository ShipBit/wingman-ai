"""Local ERP dashboard with optional session-protected phone sharing."""

from __future__ import annotations

import json
import ipaddress
import logging
import re
from pathlib import Path
import socket
import secrets
import threading
import time

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)
UI = Path(__file__).with_name("erp_ui")
SECTIONS = {
    "overview",
    "operations",
    "journal",
    "inventory",
    "production",
    "assets",
    "plans",
    "attention",
    "evidence",
    "reports",
    "history",
}
ACTIONS = {
    "set_mode",
    "start_operation",
    "finish_operation",
    "record_cash",
    "buy_stock",
    "sell_stock",
    "reserve_stock",
    "transfer_stock",
    "lose_stock",
    "start_production",
    "complete_production",
    "collect_production",
    "register_asset",
    "update_asset",
    "set_plan",
    "reconcile_wallet",
    "resolve_event",
    "reverse_entry",
    "new_period",
    "set_stock_cost",
    "resolve_cost",
    "allocate_sale",
    "assign_entry",
}


def create_app(engine, *, lan_host="", access_token="") -> FastAPI:
    """Create an app without starting a listener or taking ownership of engine."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    if bool(lan_host) != bool(access_token):
        raise ValueError("Phone sharing requires both an address and a session token")

    @app.middleware("http")
    async def protect(request: Request, call_next):
        # Wingman's frozen build omits Starlette's optional trustedhost module.
        # Keep the local-host boundary here instead of adding a dependency.
        host = request.headers.get("host", "")
        local_host = re.fullmatch(
            r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?", host, re.IGNORECASE
        )
        shared_host = lan_host and re.fullmatch(re.escape(lan_host) + r"(?::[0-9]{1,5})?", host)
        if not (local_host or shared_host):
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        # A phone gets a session from the QR, without exposing the records to
        # every machine on the network. Host spoofing never bypasses this check.
        local_client = request.client and request.client.host in {"127.0.0.1", "::1"}
        if lan_host and not (local_host and local_client):
            supplied = request.query_params.get("share", "")
            if request.method == "GET" and request.url.path == "/" and secrets.compare_digest(supplied.encode(), access_token.encode()):
                response = RedirectResponse("/", status_code=303,
                    headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
                response.set_cookie("sc_accountant_session", access_token, httponly=True, samesite="strict")
                return response
            if not secrets.compare_digest(request.cookies.get("sc_accountant_session", "").encode(), access_token.encode()):
                return JSONResponse({"detail": "Scan Accountant's QR code in Wingman to open this dashboard."}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin", "")
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if (
                origin != expected
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                return JSONResponse(
                    {"detail": "Open this dashboard directly to make changes."},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            }
        )
        return response

    @app.get("/")
    def index():
        return FileResponse(UI / "index.html")

    @app.get("/app.js")
    def script():
        return FileResponse(UI / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet():
        return FileResponse(UI / "style.css", media_type="text/css")

    @app.get("/api/erp/{section}")
    def view(
        section: str,
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        operation_id: str | None = None,
    ):
        if section not in SECTIONS:
            raise HTTPException(404, "Unknown section")
        filters = {"limit": limit, "offset": offset}
        if operation_id:
            filters["operation_id"] = operation_id
        try:
            return engine.view(section, **filters)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            logger.exception("ERP dashboard read failed")
            raise HTTPException(500, "Unable to read records. See the application log.")

    @app.post("/api/erp/command")
    async def command(request: Request):
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip()
            != "application/json"
        ):
            raise HTTPException(415, "A JSON request is required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, "Request is too large")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("action"), str)
            or payload["action"] not in ACTIONS
        ):
            raise HTTPException(400, "Unknown command")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise HTTPException(400, "Command data must be an object")
        try:
            return engine.command(payload["action"], data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            logger.exception("ERP dashboard command failed")
            raise HTTPException(
                500, "Unable to save this change. See the application log."
            )

    return app


class ERPServer:
    """Background listener; phone sharing is explicit and limited to a QR session."""

    def __init__(self, engine, port: int = 7863, *, share_on_lan: bool = False):
        self._lan_host = ""
        if share_on_lan:
            if __package__:
                from .erp_sharing import get_lan_ip
            else:
                from erp_sharing import get_lan_ip
            address = get_lan_ip()
            if address:
                parsed = ipaddress.ip_address(address)
                if parsed.is_private and not (parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast):
                    self._lan_host = address
        self._access_token = secrets.token_urlsafe(18) if self._lan_host else ""
        self.app = create_app(engine, lan_host=self._lan_host, access_token=self._access_token)
        self.port = int(port)
        self._thread = None
        self._server = None
        self._socket = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def lan_url(self):
        if not self._lan_host:
            return ""
        return f"http://{self._lan_host}:{self.port}/?share={self._access_token}"

    def start(self):
        if self._thread and self._thread.is_alive():
            return self.url
        import uvicorn

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            bind_host = "0.0.0.0" if self._lan_host else "127.0.0.1"
            listener.bind((bind_host, self.port))
            listener.listen(128)
            self.port = listener.getsockname()[1]
            self._socket = listener
            self._server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host=bind_host,
                    proxy_headers=False,
                    port=self.port,
                    log_level="warning",
                    access_log=False,
                    ws="none",
                )
            )
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [listener]},
                name="sc-accountant-erp",
                daemon=True,
            )
            self._thread.start()
            deadline = time.monotonic() + 5
            while not self._server.started:
                if not self._thread.is_alive() or time.monotonic() > deadline:
                    self.stop()
                    raise RuntimeError("ERP dashboard did not start")
                time.sleep(0.02)
            return self.url
        except Exception:
            listener.close()
            raise

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("ERP dashboard is still stopping")
        if self._socket:
            self._socket.close()
        self._thread = self._server = self._socket = None

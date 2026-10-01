"""Star Citizen Accountant: personal books, filled from the game log.

Written by Mallachi as SC Accountant. The engine (erp*.py) owns accounting.
Core's log reader owns the game log (`self.wingman.sc_gamelog`); this skill
books what it recorded and exposes three bounded, on-demand tools.

There is one set of books for the whole process, however many Wingmen have
the skill on: one database, one capture and one dashboard on one port.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
import secrets
import webbrowser

from skills.skill_base import Skill, tool
from skills.sc_accountant.erp_feed import capture_once


def compact_report(value: Any, budget: int = 3500) -> str:
    """Keep valid JSON and explicit omissions; never slice JSON mid-document."""
    omitted = False

    def reduce(item, depth=0):
        nonlocal omitted
        if isinstance(item, dict):
            if depth >= 6:
                omitted = True
                return "Details available in dashboard"
            keys = list(item)[:24]
            omitted |= len(keys) < len(item)
            return {str(key): reduce(item[key], depth + 1) for key in keys}
        if isinstance(item, (list, tuple)):
            omitted |= len(item) > 5
            return [reduce(child, depth + 1) for child in item[:5]]
        if isinstance(item, str) and len(item) > 240:
            omitted = True
            return item[:240] + "…"
        return item

    data = reduce(value)
    result = data if isinstance(data, dict) else {"data": data}
    result = dict(result)
    if omitted:
        result.update(
            truncated=True, hint="Open the dashboard for all records and details."
        )
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) <= budget:
        return encoded
    # Too many independent fields: retain a small preview and a clear indicator.
    result = {
        "mode": result.get("mode"),
        "truncated": True,
        "hint": "Open the dashboard for this detailed report.",
        "preview": encoded[: max(0, budget // 2)],
    }
    return json.dumps(result, ensure_ascii=False)


def normalized_mode(value: Any) -> str:
    mapping = {"casual": "simple", "engaged": "advanced", "industrial": "advanced"}
    mode = mapping.get(str(value).lower(), str(value or "simple").lower())
    if mode not in {"simple", "advanced"}:
        raise ValueError("Choose simple or advanced mode.")
    return mode


CAPTURE_DELAY_SECONDS = 2
"""Wait this long after an event before booking, so a burst is one capture."""
DIALOG_ONCE = "SC_Accountant.dashboard"


class _Books:
    """The shared engine, capture and dashboard.

    The first skill that prepares opens them, the last one that unloads closes
    them. A plain get_instance/destroy_instance pair would close them under
    every other Wingman that still uses them."""

    _instance: "_Books | None" = None
    _lock: asyncio.Lock | None = None

    def __init__(self, directory: Path, gamelog) -> None:
        self.directory = directory
        self.gamelog = gamelog
        self.users = 0
        self.engine = None
        self.server = None
        self.status = "Starting."
        self._capture_task = None
        self._subscription = None
        self._dirty = asyncio.Event()
        self._engine_lock = asyncio.Lock()
        self._dashboard_lock = asyncio.Lock()  # Two Wingmen starting at once.

    @classmethod
    async def acquire(cls, directory: Path, gamelog) -> "_Books":
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is None:
                books = cls(directory, gamelog)
                await books._open()
                cls._instance = books
            cls._instance.users += 1
            return cls._instance

    async def release(self) -> None:
        async with _Books._lock:
            self.users -= 1
            if self.users > 0:
                return
            _Books._instance = None
            await self._close()

    async def run(self, fn, *args, **kwargs):
        """Engine work runs off the event loop, one call at a time."""
        async with self._engine_lock:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def _open(self) -> None:
        from skills.sc_accountant.erp import ERP

        self.directory.mkdir(parents=True, exist_ok=True)
        self.engine = await asyncio.to_thread(ERP, self.directory / "erp.sqlite3")
        self._subscription = self.gamelog.on("*", lambda _event: self._dirty.set())
        self._dirty.set()  # Book what the log recorded while nobody was listening.
        self._capture_task = asyncio.create_task(self._capture_loop(), name="sc-accountant-capture")

    async def _close(self) -> None:
        if self._subscription:
            self._subscription.unsubscribe()
        if self._capture_task:
            self._capture_task.cancel()
            await asyncio.gather(self._capture_task, return_exceptions=True)
        if self.server is not None:
            await asyncio.to_thread(self.server.stop)
            self.server = None
        if self.engine is not None:
            async with self._engine_lock:
                await asyncio.to_thread(self.engine.close)
            self.engine = None

    async def _capture_loop(self) -> None:
        while True:
            await self._dirty.wait()
            await asyncio.sleep(CAPTURE_DELAY_SECONDS)
            self._dirty.clear()
            try:
                await self.capture()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.status = "Capture needs attention: " + str(error)[:300]
                await self.run(self.engine.set_feed_error, self.status)

    async def capture(self) -> None:
        database = self.gamelog.database_path
        if database is None:
            self.status = (
                "The Star Citizen log is switched off in the settings. Manual entry is available."
            )
            return
        while True:
            page = await self.run(capture_once, self.engine, Path(database))
            if not page.get("has_more"):
                break
        self.status = "Capturing from the Star Citizen log."

    async def dashboard(self, port: int):
        """Start the dashboard once; later calls return the running one."""
        async with self._dashboard_lock:
            return await self._start_dashboard(port)

    async def _start_dashboard(self, port: int):
        if self.server is None:
            from skills.sc_accountant.erp_web import ERPServer

            if not 1024 <= port <= 65535:
                raise ValueError("Dashboard port must be between 1024 and 65535.")
            server = ERPServer(
                self.engine, port=port, share_on_lan=True, access_token=self._token()
            )
            try:
                await asyncio.to_thread(server.start)
            except Exception:
                await asyncio.to_thread(server.stop)
                raise
            self.server = server
        return self.server

    def _token(self) -> str:
        """The phone link's key, kept so a scanned QR code keeps working."""
        path = self.directory / "dashboard_token"
        try:
            token = path.read_text(encoding="utf-8").strip()
            if len(token) >= 24:
                return token
        except OSError:
            pass
        token = secrets.token_urlsafe(18)
        path.write_text(token, encoding="utf-8")
        return token


class SC_Accountant(Skill):
    """Personal books with capture from the game log and on-demand voice access."""

    def __init__(self, config, settings=None, wingman=None):
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._books: _Books | None = None

    def _property(self, name, default=None):
        value = self.retrieve_custom_property_value(name, [])
        return default if value is None else value

    def _mode(self):
        return normalized_mode(self._property("complexity_layer", "simple"))

    async def prepare(self):
        await super().prepare()
        if self._books is not None:
            return
        self._books = await _Books.acquire(
            Path(self.get_generated_files_dir()), self.wingman.sc_gamelog
        )
        await self._books.run(
            self._books.engine.command, "apply_config_mode", {"mode": self._mode()}
        )
        try:
            server = await self._books.dashboard(int(self._property("dashboard_port", 7863)))
            await self._show_dashboard(server, once=True)
        except Exception as error:
            self.log.warning("Accountant dashboard unavailable: " + str(error)[:300])

    async def unload(self):
        if self._books is not None:
            books, self._books = self._books, None
            await books.release()
        await super().unload()

    async def _show_dashboard(self, server, *, once: bool) -> None:
        from skills.sc_accountant.erp_sharing import qr_png_base64

        qr = await asyncio.to_thread(qr_png_base64, server.lan_url) if server.lan_url else None
        text = (
            f"Scan the code with your phone, or open [{server.url}]({server.url}) "
            "on this computer."
            if qr
            else f"Open [{server.url}]({server.url}) on this computer."
        )
        await self.wingman.ui.show_dialog(
            "Accountant dashboard",
            text,
            image=f"data:image/png;base64,{qr}" if qr else None,
            once=DIALOG_ONCE if once else None,
        )

    async def _ready(self):
        if self._books is None or self._books.engine is None:
            raise RuntimeError("Accountant is not ready. Load the skill first.")
        await self._books.run(
            self._books.engine.command, "apply_config_mode", {"mode": self._mode()}
        )

    @tool(
        description="Read ERP overview or a section. Use help for action names, help:ACTION for fields.",
        wait_response=True,
    )
    async def erp_report(self, section: str = "overview") -> str:
        """Args:
        section: overview, operations, inventory, jobs, assets, finance, planning, attention, feed, help, or help:ACTION.
        """
        try:
            await self._ready()
            if section.startswith("help:"):
                action = section.split(":", 1)[1]
                help_result = await self._books.run(self._books.engine.view, "help")
                if action not in help_result["data"]:
                    raise ValueError(
                        "Unknown action. Read help for supported action names."
                    )
                result = {"action": action, "fields": help_result["data"][action]}
            elif section == "help":
                help_result = await self._books.run(self._books.engine.view, "help")
                names = list(help_result["data"])
                result = {
                    "actions": {
                        str(i // 5 + 1): ", ".join(names[i : i + 5])
                        for i in range(0, len(names), 5)
                    },
                    "hint": "Read help:ACTION for its fields before recording.",
                }
            else:
                aliases = {
                    "jobs": "production",
                    "finance": "reports",
                    "planning": "plans",
                }
                result = await self._books.run(
                    self._books.engine.view, aliases.get(section, section), limit=5
                )
            result = dict(result)
            result["capture_status"] = self._books.status
            return compact_report(result)
        except Exception as exc:
            return compact_report({"error": str(exc)})

    @tool(
        description="Record an ERP action using JSON fields. Read help:ACTION first; never invent missing amounts.",
        wait_response=True,
    )
    async def erp_record(self, action: str, details: str) -> str:
        """Args:
        action: Action from erp_report help.
        details: JSON object containing that action's fields.
        """
        try:
            if len(details) > 16000:
                raise ValueError("Entry is too large. Use a smaller record.")
            data = json.loads(details)
            if not isinstance(data, dict):
                raise ValueError("Details must be a JSON object.")
            if action == "import_legacy":
                own_directory = Path(self.get_generated_files_dir()).resolve()
                requested = Path(data.get("path", own_directory)).resolve()
                if requested != own_directory:
                    raise ValueError(
                        "Legacy import is restricted to this skill's generated data folder."
                    )
                data["path"] = str(own_directory)
            await self._ready()
            result = await self._books.run(self._books.engine.command, action, data)
            return compact_report(result)
        except Exception as exc:
            return compact_report({"error": str(exc)})

    @tool(
        description="Open the local ERP dashboard for detailed records and editing.",
        wait_response=True,
        summarize=False,
    )
    async def erp_dashboard(self) -> str:
        try:
            await self._ready()
            server = await self._books.dashboard(int(self._property("dashboard_port", 7863)))
            opened = await asyncio.to_thread(webbrowser.open, server.url)
            await self._show_dashboard(server, once=False)
            return ("ERP dashboard: " if opened else "Open the ERP dashboard at ") + server.url
        except Exception as exc:
            return "Dashboard unavailable: " + str(exc)[:300]

"""Thin Wingman lifecycle and voice adapter for the personal ERP.

The engine owns accounting. The reader owns game-log parsing. This adapter only
connects their durable boundary and exposes three bounded, on-demand tools.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
import webbrowser

from skills.skill_base import Skill, tool
from .erp_feed import capture_once


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


class SC_Accountant(Skill):
    """Personal ERP with Wingman-managed capture and on-demand voice access."""

    def __init__(self, config, settings=None, wingman=None):
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._engine = None
        self._server = None
        self._poll_task = None
        self._announce_task = None
        self._dashboard_lock = asyncio.Lock()
        self._workers = set()
        self._closing = False
        self._worker_lock = asyncio.Lock()
        self._feed_status = "Manual entry: no reader database configured."

    def _property(self, name, default=None):
        value = self.retrieve_custom_property_value(name, [])
        return default if value is None else value

    def _reader_path(self):
        raw = str(self._property("reader_database", "")).strip()
        if raw:
            return Path(raw).expanduser()
        # Read the current profile through Wingman's v3 facade. Do not import
        # the reader, activate another skill, or search other profiles' data.
        config = getattr(getattr(self, "wingman", None), "config", None)
        candidates = set()
        for skill in getattr(config, "skills", None) or ():
            module = str(getattr(skill, "module", "")).lower()
            if module not in {"skills.sc_log_reader.main", "skills.sc_log_reader_2.main"}:
                continue
            for prop in getattr(skill, "custom_properties", None) or ():
                if prop.id == "runtime_directory" and prop.value:
                    runtime = str(prop.value).strip()
                    if runtime:
                        candidates.add(Path(runtime).expanduser() / "events.sqlite3")
        if len(candidates) > 1:
            raise ValueError("Multiple Log Reader databases in this profile. Choose one in Accountant settings.")
        return next(iter(candidates), None)

    def _mode(self):
        return normalized_mode(self._property("complexity_layer", "simple"))

    async def prepare(self):
        await super().prepare()
        from .erp import ERP

        if self._engine is not None:
            return
        self._closing = False
        directory = Path(self.get_generated_files_dir())
        directory.mkdir(parents=True, exist_ok=True)

        def create_owned_engine():
            self._engine = ERP(directory / "erp.sqlite3")

        try:
            await self._worker(create_owned_engine)
            await self._worker(
                self._engine.command, "apply_config_mode", {"mode": self._mode()}
            )
            self._poll_task = asyncio.create_task(
                self._poll(), name="sc-accountant-feed"
            )
            try:
                await self._ensure_dashboard()
                self._announce_task = asyncio.create_task(
                    self._announce_ui_startup(self._server), name="sc-accountant-startup-card"
                )
                self._announce_task.add_done_callback(self._announcement_finished)
            except Exception as exc:
                self.log.warning("Accountant dashboard unavailable: " + str(exc)[:300])
        except BaseException:
            await self.unload()
            raise

    async def _worker(self, fn, *args, **kwargs):
        """Cancellation stops waiting, not sqlite work; unload drains that work."""
        if self._closing:
            raise RuntimeError("Accountant is shutting down.")
        async with self._worker_lock:
            if self._closing:
                raise RuntimeError("Accountant is shutting down.")
            task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)
            return await asyncio.shield(task)

    def _sync(self, database: Path):
        return capture_once(self._engine, database)

    async def _poll(self):
        while not self._closing:
            interval = 15.0
            try:
                mode = self._mode()
                await self._worker(
                    self._engine.command, "apply_config_mode", {"mode": mode}
                )
                interval = max(0.0, float(self._property("auto_sync_interval", 15)))
                database = self._reader_path()
                if interval == 0:
                    self._feed_status = "Automatic capture paused in settings; manual entry is available."
                elif database is None:
                    self._feed_status = "Manual entry available. Enable and configure SC Log Reader in this Wingman profile for automatic capture."
                    await self._worker(self._engine.set_feed_error, self._feed_status)
                elif not await self._worker(database.is_file):
                    self._feed_status = "Waiting for SC Log Reader to create its database. Capture will connect automatically."
                    await self._worker(self._engine.set_feed_error, self._feed_status)
                else:
                    page = await self._worker(self._sync, database)
                    self._feed_status = "Reader capture active." + (
                        " Catching up on recorded events."
                        if page.get("has_more")
                        else ""
                    )
                    if page.get("has_more"):
                        interval = 0.1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._feed_status = "Capture needs attention: " + str(exc)[:300]
                await self._worker(self._engine.set_feed_error, self._feed_status)
            await asyncio.sleep(max(0.1, interval) if interval else 1)

    async def _ready(self):
        if self._engine is None or self._closing:
            raise RuntimeError("Accountant is not ready. Load the skill first.")
        await self._worker(
            self._engine.command, "apply_config_mode", {"mode": self._mode()}
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
                help_result = await self._worker(self._engine.view, "help")
                if action not in help_result["data"]:
                    raise ValueError(
                        "Unknown action. Read help for supported action names."
                    )
                result = {"action": action, "fields": help_result["data"][action]}
            elif section == "help":
                help_result = await self._worker(self._engine.view, "help")
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
                result = await self._worker(
                    self._engine.view, aliases.get(section, section), limit=5
                )
            result = dict(result)
            result["capture_status"] = self._feed_status
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
            result = await self._worker(self._engine.command, action, data)
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
            await self._ensure_dashboard()
            opened = await self._worker(webbrowser.open, self._server.url)
            return (
                "ERP dashboard: " if opened else "Open the ERP dashboard at "
            ) + self._server.url
        except Exception as exc:
            return "Dashboard unavailable: " + str(exc)[:300]

    async def _ensure_dashboard(self):
        async with self._dashboard_lock:
            if self._server is None:
                from .erp_web import ERPServer

                port = int(self._property("dashboard_port", 7863))
                if not 1024 <= port <= 65535:
                    raise ValueError("Dashboard port must be between 1024 and 65535.")
                self._server = ERPServer(self._engine, port=port, share_on_lan=True)
                try:
                    await self._worker(self._server.start)
                except Exception:
                    await self._worker(self._server.stop)
                    self._server = None
                    raise

    def _announcement_finished(self, task):
        if not task.cancelled() and (error := task.exception()) is not None:
            self.log.warning("Accountant startup card unavailable: " + str(error)[:300])

    async def _announce_ui_startup(self, server):
        """Use the same delayed, three-line image card as NavPoint."""
        await asyncio.sleep(15)
        if self._closing or self._server is not server:
            return
        from api.enums import LogType, LogSource
        from .erp_sharing import qr_png_base64
        qr = await self._worker(qr_png_base64, server.lan_url) if server.lan_url else None
        if self._closing or self._server is not server:
            return
        instruction = "Scan with your phone, or open:" if qr else "Open on this computer:"
        await self.printr.print_async(
            f"Accountant dashboard ready.\n{instruction}\n{server.url}",
            color=LogType.POSITIVE, source=LogSource.WINGMAN,
            source_name=self.wingman.name if self.wingman else "SC_Accountant",
            skill_name=self.name,
            additional_data={"image_base64": qr} if qr else None,
        )

    async def unload(self):
        self._closing = True
        if self._announce_task is not None:
            self._announce_task.cancel()
            await asyncio.gather(self._announce_task, return_exceptions=True)
            self._announce_task = None
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._workers:
            await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        if self._server is not None:
            await asyncio.to_thread(self._server.stop)
            self._server = None
        if self._engine is not None:
            await asyncio.to_thread(self._engine.close)
            self._engine = None
        await super().unload()

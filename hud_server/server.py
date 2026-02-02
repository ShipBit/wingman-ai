"""
HUD Server - FastAPI-based HTTP server for HUD overlay control.

This server provides a REST API to control HUD overlays from any client.
It runs in its own thread with its own event loop.
"""

import asyncio
import threading
import queue
from typing import Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from uvicorn import Server, Config

from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.enums import LogType
from services.printr import Printr
from hud_server.hud_manager import HudManager
from hud_server.models import (
    CreateGroupRequest,
    UpdateGroupRequest,
    MessageRequest,
    AppendMessageRequest,
    LoaderRequest,
    ItemRequest,
    UpdateItemRequest,
    ProgressRequest,
    TimerRequest,
    ChatMessageRequest,
    CreateChatWindowRequest,
    StateRestoreRequest,
    HealthResponse,
    GroupStateResponse,
    OperationResponse,
)

# Try to import overlay support (bundled with hud_server)
OVERLAY_AVAILABLE = False
HeadsUpOverlay = None
PIL_AVAILABLE = False

try:
    from hud_server.overlay.overlay import HeadsUpOverlay as _HeadsUpOverlay, PIL_AVAILABLE as _PIL_AVAILABLE
    OVERLAY_AVAILABLE = _PIL_AVAILABLE and _HeadsUpOverlay is not None
    HeadsUpOverlay = _HeadsUpOverlay
    PIL_AVAILABLE = _PIL_AVAILABLE
except ImportError:
    pass

printr = Printr()


class HudServer:
    """
    HTTP-based HUD Server running in its own thread.

    Provides REST API endpoints for controlling HUD overlays.
    Starts fresh on each launch - clients can use state/restore endpoints
    to persist and restore their own state.
    """

    VERSION = "1.0.0"

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[Server] = None
        self._running = False
        self._host = "127.0.0.1"
        self._port = 7862
        self._framerate = 60
        self._layout_margin = 20
        self._layout_spacing = 15

        # HUD state manager
        self.manager = HudManager()

        # Overlay support (optional)
        self._overlay = None
        self._overlay_thread: Optional[threading.Thread] = None
        self._command_queue: Optional[queue.Queue] = None
        self._error_queue: Optional[queue.Queue] = None

        # Create FastAPI app
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            self._start_overlay()
            yield
            # Shutdown
            self._stop_overlay()

        app = FastAPI(
            title="HUD Server",
            description="HTTP API for controlling HUD overlays",
            version=self.VERSION,
            lifespan=lifespan
        )

        # Enable CORS for browser-based clients (OBS Browser Source, web overlays)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Register error handlers for logging invalid requests
        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            """Log validation errors for invalid request data."""
            path = request.url.path
            method = request.method
            errors = exc.errors()
            error_details = [f"{e.get('loc', ['?'])}: {e.get('msg', 'unknown error')}" for e in errors]
            printr.print(
                f"[HUD Server] Invalid request data on {method} {path}: {'; '.join(error_details)}",
                color=LogType.WARNING,
                server_only=True
            )
            return JSONResponse(
                status_code=422,
                content={"status": "error", "message": "Validation error", "detail": errors}
            )

        @app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            """Log HTTP exceptions (404, etc.)."""
            path = request.url.path
            method = request.method
            printr.print(
                f"[HUD Server] {exc.status_code} on {method} {path}: {exc.detail}",
                color=LogType.WARNING,
                server_only=True
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={"status": "error", "message": exc.detail}
            )

        @app.exception_handler(Exception)
        async def general_exception_handler(request: Request, exc: Exception):
            """Log unexpected exceptions."""
            path = request.url.path
            method = request.method
            printr.print(
                f"[HUD Server] Unexpected error on {method} {path}: {type(exc).__name__}: {exc}",
                color=LogType.ERROR,
                server_only=True
            )
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Internal server error", "detail": str(exc)}
            )

        # Register routes
        self._register_routes(app)

        return app

    def _register_routes(self, app: FastAPI):
        """Register all API routes."""

        # ─────────────────────────────── Health ─────────────────────────────── #

        @app.get("/health", response_model=HealthResponse, tags=["health"])
        async def health_check():
            """Check server health and get list of active groups."""
            return HealthResponse(
                status="healthy",
                groups=self.manager.get_groups(),
                version=self.VERSION
            )

        @app.get("/", response_model=HealthResponse, tags=["health"])
        async def root():
            """Root endpoint - same as health check."""
            return await health_check()

        # ─────────────────────────────── Groups ─────────────────────────────── #

        @app.post("/groups", response_model=OperationResponse, tags=["groups"])
        async def create_group(request: CreateGroupRequest):
            """Create or update a HUD group."""
            self.manager.create_group(request.group_name, request.props)
            return OperationResponse(status="ok", message=f"Group '{request.group_name}' created")

        @app.put("/groups/{group_name}", response_model=OperationResponse, tags=["groups"])
        async def update_group(group_name: str, request: UpdateGroupRequest):
            """Update properties of an existing group."""
            if not self.manager.update_group(group_name, request.props):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' updated")

        @app.patch("/groups/{group_name}", response_model=OperationResponse, tags=["groups"])
        async def patch_group(group_name: str, request: UpdateGroupRequest):
            """Update properties of an existing group (PATCH)."""
            printr.print(
                f"[HUD Server] PATCH /groups/{group_name}: props keys={list(request.props.keys()) if request.props else []}",
                color=LogType.INFO,
                server_only=True
            )
            if request.props and 'width' in request.props:
                printr.print(
                    f"[HUD Server] PATCH /groups/{group_name}: width={request.props['width']}",
                    color=LogType.INFO,
                    server_only=True
                )
            result = self.manager.update_group(group_name, request.props)
            printr.print(
                f"[HUD Server] PATCH /groups/{group_name}: manager.update_group returned {result}",
                color=LogType.INFO,
                server_only=True
            )
            if not result:
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' updated")

        @app.delete("/groups/{group_name}", response_model=OperationResponse, tags=["groups"])
        async def delete_group(group_name: str):
            """Delete a HUD group."""
            if not self.manager.delete_group(group_name):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' deleted")

        @app.get("/groups", tags=["groups"])
        async def list_groups():
            """Get list of all group names."""
            return {"groups": self.manager.get_groups()}

        # ─────────────────────────────── State ─────────────────────────────── #

        @app.get("/state/{group_name}", response_model=GroupStateResponse, tags=["state"])
        async def get_state(group_name: str):
            """Get the current state of a group for persistence."""
            state = self.manager.get_group_state(group_name)
            if state is None:
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return GroupStateResponse(group_name=group_name, state=state)

        @app.post("/state/restore", response_model=OperationResponse, tags=["state"])
        async def restore_state(request: StateRestoreRequest):
            """Restore a group's state from a previous snapshot."""
            self.manager.restore_group_state(request.group_name, request.state)
            return OperationResponse(status="ok", message=f"State restored for '{request.group_name}'")

        # ─────────────────────────────── Messages ─────────────────────────────── #

        @app.post("/message", response_model=OperationResponse, tags=["messages"])
        async def show_message(request: MessageRequest):
            """Show a message in a HUD group."""
            printr.print(
                f"[HUD Server] show_message called for group '{request.group_name}'",
                color=LogType.INFO,
                server_only=True
            )
            self.manager.show_message(
                group_name=request.group_name,
                title=request.title,
                content=request.content,
                color=request.color,
                tools=request.tools,
                props=request.props,
                duration=request.duration
            )
            return OperationResponse(status="ok")

        @app.post("/message/append", response_model=OperationResponse, tags=["messages"])
        async def append_message(request: AppendMessageRequest):
            """Append content to the current message (for streaming)."""
            if not self.manager.append_message(request.group_name, request.content):
                raise HTTPException(status_code=404, detail=f"Group '{request.group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/message/hide/{group_name}", response_model=OperationResponse, tags=["messages"])
        async def hide_message(group_name: str):
            """Hide the current message in a group."""
            if not self.manager.hide_message(group_name):
                available_groups = self.manager.get_groups()
                printr.print(
                    f"[HUD Server] hide_message failed: group '{group_name}' not found. "
                    f"Available groups: {available_groups}",
                    color=LogType.WARNING,
                    server_only=True
                )
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Loader ─────────────────────────────── #

        @app.post("/loader", response_model=OperationResponse, tags=["loader"])
        async def set_loader(request: LoaderRequest):
            """Show or hide the loader animation."""
            self.manager.set_loader(request.group_name, request.show, request.color)
            return OperationResponse(status="ok")

        # ─────────────────────────────── Items ─────────────────────────────── #

        @app.post("/items", response_model=OperationResponse, tags=["items"])
        async def add_item(request: ItemRequest):
            """Add a persistent item to a group."""
            self.manager.add_item(
                group_name=request.group_name,
                title=request.title,
                description=request.description,
                color=request.color,
                duration=request.duration
            )
            return OperationResponse(status="ok")

        @app.put("/items", response_model=OperationResponse, tags=["items"])
        async def update_item(request: UpdateItemRequest):
            """Update an existing item."""
            if not self.manager.update_item(
                group_name=request.group_name,
                title=request.title,
                description=request.description,
                color=request.color,
                duration=request.duration
            ):
                raise HTTPException(status_code=404, detail="Item not found")
            return OperationResponse(status="ok")

        @app.delete("/items/{group_name}/{title}", response_model=OperationResponse, tags=["items"])
        async def remove_item(group_name: str, title: str):
            """Remove an item from a group."""
            if not self.manager.remove_item(group_name, title):
                raise HTTPException(status_code=404, detail="Item not found")
            return OperationResponse(status="ok")

        @app.delete("/items/{group_name}", response_model=OperationResponse, tags=["items"])
        async def clear_items(group_name: str):
            """Clear all items from a group."""
            if not self.manager.clear_items(group_name):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Progress ─────────────────────────────── #

        @app.post("/progress", response_model=OperationResponse, tags=["progress"])
        async def show_progress(request: ProgressRequest):
            """Show or update a progress bar."""
            self.manager.show_progress(
                group_name=request.group_name,
                title=request.title,
                current=request.current,
                maximum=request.maximum,
                description=request.description,
                color=request.color,
                auto_close=request.auto_close
            )
            return OperationResponse(status="ok")

        @app.post("/timer", response_model=OperationResponse, tags=["progress"])
        async def show_timer(request: TimerRequest):
            """Show a timer-based progress bar."""
            self.manager.show_timer(
                group_name=request.group_name,
                title=request.title,
                duration=request.duration,
                description=request.description,
                color=request.color,
                auto_close=request.auto_close,
                initial_progress=request.initial_progress
            )
            return OperationResponse(status="ok")

        # ─────────────────────────────── Chat Window ─────────────────────────────── #

        @app.post("/chat/window", response_model=OperationResponse, tags=["chat"])
        async def create_chat_window(request: CreateChatWindowRequest):
            """Create a new chat window."""
            props = {
                "x": request.x,
                "y": request.y,
                "width": request.width,
                "max_height": request.max_height,
                "auto_hide": request.auto_hide,
                "auto_hide_delay": request.auto_hide_delay,
                "max_messages": request.max_messages,
                "sender_colors": request.sender_colors or {},
                "fade_old_messages": request.fade_old_messages,
                "is_chat_window": True,
            }
            if request.props:
                props.update(request.props)

            self.manager.create_chat_window(request.name, props)
            return OperationResponse(status="ok", message=f"Chat window '{request.name}' created")

        @app.delete("/chat/window/{name}", response_model=OperationResponse, tags=["chat"])
        async def delete_chat_window(name: str):
            """Delete a chat window."""
            if not self.manager.delete_group(name):
                raise HTTPException(status_code=404, detail=f"Chat window '{name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/message", response_model=OperationResponse, tags=["chat"])
        async def send_chat_message(request: ChatMessageRequest):
            """Send a message to a chat window."""
            if not self.manager.send_chat_message(
                window_name=request.window_name,
                sender=request.sender,
                text=request.text,
                color=request.color
            ):
                raise HTTPException(status_code=404, detail=f"Chat window '{request.window_name}' not found")
            return OperationResponse(status="ok")

        @app.delete("/chat/messages/{window_name}", response_model=OperationResponse, tags=["chat"])
        async def clear_chat_messages(window_name: str):
            """Clear all messages from a chat window."""
            if not self.manager.clear_chat_window(window_name):
                raise HTTPException(status_code=404, detail=f"Chat window '{window_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/show/{name}", response_model=OperationResponse, tags=["chat"])
        async def show_chat_window(name: str):
            """Show a hidden chat window."""
            if not self.manager.show_chat_window(name):
                raise HTTPException(status_code=404, detail=f"Chat window '{name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/hide/{name}", response_model=OperationResponse, tags=["chat"])
        async def hide_chat_window(name: str):
            """Hide a chat window."""
            if not self.manager.hide_chat_window(name):
                raise HTTPException(status_code=404, detail=f"Chat window '{name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Legacy Compatibility ─────────────────────────────── #
        # These endpoints provide compatibility with the old WebSocket-based commands

        @app.post("/legacy/draw", response_model=OperationResponse, tags=["legacy"])
        async def legacy_draw(cmd: dict[str, Any]):
            """Legacy draw command (WebSocket compatibility)."""
            group = cmd.get("group", "default")
            self.manager.show_message(
                group_name=group,
                title=cmd.get("title", ""),
                content=cmd.get("message", ""),
                color=cmd.get("color"),
                tools=cmd.get("tools"),
                props=cmd.get("props"),
                duration=cmd.get("duration")
            )
            return OperationResponse(status="ok")

        @app.post("/legacy/hide", response_model=OperationResponse, tags=["legacy"])
        async def legacy_hide(cmd: dict[str, Any]):
            """Legacy hide command (WebSocket compatibility)."""
            group = cmd.get("group", "default")
            self.manager.hide_message(group)
            return OperationResponse(status="ok")

        @app.post("/legacy/loading", response_model=OperationResponse, tags=["legacy"])
        async def legacy_loading(cmd: dict[str, Any]):
            """Legacy loading command (WebSocket compatibility)."""
            group = cmd.get("group", "default")
            self.manager.set_loader(group, cmd.get("state", True), cmd.get("color"))
            return OperationResponse(status="ok")

    # ─────────────────────────────── Overlay Support ─────────────────────────────── #

    def _start_overlay(self):
        """Start the overlay renderer in a background thread (if available)."""
        if not OVERLAY_AVAILABLE or HeadsUpOverlay is None:
            return

        if self._overlay_thread and self._overlay_thread.is_alive():
            return

        try:
            self._command_queue = queue.Queue()
            self._error_queue = queue.Queue()

            self._overlay = HeadsUpOverlay(
                command_queue=self._command_queue,
                error_queue=self._error_queue,
                framerate=self._framerate,
                layout_margin=self._layout_margin,
                layout_spacing=self._layout_spacing,
            )

            # Register callback to send commands to overlay
            self.manager.register_command_callback(self._send_to_overlay)

            self._overlay_thread = threading.Thread(
                target=self._overlay.run,
                daemon=True,
                name="HUDOverlayThread"
            )
            self._overlay_thread.start()

        except Exception:
            pass  # Overlay is optional

    def _stop_overlay(self):
        """Stop the overlay renderer."""
        if self._command_queue:
            try:
                self._command_queue.put({"type": "quit"})
            except Exception:
                pass

        if self._overlay_thread:
            self._overlay_thread.join(timeout=2.0)
            self._overlay_thread = None

        self._overlay = None
        self._command_queue = None
        self.manager.unregister_command_callback(self._send_to_overlay)

    def _send_to_overlay(self, command: dict[str, Any]):
        """Send a command to the overlay renderer."""
        cmd_type = command.get('type', 'unknown')
        group = command.get('group', 'unknown')
        printr.print(
            f"[HUD Server] _send_to_overlay: type='{cmd_type}', group='{group}'",
            color=LogType.INFO,
            server_only=True
        )
        if cmd_type == 'update_group':
            props = command.get('props', {})
            printr.print(
                f"[HUD Server] _send_to_overlay: update_group props keys={list(props.keys())}",
                color=LogType.INFO,
                server_only=True
            )
            if 'width' in props:
                printr.print(
                    f"[HUD Server] _send_to_overlay: width={props['width']}",
                    color=LogType.INFO,
                    server_only=True
                )
        if self._command_queue:
            try:
                self._command_queue.put(command)
            except Exception as e:
                printr.print(
                    f"[HUD Server] _send_to_overlay: FAILED to queue: {e}",
                    color=LogType.ERROR,
                    server_only=True
                )
        else:
            printr.print(
                f"[HUD Server] _send_to_overlay: NO command queue!",
                color=LogType.WARNING,
                server_only=True
            )

    # ─────────────────────────────── Server Lifecycle ─────────────────────────────── #

    def start(self, host: str = "127.0.0.1", port: int = 7862, framerate: int = 60,
               layout_margin: int = 20, layout_spacing: int = 15) -> bool:
        """
        Start the HUD server in a background thread.

        Args:
            host: Interface to listen on ('127.0.0.1' for local, '0.0.0.0' for LAN)
            port: Port to listen on
            framerate: HUD overlay rendering framerate (min 1)
            layout_margin: Margin from screen edges in pixels
            layout_spacing: Spacing between stacked windows in pixels

        Returns:
            True if server started successfully
        """
        if self._running:
            return True

        self._host = host
        self._port = port
        self._framerate = max(1, framerate)
        self._layout_margin = layout_margin
        self._layout_spacing = layout_spacing

        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="HUDServerThread"
        )
        self._thread.start()

        # Wait briefly for server to start
        import time
        for _ in range(50):  # 5 seconds max
            time.sleep(0.1)
            if self._running:
                printr.print(
                    f"HUD Server started on http://{self._host}:{self._port}",
                    color=LogType.INFO,
                    server_only=True
                )
                return True

        return False

    def _run_server(self):
        """Run the server in its own thread with its own event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        config = Config(
            app=self.app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        self._server = Server(config)

        self._running = True

        try:
            self._loop.run_until_complete(self._server.serve())
        except Exception:
            pass
        finally:
            self._running = False

    async def stop(self):
        """Stop the HUD server."""
        if not self._running:
            return

        self._running = False

        # Stop overlay first
        self._stop_overlay()

        # Signal server to stop
        if self._server:
            self._server.should_exit = True

        # Wait for thread to finish
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        self._server = None
        self._loop = None

        printr.print(
            "HUD Server stopped",
            color=LogType.INFO,
            server_only=True
        )

    @property
    def is_running(self) -> bool:
        """Check if the server is currently running."""
        return self._running

    @property
    def base_url(self) -> str:
        """Get the base URL for the server."""
        return f"http://{self._host}:{self._port}"


# Standalone execution support
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HUD Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=7862, help="Port to bind to")
    args = parser.parse_args()

    print(f"Starting HUD Server on http://{args.host}:{args.port}")
    print("API docs available at /docs")

    uvicorn.run(
        "hud_server.server:HudServer().app",
        host=args.host,
        port=args.port,
        reload=False
    )


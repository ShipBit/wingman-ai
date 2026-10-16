"""
HUD Server - FastAPI-based HTTP server for HUD overlay control.

This server provides a REST API to control HUD overlays from any client.
It runs in its own thread with its own event loop.
"""

import asyncio
import threading
import queue
import time
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
from hud_server import constants as hud_const
from hud_server.types import WindowType
from hud_server.models import (
    CreateGroupRequest,
    UpdateGroupRequest,
    DefaultsRequest,
    PreviewRequest,
    PreviewResponse,
    MessageRequest,
    AppendMessageRequest,
    LoaderRequest,
    ItemRequest,
    UpdateItemRequest,
    ProgressRequest,
    TimerRequest,
    ChatMessageRequest,
    ChatMessageUpdateRequest,
    CreateChatWindowRequest,
    HealthResponse,
    OperationResponse,
    ChatMessageResponse,
)

# The overlay renders on every OS; the platform backend puts it on screen
from hud_server.overlay.overlay import HeadsUpOverlay, PIL_AVAILABLE
from hud_server.platform import create_backend

printr = Printr()


class HudServer:
    """
    HTTP-based HUD Server running in its own thread.

    Provides REST API endpoints for controlling HUD overlays.
    Starts fresh on each launch - clients can use state/restore endpoints
    to persist and restore their own state.
    """

    VERSION = "1.0.0"

    # Default configuration constants (from constants module)
    DEFAULT_HOST = hud_const.DEFAULT_HOST
    DEFAULT_PORT = hud_const.DEFAULT_PORT
    DEFAULT_FRAMERATE = hud_const.DEFAULT_FRAMERATE
    DEFAULT_LAYOUT_MARGIN = hud_const.DEFAULT_LAYOUT_MARGIN
    DEFAULT_LAYOUT_SPACING = hud_const.DEFAULT_LAYOUT_SPACING
    DEFAULT_SCREEN = 1

    # Server startup timeout
    STARTUP_TIMEOUT_SECONDS = hud_const.SERVER_STARTUP_TIMEOUT
    STARTUP_CHECK_INTERVAL = hud_const.SERVER_STARTUP_CHECK_INTERVAL

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[Server] = None
        self._running = False
        self._host = self.DEFAULT_HOST
        self._port = self.DEFAULT_PORT
        self._framerate = self.DEFAULT_FRAMERATE
        self._layout_margin = self.DEFAULT_LAYOUT_MARGIN
        self._layout_spacing = self.DEFAULT_LAYOUT_SPACING
        self._screen = self.DEFAULT_SCREEN

        # HUD state manager
        self.manager = HudManager()

        # Overlay support (optional)
        self._overlay = None
        self._overlay_thread: Optional[threading.Thread] = None
        self._command_queue: Optional[queue.Queue] = None
        self._error_queue: Optional[queue.Queue] = None
        self._error_thread: Optional[threading.Thread] = None

        # Called with overlay events (e.g. preview_changed), from the overlay thread
        self._event_listeners: list = []

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
            # Reduce noise for 404s
            if exc.status_code != 404:
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

        # ─────────────────────────────── Settings ─────────────────────────────── #

        @app.post("/settings/update", tags=["settings"])
        async def update_settings(
            framerate: Optional[int] = None,
            layout_margin: Optional[int] = None,
            layout_spacing: Optional[int] = None,
            screen: Optional[int] = None
        ):
            """Update HUD server settings dynamically without restart."""
            self.update_settings(
                framerate=framerate,
                layout_margin=layout_margin,
                layout_spacing=layout_spacing,
                screen=screen
            )
            return {"status": "ok", "message": "Settings updated"}

        # ─────────────────────────────── Defaults ─────────────────────────────── #

        @app.get(hud_const.PATH_DEFAULTS, response_model=DefaultsRequest, tags=["defaults"])
        async def get_defaults():
            """The values groups use for props their own calls leave out."""
            return DefaultsRequest(**self.manager.get_defaults())

        @app.put(hud_const.PATH_DEFAULTS, response_model=OperationResponse, tags=["defaults"])
        async def set_defaults(request: DefaultsRequest):
            """Replace the defaults. Existing windows pick them up immediately."""
            self.manager.set_defaults(request.props, request.groups)
            return OperationResponse(status="ok", message="Defaults updated")

        # ─────────────────────────────── Preview ─────────────────────────────── #

        @app.get(hud_const.PATH_PREVIEW, response_model=PreviewResponse, tags=["preview"])
        async def get_preview():
            """The current preview of the shared containers, if one is shown."""
            preview = self.manager.get_preview()
            if preview is None:
                return PreviewResponse(active=False)
            return PreviewResponse(active=True, **preview)

        @app.post(hud_const.PATH_PREVIEW, response_model=OperationResponse, tags=["preview"])
        @app.put(hud_const.PATH_PREVIEW, response_model=OperationResponse, tags=["preview"])
        async def set_preview(request: PreviewRequest):
            """Show or update the preview of the chat and info containers."""
            self.manager.set_preview(request.containers, request.interactive)
            return OperationResponse(status="ok")

        @app.delete(hud_const.PATH_PREVIEW, response_model=OperationResponse, tags=["preview"])
        async def clear_preview():
            """End the preview; the real containers come back."""
            self.manager.clear_preview()
            return OperationResponse(status="ok")

        # ─────────────────────────────── Groups ─────────────────────────────── #

        @app.post("/groups", response_model=OperationResponse, tags=["groups"])
        async def create_group(request: CreateGroupRequest):
            """Create or update a HUD group."""
            self.manager.create_group(request.group_name, request.element.value, request.props)
            return OperationResponse(status="ok", message=f"Group '{request.group_name}' created")

        @app.put("/groups/{group_name}/{element}", response_model=OperationResponse, tags=["groups"])
        async def update_group(group_name: str, element: str, request: UpdateGroupRequest):
            """Update properties of an existing group."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.update_group(group_name, element_type.value, request.props):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' updated")

        @app.patch("/groups/{group_name}/{element}", response_model=OperationResponse, tags=["groups"])
        async def patch_group(group_name: str, element: str, request: UpdateGroupRequest):
            """Update properties of an existing group (PATCH)."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            result = self.manager.update_group(group_name, element_type.value, request.props)
            if not result:
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' updated")

        @app.delete("/groups/{group_name}/{element}", response_model=OperationResponse, tags=["groups"])
        async def delete_group(group_name: str, element: str):
            """Delete a HUD group."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.delete_group(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok", message=f"Group '{group_name}' deleted")

        @app.get("/groups", tags=["groups"])
        async def list_groups():
            """Get list of all group names."""
            return {"groups": self.manager.get_groups()}

        # ─────────────────────────────── Messages ─────────────────────────────── #

        @app.post("/message", response_model=OperationResponse, tags=["messages"])
        async def show_message(request: MessageRequest):
            """Show a message in a HUD group."""
            self.manager.show_message(
                group_name=request.group_name,
                element=request.element.value,
                title=request.title,
                content=request.content,
                color=request.color,
                tools=request.tools,
                props=request.props,
                duration=request.duration,
                title_icon=request.title_icon
            )
            return OperationResponse(status="ok")

        @app.post("/message/append", response_model=OperationResponse, tags=["messages"])
        async def append_message(request: AppendMessageRequest):
            """Append content to the current message (for streaming)."""
            if not self.manager.append_message(request.group_name, request.element.value, request.content):
                raise HTTPException(status_code=404, detail=f"Group '{request.group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/message/hide/{group_name}/{element}", response_model=OperationResponse, tags=["messages"])
        async def hide_message(group_name: str, element: str):
            """Hide the current message in a group."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.hide_message(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Loader ─────────────────────────────── #

        @app.post("/loader", response_model=OperationResponse, tags=["loader"])
        async def set_loader(request: LoaderRequest):
            """Show or hide the loader animation."""
            self.manager.set_loader(request.group_name, request.element.value, request.show, request.color)
            return OperationResponse(status="ok")

        # ─────────────────────────────── Items ─────────────────────────────── #

        @app.post("/items", response_model=OperationResponse, tags=["items"])
        async def add_item(request: ItemRequest):
            """Add a persistent item to a group."""
            self.manager.add_item(
                group_name=request.group_name,
                element=request.element.value,
                title=request.title,
                description=request.description,
                color=request.color,
                duration=request.duration,
                added_by=request.added_by,
            )
            return OperationResponse(status="ok")

        @app.put("/items", response_model=OperationResponse, tags=["items"])
        async def update_item(request: UpdateItemRequest):
            """Update an existing item."""
            if not self.manager.update_item(
                group_name=request.group_name,
                element=request.element.value,
                title=request.title,
                description=request.description,
                color=request.color,
                duration=request.duration
            ):
                raise HTTPException(status_code=404, detail="Item not found")
            return OperationResponse(status="ok")

        @app.delete("/items/{group_name}/{element}/{title}", response_model=OperationResponse, tags=["items"])
        async def remove_item(group_name: str, element: str, title: str):
            """Remove an item from a group."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.remove_item(group_name, element_type.value, title):
                raise HTTPException(status_code=404, detail="Item not found")
            return OperationResponse(status="ok")

        @app.delete("/items/{group_name}/{element}", response_model=OperationResponse, tags=["items"])
        async def clear_items(group_name: str, element: str):
            """Clear all items from a group."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.clear_items(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Progress ─────────────────────────────── #

        @app.post("/progress", response_model=OperationResponse, tags=["progress"])
        async def show_progress(request: ProgressRequest):
            """Show or update a progress bar."""
            self.manager.show_progress(
                group_name=request.group_name,
                element=request.element.value,
                title=request.title,
                current=request.current,
                maximum=request.maximum,
                description=request.description,
                color=request.color,
                auto_close=request.auto_close,
                added_by=request.added_by,
            )
            return OperationResponse(status="ok")

        @app.post("/timer", response_model=OperationResponse, tags=["progress"])
        async def show_timer(request: TimerRequest):
            """Show a timer-based progress bar."""
            self.manager.show_timer(
                group_name=request.group_name,
                element=request.element.value,
                title=request.title,
                duration=request.duration,
                description=request.description,
                color=request.color,
                auto_close=request.auto_close,
                initial_progress=request.initial_progress,
                added_by=request.added_by,
            )
            return OperationResponse(status="ok")

        # ─────────────────────────────── Chat Window ─────────────────────────────── #

        @app.post("/chat/window", response_model=OperationResponse, tags=["chat"])
        async def create_chat_window(request: CreateChatWindowRequest):
            """Create a new chat window."""
            props = {
                "anchor": request.anchor,
                "priority": request.priority,
                "layout_mode": request.layout_mode,
                "x": request.x,
                "y": request.y,
                "width": request.width,
                "max_height": request.max_height,
                "bg_color": request.bg_color,
                "text_color": request.text_color,
                "accent_color": request.accent_color,
                "opacity": request.opacity,
                "font_size": request.font_size,
                "font_family": request.font_family,
                "border_radius": request.border_radius,
                "auto_hide": request.auto_hide,
                "auto_hide_delay": request.auto_hide_delay,
                "max_messages": request.max_messages,
                "sender_colors": request.sender_colors or {},
                "fade_old_messages": request.fade_old_messages,
            }
            # Remove None values
            props = {k: v for k, v in props.items() if v is not None}
            if request.props:
                props.update(request.props)

            self.manager.create_group(request.group_name, request.element.value, props)
            return OperationResponse(status="ok", message=f"Chat window '{request.group_name}' created")

        @app.delete("/chat/window/{group_name}/{element}", response_model=OperationResponse, tags=["chat"])
        async def delete_chat_window(group_name: str, element: str):
            """Delete a chat window."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.delete_group(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Chat window '{group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/message", response_model=ChatMessageResponse, tags=["chat"])
        async def send_chat_message(request: ChatMessageRequest):
            """Send a message to a chat window. Returns the message ID."""
            message_id = self.manager.send_chat_message(
                group_name=request.group_name,
                element=request.element.value,
                sender=request.sender,
                text=request.text,
                color=request.color,
                icon=request.icon,
                own=request.own,
                tools=request.tools,
            )
            if message_id is None:
                raise HTTPException(status_code=404, detail=f"Chat window '{request.group_name}' not found")
            return ChatMessageResponse(status="ok", message_id=message_id)

        @app.put("/chat/message", response_model=OperationResponse, tags=["chat"])
        async def update_chat_message(request: ChatMessageUpdateRequest):
            """Update an existing chat message's text content by its ID."""
            if not self.manager.update_chat_message(
                group_name=request.group_name,
                element=request.element.value,
                message_id=request.message_id,
                text=request.text
            ):
                raise HTTPException(status_code=404, detail=f"Message '{request.message_id}' not found in window '{request.group_name}'")
            return OperationResponse(status="ok")

        @app.delete("/chat/messages/{group_name}/{element}", response_model=OperationResponse, tags=["chat"])
        async def clear_chat_messages(group_name: str, element: str):
            """Clear all messages from a chat window."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.clear_chat_window(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Chat window '{group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/show/{group_name}/{element}", response_model=OperationResponse, tags=["chat"])
        async def show_chat_window(group_name: str, element: str):
            """Show a hidden chat window."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.show_chat_window(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Chat window '{group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/chat/hide/{group_name}/{element}", response_model=OperationResponse, tags=["chat"])
        async def hide_chat_window(group_name: str, element: str):
            """Hide a chat window."""
            try:
                element_type = WindowType(element)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid element type: {element}")
            if not self.manager.hide_chat_window(group_name, element_type.value):
                raise HTTPException(status_code=404, detail=f"Chat window '{group_name}' not found")
            return OperationResponse(status="ok")

        # ─────────────────────────────── Element Visibility ─────────────────────────────── #

        @app.post("/element/show", response_model=OperationResponse, tags=["element"])
        async def show_element(request: Request):
            """Show a hidden HUD element (message, persistent, or chat).

            The element will continue to receive updates and perform all logic,
            but will now be displayed again.
            """
            body = await request.json()
            group_name = body.get("group_name")
            element_str = body.get("element")

            if not group_name or not element_str:
                raise HTTPException(status_code=400, detail="group_name and element are required")

            # Validate element is a valid WindowType enum value
            try:
                element = WindowType(element_str)
            except ValueError:
                valid_values = [e.value for e in WindowType]
                raise HTTPException(
                    status_code=400,
                    detail=f"element must be one of: {', '.join(valid_values)}"
                )

            if not self.manager.show_element(group_name, element.value):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")

        @app.post("/element/hide", response_model=OperationResponse, tags=["element"])
        async def hide_element(request: Request):
            """Hide a HUD element (message, persistent, or chat).

            The element will no longer be displayed but will still receive updates
            and perform all logic (timers, auto-hide, updates) in the background.
            """
            body = await request.json()
            group_name = body.get("group_name")
            element_str = body.get("element")

            if not group_name or not element_str:
                raise HTTPException(status_code=400, detail="group_name and element are required")

            # Validate element is a valid WindowType enum value
            try:
                element = WindowType(element_str)
            except ValueError:
                valid_values = [e.value for e in WindowType]
                raise HTTPException(
                    status_code=400,
                    detail=f"element must be one of: {', '.join(valid_values)}"
                )

            if not self.manager.hide_element(group_name, element.value):
                raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
            return OperationResponse(status="ok")


    # ─────────────────────────────── Overlay Support ─────────────────────────────── #

    def _start_overlay(self):
        """Start the overlay renderer in a background thread (if available)."""
        if not PIL_AVAILABLE:
            printr.print(
                hud_const.LOG_OVERLAY_NOT_AVAILABLE,
                color=LogType.WARNING,
                server_only=True
            )
            return

        backend = create_backend()
        if not backend.supported:
            printr.print(
                hud_const.LOG_OVERLAY_UNSUPPORTED.format(backend.unsupported_reason),
                color=LogType.WARNING,
                server_only=True
            )
            return

        if self._overlay_thread and self._overlay_thread.is_alive():
            printr.print(
                hud_const.LOG_OVERLAY_ALREADY_RUNNING,
                color=LogType.WARNING,
                server_only=True
            )
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
                screen=self._screen,
                event_callback=self._on_overlay_event,
                backend=backend,
            )

            # Register callback to send commands to overlay
            self.manager.register_command_callback(self._send_to_overlay)

            self._overlay_thread = threading.Thread(
                target=self._overlay.run,
                daemon=True,
                name=hud_const.THREAD_NAME_OVERLAY
            )
            self._overlay_thread.start()

            self._error_thread = threading.Thread(
                target=self._drain_overlay_errors,
                args=(self._error_queue,),
                daemon=True,
                name="HUDOverlayErrorThread",
            )
            self._error_thread.start()

            printr.print(
                hud_const.LOG_OVERLAY_STARTED,
                color=LogType.INFO,
                server_only=True
            )

        except Exception as e:
            printr.print(
                f"[HUD Server] Failed to start overlay: {type(e).__name__}: {e}",
                color=LogType.ERROR,
                server_only=True
            )
            # Overlay is optional, so we continue without it

    def _stop_overlay(self):
        """Stop the overlay renderer."""
        if not self._command_queue and not self._overlay_thread:
            return

        try:
            if self._command_queue:
                try:
                    self._command_queue.put({"type": "quit"}, timeout=1.0)
                except Exception as e:
                    printr.print(
                        f"[HUD Server] Failed to send quit command to overlay: {e}",
                        color=LogType.WARNING,
                        server_only=True
                    )

            if self._overlay_thread:
                self._overlay_thread.join(timeout=hud_const.OVERLAY_SHUTDOWN_TIMEOUT)
                if self._overlay_thread.is_alive():
                    printr.print(
                        "[HUD Server] Overlay thread did not stop gracefully",
                        color=LogType.WARNING,
                        server_only=True
                    )
                self._overlay_thread = None

            self._overlay = None
            self._command_queue = None
            if self._error_queue:
                self._error_queue.put(None)  # stops the drain thread
            self._error_queue = None
            self._error_thread = None
            self.manager.unregister_command_callback(self._send_to_overlay)

            printr.print(
                hud_const.LOG_OVERLAY_STOPPED,
                color=LogType.INFO,
                server_only=True
            )

        except Exception as e:
            printr.print(
                f"[HUD Server] Error stopping overlay: {type(e).__name__}: {e}",
                color=LogType.ERROR,
                server_only=True
            )

    def add_event_listener(self, listener) -> None:
        """Call `listener(event)` for overlay events such as `preview_changed`.

        Runs on the overlay thread: hand the work to your own loop quickly.
        """
        if listener not in self._event_listeners:
            self._event_listeners.append(listener)

    def remove_event_listener(self, listener) -> None:
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    def _on_overlay_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "preview_changed":
            self.manager.preview_moved(
                event["container"], event["x1"], event["y1"], event["x2"], event["y2"]
            )
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception as e:
                printr.print(
                    f"[HUD Server] Event listener failed: {type(e).__name__}: {e}",
                    color=LogType.ERROR,
                    server_only=True,
                )

    def _drain_overlay_errors(self, error_queue: queue.Queue):
        """Log what the overlay thread reports. Heartbeats are dropped, and an
        error repeating every frame is logged once per 10 seconds."""
        last_logged: dict[tuple, float] = {}
        while True:
            report = error_queue.get()
            if report is None:
                return
            if not isinstance(report, dict) or report.get("type") != "error":
                continue
            key = (report.get("context"), report.get("error"))
            now = time.time()
            if now - last_logged.get(key, 0) < 10:
                continue
            last_logged[key] = now
            printr.print(
                f"[HUD Overlay] {report.get('context', '?')}: {report.get('error', '')}",
                color=LogType.ERROR,
                server_only=True,
            )

    def _send_to_overlay(self, command: dict[str, Any]):
        """Send a command to the overlay renderer."""
        if self._command_queue:
            try:
                self._command_queue.put(command)
            except Exception as e:
                printr.print(
                    f"[HUD Server] _send_to_overlay: FAILED to queue: {e}",
                    color=LogType.ERROR,
                    server_only=True
                )

    # ─────────────────────────────── Server Lifecycle ─────────────────────────────── #

    def start(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, framerate: int = DEFAULT_FRAMERATE,
               layout_margin: int = DEFAULT_LAYOUT_MARGIN, layout_spacing: int = DEFAULT_LAYOUT_SPACING,
               screen: int = DEFAULT_SCREEN) -> bool:
        """
        Start the HUD server in a background thread.

        Args:
            host: Interface to listen on ('127.0.0.1' for local, '0.0.0.0' for LAN)
            port: Port to listen on
            framerate: HUD overlay rendering framerate (min 1)
            layout_margin: Margin from screen edges in pixels
            layout_spacing: Spacing between stacked windows in pixels
            screen: Which monitor to render the HUD on (1 = primary, 2 = secondary, etc.)

        Returns:
            True if server started successfully
        """
        if self._running:
            printr.print(
                hud_const.LOG_SERVER_ALREADY_RUNNING,
                color=LogType.WARNING,
                server_only=True
            )
            return True

        self._host = host
        self._port = port
        self._framerate = max(1, framerate)
        self._layout_margin = layout_margin
        self._layout_spacing = layout_spacing
        self._screen = max(1, screen)

        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name=hud_const.THREAD_NAME_SERVER
        )
        self._thread.start()

        # Wait until uvicorn finished its startup: the lifespan has started the
        # overlay and hooked it to the manager, so nothing sent after this is lost
        max_checks = int(self.STARTUP_TIMEOUT_SECONDS / self.STARTUP_CHECK_INTERVAL)
        for _ in range(max_checks):
            time.sleep(self.STARTUP_CHECK_INTERVAL)
            if self._running and self._server is not None and self._server.started:
                printr.print(
                    hud_const.LOG_SERVER_STARTED.format(self._host, self._port),
                    color=LogType.INFO,
                    server_only=True
                )
                return True

        printr.print(
            hud_const.LOG_SERVER_STARTUP_TIMEOUT.format(self.STARTUP_TIMEOUT_SECONDS),
            color=LogType.ERROR,
            server_only=True
        )
        return False

    def update_settings(self, framerate: int = None, layout_margin: int = None,
                       layout_spacing: int = None, screen: int = None):
        """Update HUD server settings without restarting.

        Args:
            framerate: New framerate (1-240)
            layout_margin: New layout margin in pixels
            layout_spacing: New layout spacing in pixels
            screen: New screen index (1=primary, 2=secondary, etc.)
        """
        # Update local state and build message with only changed settings
        settings_msg = {"type": "update_settings"}

        if framerate is not None:
            self._framerate = max(1, min(240, framerate))
            settings_msg["framerate"] = self._framerate
        if layout_margin is not None:
            self._layout_margin = layout_margin
            settings_msg["layout_margin"] = self._layout_margin
        if layout_spacing is not None:
            self._layout_spacing = layout_spacing
            settings_msg["layout_spacing"] = self._layout_spacing
        if screen is not None:
            self._screen = max(1, screen)
            settings_msg["screen"] = self._screen

        # Send to overlay if running - only include changed settings
        if self._command_queue and self._overlay_thread and self._overlay_thread.is_alive():
            self._command_queue.put(settings_msg)

    def _run_server(self):
        """Run the server in its own thread with its own event loop."""
        try:
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

            self._loop.run_until_complete(self._server.serve())
        except Exception as e:
            printr.print(
                f"[HUD Server] Server error: {type(e).__name__}: {e}",
                color=LogType.ERROR,
                server_only=True
            )
        finally:
            self._running = False
            printr.print(
                "[HUD Server] Server loop exited",
                color=LogType.INFO,
                server_only=True
            )

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
            self._thread.join(timeout=hud_const.SERVER_SHUTDOWN_TIMEOUT)
            self._thread = None

        self._server = None
        self._loop = None

        printr.print(
            hud_const.LOG_SERVER_STOPPED,
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

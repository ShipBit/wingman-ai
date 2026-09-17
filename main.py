import multiprocessing
import argparse
import asyncio
import atexit
import faulthandler
import html
from enum import Enum
from os import path
import os
import platform
import signal
import sys
import traceback
from typing import Any, Literal, get_args, get_origin

# Must be called before anything else in a PyInstaller frozen app.
# On macOS, multiprocessing spawns child processes by re-invoking the binary
# with -c flags. Without this, argparse sees those flags and crashes.
multiprocessing.freeze_support()

# Diagnostics: dump a Python + all-thread traceback to stderr if the process
# dies on a native fault (SIGSEGV/SIGABRT/SIGBUS/SIGFPE) from a C extension
# (llama.cpp/Metal, onnxruntime, torch, PortAudio, SDL). Without this, such a
# crash is silent and the only sign is a stray "leaked semaphore" warning from
# the multiprocessing resource_tracker. Cheap and safe to leave enabled.
faulthandler.enable()

# =============================================================================
# NVIDIA CUDA DLL PATH SETUP (must be done before any CUDA-dependent imports)
# =============================================================================
# When running as a PyInstaller bundle, the NVIDIA CUDA DLLs are in subdirectories
# of _internal/nvidia/. We need to add these to PATH so onnxruntime can find them.
# This must happen before any import that might load CUDA libraries.
if getattr(sys, "frozen", False):
    # Running as bundled exe
    _internal_dir = sys._MEIPASS
    _nvidia_paths = [
        path.join(_internal_dir, "nvidia", "cublas", "bin"),
        path.join(_internal_dir, "nvidia", "cudnn", "bin"),
        path.join(_internal_dir, "nvidia", "cuda_runtime", "bin"),
        path.join(_internal_dir, "nvidia", "cuda_nvrtc", "bin"),
        path.join(_internal_dir, "nvidia", "nvrtc", "bin"),
    ]
    # Prepend existing paths that exist
    _existing_nvidia_paths = [p for p in _nvidia_paths if path.isdir(p)]
    if _existing_nvidia_paths:
        os.environ["PATH"] = (
            os.pathsep.join(_existing_nvidia_paths)
            + os.pathsep
            + os.environ.get("PATH", "")
        )

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.concurrency import asynccontextmanager
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from api.commands import McpOAuthStateChangedCommand, WebSocketCommandModel
from api.interface import BenchmarkResult, CoreStatusResponse
from api.enums import ENUM_TYPES, CoreState, LogType, WingmanInitializationErrorType
import keyboard.keyboard as keyboard
from services.command_handler import CommandHandler
from services.config_manager import ConfigManager, ConfigValidationError
from services.connection_manager import ConnectionManager
from services.esp32_handler import Esp32Handler
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.mcp_oauth import CALLBACK_PATH, get_oauth_service
from services.system_manager import LOCAL_VERSION, SystemManager
from wingman_core import WingmanCore
port = None
host = None

connection_manager = ConnectionManager()


printr = Printr()
Printr.set_connection_manager(connection_manager)

app_is_bundled = getattr(sys, "frozen", False)
app_root_path = sys._MEIPASS if app_is_bundled else path.dirname(path.abspath(__file__))

# Set the bundled skills directory for ModuleManager
from services.module_manager import set_bundled_skills_dir

bundled_skills_path = path.join(app_root_path, "skills")
set_bundled_skills_dir(bundled_skills_path)
printr.print(
    f"Skills directory: {bundled_skills_path}",
    server_only=True,
    color=LogType.STARTUP,
)

# creates all the configs from templates - do this first!
config_manager = ConfigManager(app_root_path)
printr.print(
    f"Config directory: {config_manager.config_dir}",
    server_only=True,
    color=LogType.STARTUP,
)

secret_keeper = SecretKeeper()
SecretKeeper.set_connection_manager(connection_manager)

system_manager = SystemManager()
printr.print(
    f"Wingman AI Core v{LOCAL_VERSION}",
    server_only=True,
    color=LogType.STARTUP,
)

# uses the Singletons above, so don't move this up!
core = WingmanCore(
    config_manager=config_manager,
    app_root_path=app_root_path,
    app_is_bundled=app_is_bundled,
    system_manager=system_manager,
)
core.set_connection_manager(connection_manager)

keyboard.hook(core.on_key)

def custom_generate_unique_id(route: APIRoute):
    return f"{route.tags[0]}-{route.name}"


def modify_openapi():
    """Strip the tagname of the functions (for the client) in the OpenAPI spec"""
    openapi_schema = app.openapi()
    for path_data in openapi_schema["paths"].values():
        for operation in path_data.values():
            tags = operation.get("tags")
            if tags:
                tag = tags[0]
                operation_id = operation.get("operationId")
                if operation_id:
                    to_remove = f"{tag}-"
                    new_operation_id = operation_id[len(to_remove) :]
                    operation["operationId"] = new_operation_id
    app.openapi_schema = openapi_schema


async def shutdown():
    await connection_manager.shutdown()
    await core.shutdown()
    keyboard.unhook_all()


def exit_handler():
    printr.print(
        "atexit handler shutting down...", color=LogType.SYSTEM, server_only=True
    )
    try:
        asyncio.run(shutdown())
    except Exception:
        # If async shutdown fails (e.g. loop issues), the LlamaCppProvider's
        # own atexit handler will still kill orphan llama-server processes.
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # executed before the application starts
    modify_openapi()

    yield

    # executed after the application has finished
    printr.print(
        "Lifespan end - shutting down...", color=LogType.SYSTEM, server_only=True
    )
    await shutdown()


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)


def custom_openapi():
    global host

    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Wingman AI Core REST API",
        version=LOCAL_VERSION,
        description="Communicate with Wingman AI Core",
        routes=app.routes,
    )

    # Add custom server configuration
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    openapi_schema["servers"] = [{"url": f"{host}:{port}"}]

    # Ensure the components.schemas key exists
    openapi_schema.setdefault("components", {}).setdefault("schemas", {})

    # Add enums to schema
    for enum_name, enum_model in ENUM_TYPES.items():
        enum_field_name, enum_type = next(iter(enum_model.__annotations__.items()))
        if issubclass(enum_type, Enum):
            enum_values = [e.value for e in enum_type]
            enum_schema = {
                "type": "string",
                "enum": enum_values,
                "description": f"Possible values for {enum_name}",
            }
            openapi_schema["components"]["schemas"][enum_name] = enum_schema

    openapi_schema["components"]["schemas"]["CommandActionConfig"] = {
        "type": "object",
        "properties": {
            "keyboard": {"$ref": "#/components/schemas/CommandKeyboardConfig"},
            "wait": {"type": "number"},
            "mouse": {"$ref": "#/components/schemas/CommandMouseConfig"},
            "write": {"type": "string"},
            "audio": {"$ref": "#/components/schemas/AudioFileConfig"},
            "joystick": {"$ref": "#/components/schemas/CommandJoystickConfig"},
        },
    }

    # Add WebSocket command models to schema
    for cls in WebSocketCommandModel.__subclasses__():
        cls_schema_dict = cls.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )

        for field_name, field_type in cls.__annotations__.items():
            origin = get_origin(field_type)
            if origin is Literal:
                literal_args = get_args(field_type)
                if len(literal_args) == 1:
                    literal_value = literal_args[0]
                    cls_schema_dict["properties"][field_name] = {
                        "type": "string",
                        "enum": [literal_value],
                    }
                else:
                    cls_schema_dict["properties"][field_name] = {
                        "type": "string",
                        "enum": list(literal_args),
                    }

                cls_schema_dict.setdefault("required", []).append(field_name)
        openapi_schema["components"]["schemas"][cls.__name__] = cls_schema_dict

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# if a class adds GET/POST endpoints, add them here:
app.include_router(core.router)
app.include_router(core.config_service.router)
app.include_router(core.settings_service.router)
app.include_router(core.voice_service.router)

app.include_router(system_manager.router)
app.include_router(secret_keeper.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    command_handler = CommandHandler(connection_manager, core)
    try:
        while True:
            message = await websocket.receive_text()
            await command_handler.dispatch(message, websocket)
    except WebSocketDisconnect:
        await printr.print_async("Client disconnected", server_only=True)
    finally:
        await connection_manager.disconnect(websocket)


# Websocket for ESP32 clients to stream audio to and from
@app.websocket("/")
async def oi_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    esp32_handler = Esp32Handler(core)
    receive_task = asyncio.create_task(esp32_handler.receive_messages(websocket))
    send_task = asyncio.create_task(esp32_handler.send_messages(websocket))
    try:
        await asyncio.gather(receive_task, send_task)
    except Exception as e:
        print(traceback.format_exc())
        print(f"Connection lost. Error: {e}")


@app.websocket("/ws/audio")
async def websocket_global_audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    printr.print(
        f"Audio client {websocket.client.host} connected",
        server_only=True,
        color=LogType.SYSTEM,
    )

    # Track connection state
    is_connected = True

    # Reference to the callback function for cleanup
    audio_callback = None

    try:
        # Wait for the audio player to be ready
        retry_count = 0
        max_retries = 5

        while retry_count < max_retries and is_connected:
            # Check if audio_player is ready
            if (
                core.audio_player
                and hasattr(core.audio_player, "stream_event")
                and core.audio_player.stream_event is not None
            ):
                try:
                    # Define handler for audio chunks
                    async def on_audio_chunk(data: bytes):
                        nonlocal is_connected

                        if not is_connected:
                            return

                        try:
                            # Forward the audio chunk to the browser client
                            await websocket.send_bytes(data)
                        except Exception as e:
                            printr.print(
                                f"Error sending audio: {str(e)}",
                                server_only=True,
                                color=LogType.ERROR,
                            )
                            is_connected = False

                    # Save reference to the callback for later cleanup
                    audio_callback = on_audio_chunk

                    # Subscribe without expecting a return value
                    core.audio_player.stream_event.subscribe("audio", audio_callback)
                    printr.print(
                        "Audio subscription successful",
                        server_only=True,
                        color=LogType.SYSTEM,
                    )
                    break

                except Exception as e:
                    printr.print(
                        f"Error subscribing to audio: {str(e)}",
                        server_only=True,
                        color=LogType.WARNING,
                    )

            # Not ready or subscription failed, wait and retry
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(1)
            else:
                printr.print(
                    "Audio player not ready after multiple attempts",
                    server_only=True,
                    color=LogType.WARNING,
                )
                await websocket.close(code=1013)
                return

        # Keep connection open until client disconnects
        while is_connected:
            try:
                await websocket.receive_text()
            except:
                is_connected = False
                break

    except WebSocketDisconnect:
        printr.print(
            f"Audio client disconnected", server_only=True, color=LogType.SYSTEM
        )
    except Exception as e:
        printr.print(f"Audio error: {str(e)}", server_only=True, color=LogType.ERROR)
    finally:
        # Clean up subscription using the audio_callback reference
        if (
            audio_callback is not None
            and core.audio_player
            and hasattr(core.audio_player, "stream_event")
            and core.audio_player.stream_event is not None
        ):
            try:
                core.audio_player.stream_event.unsubscribe("audio", audio_callback)
                printr.print(
                    "Audio unsubscribed successfully",
                    server_only=True,
                    color=LogType.SYSTEM,
                )
            except Exception as e:
                printr.print(
                    f"Error unsubscribing from audio: {str(e)}",
                    server_only=True,
                    color=LogType.ERROR,
                )


@app.post("/start-secrets", tags=["main"])
async def start_secrets(secrets: dict[str, Any]):
    await secret_keeper.post_secrets(secrets)
    core.startup_errors = []
    await core.config_service.load_config()


@app.get("/ping", tags=["main"], response_model=CoreStatusResponse)
async def ping():
    return core.get_status()


@app.get(CALLBACK_PATH, tags=["main"], include_in_schema=False)
async def mcp_oauth_callback(
    code: str | None = None, state: str | None = None, error: str | None = None
):
    """Where an MCP authorization server sends the user's browser back.

    This is a loopback redirect, the same one every native MCP client uses. It
    has to live on the app itself rather than on a router, because the path is
    baked into the redirect URI that was registered with the provider.

    It is kept out of the OpenAPI schema on purpose: it is not part of the API
    the client calls, and generating a method for it would only invite someone
    to call it.
    """
    accepted, message = await get_oauth_service().handle_callback(code, state, error)
    return HTMLResponse(
        content=_callback_page(accepted, message),
        status_code=200 if accepted else 400,
    )


def _callback_page(accepted: bool, message: str) -> str:
    """The page the user lands on after consenting.

    Deliberately one self-contained file with no requests of its own: it is
    served by Core to an ordinary browser that has no access to the app's assets,
    and it is the last thing standing between a user and a working MCP server.
    """
    title = "Wingman AI is connected" if accepted else "Authorization failed"
    accent = "#4ade80" if accepted else "#f87171"
    # The message is whatever the authorization server put in `error`, or its
    # token-endpoint error text. Anyone who can make a browser open this URL
    # controls it, and a script running on Core's origin can read /secrets.
    message = html.escape(message)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; background:#0f1115; color:#e6e8ee;
         font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  main {{ max-width:26rem; padding:2.5rem; text-align:center; }}
  h1 {{ font-size:1.25rem; margin:0 0 .75rem; color:{accent}; }}
  p {{ margin:0; line-height:1.6; color:#a8adbd; }}
</style></head>
<body><main>
  <h1>{title}</h1>
  <p>{message}</p>
  <p style="margin-top:1rem">You can close this tab and go back to Wingman AI.</p>
</main></body></html>"""


@app.get("/client/plan", tags=["main"], response_model=str)
async def get_client_plan():
    return core.client_plan


@app.get("/client/account-name", tags=["main"], response_model=str)
async def get_client_account_name():
    return core.client_account_name


# required to generate API specs for class BenchmarkResult that is only used internally
@app.get("/dummy-benchmark", tags=["main"], response_model=BenchmarkResult)
async def get_dummy_benchmark():
    return BenchmarkResult(
        label="Sample Benchmark",
        execution_time_ms=150.0,
        formatted_execution_time=0.15,
        snapshots=[
            BenchmarkResult(
                label="Sub Benchmark",
                execution_time_ms=75.0,
                formatted_execution_time=0.075,
            )
        ],
    )


async def async_main(host: str, port: int, sidecar: bool):
    # The OAuth redirect URI points at this process, so the service cannot know
    # it until the port is known. Do it before uvicorn binds: a user cannot reach
    # the settings UI before the server is up, but the redirect URI is read the
    # moment anyone asks for a server's OAuth status.
    oauth_service = get_oauth_service()
    oauth_service.set_callback_origin(host, port)
    async def on_oauth_state_changed(mcp_name: str, is_authorized: bool, error):
        # Reconnect before telling the client: it reloads the server list on
        # this command, and the list has to show the server connected, not the
        # "needs authorization" error from boot next to an "Authorized" badge.
        if is_authorized:
            try:
                await core.config_service.reconnect_wingmen_using_mcp(mcp_name)
            except Exception as e:
                printr.print(
                    f"Could not reconnect wingmen after authorizing '{mcp_name}': {e}",
                    color=LogType.ERROR,
                    server_only=True,
                )
        await connection_manager.broadcast(
            McpOAuthStateChangedCommand(
                mcp_name=mcp_name, is_authorized=is_authorized, error=error
            )
        )

    oauth_service.set_state_changed_handler(on_oauth_state_changed)

    # Start uvicorn FIRST so Client can connect and see progress updates
    try:
        uvi_config = uvicorn.Config(app=app, host=host, port=port, lifespan="on")
        server = uvicorn.Server(uvi_config)
        server_task = asyncio.create_task(server.serve())

        # Wait for server to bind the port
        while not server.started:
            await asyncio.sleep(0.05)

        printr.print(
            f"Server listening on {host}:{port}",
            color=LogType.STARTUP,
            server_only=True,
        )
    except Exception as e:
        printr.print(f"Error starting uvicorn server: {str(e)}", color=LogType.ERROR)
        printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
        return

    try:
        # Set MIGRATING state before migrations
        await core.set_core_state(CoreState.MIGRATING, message="Migrating configurations...")
        await core.config_service.migrate_configs(system_manager)

        # Set LOADING_CONFIG state
        await core.set_core_state(CoreState.LOADING_CONFIG, message="Loading configuration...")
        await core.config_service.load_config()

        saved_secrets: list[str] = []
        for error in core.tower_errors:
            if (
                not sidecar  # running standalone
                and error.error_type == WingmanInitializationErrorType.MISSING_SECRET
                and not error.secret_name in saved_secrets
            ):
                secret = input(f"Please enter your '{error.secret_name}' API key/secret: ")
                if secret:
                    secret_keeper.secrets[error.secret_name] = secret
                    await secret_keeper.save()
                    saved_secrets.append(error.secret_name)
                else:
                    return
            else:
                core.startup_errors.append(error)

        try:
            await core.startup()
            event_loop = asyncio.get_running_loop()
            core.audio_player.set_event_loop(event_loop)
            asyncio.create_task(core.process_events())
            # Set READY state - this also sets is_started = True
            await core.set_core_state(CoreState.READY)

            # Check for keyboard hook errors (delayed to give macOS thread time to start)
            await asyncio.sleep(1)
            kb_error = keyboard.get_init_error()
            if kb_error:
                if platform.system() == "Linux":
                    msg = (
                        "Push-to-talk unavailable: keyboard access denied.\n"
                        "Run these commands, then log out and back in:\n"
                        "sudo usermod -a -G input $USER\n"
                        "sudo usermod -a -G tty $USER"
                    )
                elif platform.system() == "Darwin":
                    msg = (
                        "Push-to-talk unavailable: Accessibility permissions not granted.\n"
                        "Grant access in System Settings > Privacy & Security > Accessibility, "
                        "then restart Wingman AI."
                    )
                else:
                    msg = f"Push-to-talk unavailable: {kb_error}"
                printr.toast_warning(msg)
        except Exception as e:
            printr.print(f"Error starting Wingman AI Core: {str(e)}", color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return

        # Keep process alive via the server task
        await server_task
    finally:
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument(
        "-H",
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for the FastAPI server to listen on.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=str,
        default="49111",
        help="Port for the FastAPI server to listen on.",
    )
    parser.add_argument(
        "--sidecar",
        action="store_true",
        help="Whether or not Wingman AI Core was launched from a client (as sidecar).",
    )
    args = parser.parse_args()

    host = args.host
    port = int(args.port)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # No running event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    atexit.register(exit_handler)

    def signal_handler(sig, frame):
        printr.print(
            "SIGINT/SIGTERM received! Initiating shutdown...",
            color=LogType.SYSTEM,
            server_only=True,
        )

        async def _shutdown_then_stop():
            await shutdown()
            loop.stop()

        # Let shutdown complete before stopping the loop
        asyncio.ensure_future(_shutdown_then_stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        loop.run_until_complete(async_main(host=host, port=port, sidecar=args.sidecar))
    except ConfigValidationError:
        # The error message was already formatted and displayed by the config service
        # (toast_error). Just record the traceback in the log file silently so the
        # terminal shows only the clean, user-friendly message.
        printr.logger.info(f"Config validation failed at startup:\n{traceback.format_exc()}")
    except Exception as e:
        printr.print(f"Error starting application: {str(e)}", color=LogType.ERROR)
        printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)

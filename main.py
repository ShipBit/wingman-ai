import argparse
import asyncio
from enum import Enum
from os import path
import sys
from contextlib import asynccontextmanager
from typing import Literal, get_args, get_origin
import uvicorn
from pynput import keyboard
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.routing import APIRoute
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from api.commands import WebSocketCommandModel
from api.enums import ENUM_TYPES
from services.command_handler import CommandHandler
from services.connection_manager import ConnectionManager
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.system_manager import SystemManager
from wingman_core import WingmanCore

port = None
host = None

connection_manager = ConnectionManager()

printr = Printr()
Printr.set_connection_manager(connection_manager)


app_is_bundled = getattr(sys, "frozen", False)
app_root_dir = sys._MEIPASS if app_is_bundled else path.dirname(path.abspath(__file__))

secret_keeper = SecretKeeper(app_root_dir)
SecretKeeper.set_connection_manager(connection_manager)

version_check = SystemManager()
is_latest = version_check.check_version()

# uses the Singletons above, so don't move this up!
core = WingmanCore(
    app_root_dir=app_root_dir,
    app_is_bundled=app_is_bundled,
)
listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # executed before the application starts
    modify_openapi()

    yield

    # executed after the application has finished
    await connection_manager.shutdown()
    listener.stop()


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)


def custom_openapi():
    global host

    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Wingman AI Core API",
        version="1.0.0",
        description="Communicate with the Wingman AI Core",
        routes=app.routes,
    )

    # Add custom server configuration
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    openapi_schema["servers"] = [{"url": f"{host}:{port}"}]

    # Ensure the components.schemas key exists
    openapi_schema.setdefault("components", {}).setdefault("schemas", {})

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
app.include_router(version_check.router)
app.include_router(secret_keeper.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    command_handler = CommandHandler(connection_manager, core, secret_keeper, printr)
    try:
        while True:
            message = await websocket.receive_text()
            await command_handler.dispatch(message, websocket)
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
        printr.print("Client disconnected", server_only=True)


async def async_main(host: str, port: int, sidecar: bool):
    errors = await core.load_config()

    # TODO: handle the errors
    # if error.secret_missing and
    #   !sidecar: prompt in terminal
    #   else queue secret prompts and send to client
    # other errors?

    listener.start()
    listener.wait()

    config = uvicorn.Config(app=app, host=host, port=port, lifespan="on")
    server = uvicorn.Server(config)
    await server.serve()


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
        type=int,
        default=8000,
        help="Port for the FastAPI server to listen on.",
    )
    parser.add_argument(
        "--sidecar",
        type=bool,
        default=False,
        help="Whether or not Wingman AI Core was launched from a client (as sidecar).",
    )
    args = parser.parse_args()

    host = args.host
    port = args.port

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # No running event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    finally:
        loop.run_until_complete(async_main(host=host, port=port, sidecar=args.sidecar))

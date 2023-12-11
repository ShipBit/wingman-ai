from os import path
import sys
from contextlib import asynccontextmanager
import uvicorn
from pynput import keyboard
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from services.connection_manager import ConnectionManager
from services.enums import ToastType
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from services.version_check import VersionCheck
from wingman_core import WingmanCore

connection_manager = ConnectionManager()


printr = Printr()
Printr.set_ws_manager(connection_manager)

app_root_dir = path.abspath(path.dirname(__file__))
secret_keeper = SecretKeeper(app_root_dir)
SecretKeeper.set_ws_manager(connection_manager)

version_check = VersionCheck()
is_latest = version_check.check_version()

# uses the Singletons above, so don't move this up!
core = WingmanCore(
    app_root_dir=app_root_dir,
    app_is_bundled=getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"),
)
listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # executed before the application starts
    await core.load_context()
    core.activate()
    listener.start()
    listener.wait()

    yield

    # executed after the application has finished
    await connection_manager.shutdown()
    listener.stop()


app = FastAPI(lifespan=lifespan)
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
    try:
        while True:
            command = await websocket.receive_text()
            printr.print(command, server_only=True)
            command_parts = command.split("::")
            command_name = command_parts[0]
            command_params = command_parts[1:]

            if command_name == "client_ready":
                await connection_manager.client_ready(websocket)
            elif command_name == "change_context":
                context = command_params[0]
                await core.load_context(context)
                core.activate()
                printr.print(
                    f"Loaded context: {context or 'default'}", toast=ToastType.NORMAL
                )
            elif command_name == "secret":
                secret_name = command_params[0]
                secret_value = command_params[1]
                secret_keeper.secrets[secret_name] = secret_value
                secret_keeper.save()
                printr.print(f"Secret '{secret_name}' saved", toast=ToastType.NORMAL)
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
        printr.print("Client disconnected", server_only=True)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

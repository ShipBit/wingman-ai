import os
import subprocess

cmd = [
    "python",
    "-m",
    "PyInstaller",
    "main.py",  # your main file with ui.run()
    "--name",
    "WingmanAI",  # name of your app
    # "--onefile",
    '--windowed', # prevent console appearing, only use with ui.run(native=True, ...)
    "--icon",
    "assets/icons/wingman-ai.png",
    "--noconfirm",
    "--hidden-import",
    "edge_tts",
   "--collect-all",
    "pedalboard_native",
    "--collect-all",
    "tkinter",
    "--hidden-import",
    "darkdetect",
    "--add-data",
    f"assets{os.pathsep}assets",
    "--add-data",
    f"services{os.pathsep}services",
    "--add-data",
    f"configs{os.pathsep}configs",
    "--add-data",
    f"wingmen{os.pathsep}wingmen",
    "--add-data",
    f"audio_samples{os.pathsep}audio_samples",
    "--add-data",
    f".venv/Lib/site-packages/customtkinter{os.pathsep}customtkinter/",
    "--add-data",
    f".venv/Lib/site-packages/darkdetect{os.pathsep}darkdetect/",
    "--add-data",
    f".venv/Lib/site-packages/elevenlabs{os.pathsep}elevenlabs/",
    "--add-data",
    f".venv/Lib/site-packages/websockets{os.pathsep}websockets/",
    "--add-data",
    f".venv/Lib/site-packages/pedalboard{os.pathsep}pedalboard/",
    "--add-data",
    f".venv/Lib/site-packages/pedalboard_native{os.pathsep}pedalboard_native/",
    "--add-data",
    f".venv/Lib/site-packages/pedalboard_native.cp311-win_amd64.pyd{os.pathsep}.",
    "--add-data",
    f"LICENSE{os.pathsep}."
]
subprocess.call(cmd)


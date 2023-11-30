import os
import subprocess
import shutil

cmd = [
    "python",
    "-m",
    "PyInstaller",
    "main.py",  # your main file with ui.run()
    "--name",
    "WingmanAI",  # name of your app
    # "--onefile",
    #'--windowed', # prevent console appearing, only use with ui.run(native=True, ...)
    "--icon",
    "assets/icons/wingman-ai.png",
    "--noconfirm",
    "--hidden-import",
    "edge_tts",
    "--collect-all",
    "tkinter",
    "--hidden-import",
    "darkdetect",
    # "--add-data",
    # f"assets{os.pathsep}assets",
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
    f".venv/Lib/site-packages/darkdetect{os.pathsep}darkdetect/"
]
subprocess.call(cmd)

shutil.copytree("assets", "dist/WingmanAI/assets")

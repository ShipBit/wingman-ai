import os
import subprocess
from pathlib import Path

cmd = [
    "pyinstaller",
    "main.py",  # your main file with ui.run()
    "--name",
    "WingmanAI",  # name of your app
    # "--onefile",
    #'--windowed', # prevent console appearing, only use with ui.run(native=True, ...)
    "--noconfirm",
    "--add-data",
    f"config.example.yaml{os.pathsep}.",
    "--hidden-import",
    "edge_tts",
    "--add-data",
    f"services{os.pathsep}services",
    "--add-data",
    f"wingmen{os.pathsep}wingmen",
    "--add-data",
    f"audio_samples{os.pathsep}audio_samples",
]
subprocess.call(cmd)

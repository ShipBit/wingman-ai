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
    # "--windowed",  # prevent console appearing, only use with ui.run(native=True, ...)
    "--icon",
    "assets/icons/wingman-ai.png",
    "--noconfirm",
    "--paths",
    "venv/Lib/site-packages",
    "--add-data",
    f"venv/Lib/site-packages/azure/cognitiveservices/speech{os.pathsep}azure/cognitiveservices/speech",
    "--add-data",
    f"assets{os.pathsep}assets",
    "--add-data",
    f"services{os.pathsep}services",
    "--add-data",
    f"configs/system/config.example.yaml{os.pathsep}configs/system/.",
    "--add-data",
    f"wingmen{os.pathsep}wingmen",
    "--add-data",
    f"audio_samples{os.pathsep}audio_samples",
    "--add-data",
    f"LICENSE{os.pathsep}.",
]
subprocess.call(cmd)

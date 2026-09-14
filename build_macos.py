import os
import subprocess

# The Azure Speech SDK used to be bundled here. It went out with the provider on
# 2026-09-11 and is no longer in requirements.txt, but this line survived —
# harmless on a developer machine where the old package is still in the venv,
# and a hard failure in CI, where the venv is built fresh and PyInstaller aborts
# on an --add-data source that does not exist.

cmd = [
    "pyinstaller",
    "main.py",  # your main file
    "--name",
    "WingmanAiCore",  # name of your app
    "--noconfirm",
    "--icon",
    "assets/wingman-ai.ico",
    "--paths",
    f"{os.path.join('venv', 'lib', 'python3.11', 'site-packages')}",  # adapted with venv/lib/python3.11/site-packages
    "--add-data",
    os.pathsep.join(["assets", "assets"]),
    "--add-data",
    os.pathsep.join(["services", "services"]),
    "--add-data",
    os.pathsep.join(["configs/system/config.example.yaml", "configs/system/."]),
    "--add-data",
    os.pathsep.join(["wingmen", "wingmen"]),
    "--add-data",
    os.pathsep.join(["skills", "skills"]),  # Bundle skills directly (not via templates)
    "--add-data",
    os.pathsep.join(
        ["templates/configs", "templates/configs"]
    ),  # Config templates only
    "--add-data",
    os.pathsep.join(["audio_samples", "audio_samples"]),
    "--add-data",
    os.pathsep.join(["LICENSE", "."]),
]

subprocess.call(cmd)

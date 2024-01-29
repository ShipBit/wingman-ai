import os
import subprocess

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
    os.pathsep.join(
        [
            os.path.join(
                "venv",
                "lib",
                "python3.11",
                "site-packages",
                "azure",
                "cognitiveservices",
                "speech",
            ),
            "azure/cognitiveservices/speech",
        ]
    ),
    "--add-data",
    os.pathsep.join(["assets", "assets"]),
    "--add-data",
    os.pathsep.join(["services", "services"]),
    "--add-data",
    os.pathsep.join(["configs/system/config.example.yaml", "configs/system/."]),
    "--add-data",
    os.pathsep.join(["wingmen", "wingmen"]),
    "--add-data",
    os.pathsep.join(["audio_samples", "audio_samples"]),
    "--add-data",
    os.pathsep.join(["LICENSE", "."]),
]

subprocess.call(cmd)

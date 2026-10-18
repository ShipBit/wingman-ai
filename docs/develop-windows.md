# Developing on Windows

## Pre-requisites

You need **Python 3.11.7** and some dependencies to run Wingman AI Core. We recommend using a virtual environment to keep your system clean.

We do **NOT** recommend installing Python from the Microsoft Store because it runs in a sandbox environment and creates config files in directories we can't detect properly.

### The quick and easy way

Install Python 3.11.7 from [python.org](https://www.python.org/downloads/release/python-3117/) and add it to your `PATH`. Make sure to check the box **Add Python 3.11 to PATH** during the installation.

Then (re-)start your terminal and test with `python --version`.

### The clean and better way

Use [pyenv-win](https://github.com/pyenv-win/pyenv-win) to manage multiple Python versions on your system. Install it using their documentation, then:

```bash
pyenv install 3.11.7    # install Python with pyenv
pyenv global 3.11.7     # set your global Python version
```

Restart the terminal. Test with `python --version`.

## Install dependencies

Fork and clone the repository, then start a terminal in the root folder.

```bash
python -m venv venv                 # create a virtual environment
.\venv\scripts\activate             # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

`requirements.txt` installs one package (`pocket-tts`) from GitHub, so Git must be installed.

### NVIDIA GPU acceleration

GPU speech recognition (Parakeet) needs no extra step: `requirements.txt` installs `onnxruntime-gpu` and the CUDA 13 packages. It needs an NVIDIA GPU from the GTX 16xx / RTX 20xx series or newer and driver 580 or newer. torch is only used for Pocket TTS, which runs on the CPU.

## Models

Models (Parakeet, Pocket TTS, Silero VAD and others) are downloaded by Core on first use into the `models/` folder of the Wingman user data directory (`%APPDATA%\ShipBit\WingmanAI\models` on Windows). If you already have a Wingman AI installation, the dev environment uses the same folder, so there is nothing to copy.

## Setup Visual Studio Code

Open the root folder in Visual Studio Code. It should automatically detect the virtual environment and suggest the correct Python interpreter. If not, open the command palette (`Ctrl+Shift+P`), run `Python: Select Interpreter`, and select the `venv` you created.

The repo includes recommended extensions in `.vscode/extensions.json` — install them when prompted.

Press `F5` to launch `main.py` via the preconfigured debugger. The Wingman AI Core API server will start on `127.0.0.1:49111`. Connect the Wingman AI client to use it.

If it doesn't start, verify that:

- The virtual environment is selected as the Python interpreter
- All dependencies are installed (`pip install -r requirements.txt`)
- The integrated terminal is running from the repository root directory

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Developing Skills

See the full [Skills Developer Documentation](../skills/README.md) for everything you need to know about creating skills — discovery metadata, the `@tool` decorator, hooks, custom properties, bundling dependencies, and distribution.

If you're building a major skill or integration, please reach out on [Discord](https://www.shipbit.de/discord) first to make sure it aligns with the project's direction.

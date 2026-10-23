# Developing on macOS

## Pre-requisites

You need **Python 3.11.7** and some dependencies to run Wingman AI Core. We recommend using a virtual environment via `pyenv`.

```bash
brew update && brew upgrade                             # upgrade all packages
brew install pyenv portaudio                            # install dependencies
pyenv install 3.11.7                                    # install Python with pyenv
pyenv global 3.11.7                                     # set your global Python version
```

Then add `eval "$(pyenv init --path)"` to your `~/.zshrc` or `~/.bashrc` so that you can run `python` instead of `python3`.

Restart the terminal. Test with `python --version`.

## Install dependencies

Fork and clone the repository, then start a terminal in the root folder.

```bash
python -m venv venv                 # create a virtual environment
source venv/bin/activate            # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

`requirements.txt` installs one package (`pocket-tts`) from GitHub, so Git must be installed.

## Models

Models (Parakeet, Pocket TTS, Silero VAD and others) are downloaded by Core on first use into the `models/` folder of the Wingman user data directory (`~/Library/Application Support/WingmanAI/models` on macOS). If you already have a Wingman AI installation, the dev environment uses the same folder, so there is nothing to copy.

> **Note:** NVIDIA CUDA acceleration is not available on macOS. Parakeet and Pocket TTS run on the CPU.

## Setup Visual Studio Code

Open the root folder in Visual Studio Code. It should automatically detect the virtual environment and suggest the correct Python interpreter. If not, open the command palette (`Cmd+Shift+P`), run `Python: Select Interpreter`, and select the `venv` you created.

The repo includes recommended extensions in `.vscode/extensions.json` — install them when prompted.

Press `F5` to launch `main.py` via the preconfigured debugger. The Wingman AI Core API server will start on `127.0.0.1:49111`. Connect the Wingman AI client to use it.

If it doesn't start, verify that:

- The virtual environment is selected as the Python interpreter
- All dependencies are installed (`pip install -r requirements.txt`)
- The integrated terminal is running from the repository root directory — on macOS it sometimes opens in a parent directory, which breaks relative paths

### Allow access to microphone and input event monitoring

VSCode will ask you to give it access to your mic and to monitor input events. You have to allow both for Wingman to work. If you start the app from the terminal and see:

```text
This process is not trusted! Input event monitoring will not be possible until it is added to accessibility clients.
```

Go to `System Settings > Privacy & Security > Accessibility` and enable VSCode there.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Developing Skills

See the full [Skills Developer Documentation](../skills/README.md) for everything you need to know about creating skills — discovery metadata, the `@tool` decorator, hooks, custom properties, bundling dependencies, and distribution.

If you're building a major skill or integration, please reach out on [Discord](https://www.shipbit.de/discord) first to make sure it aligns with the project's direction.

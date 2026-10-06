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

## Copy runtime dependencies

The release version of Wingman AI bundles model files and binaries that are too large for git. For the full experience in your dev environment, you can copy these from an existing Wingman AI installation into your repository root:

| Directory | Purpose | What happens if you skip it |
| --- | --- | --- |
| `faster-whisper-models/` | Pre-downloaded speech recognition models | Models auto-download from HuggingFace on first use — can be slow. |
| `pocket-tts-models/` | PocketTTS text-to-speech model weights | Models auto-download on first use. |
| `pocket-tts-voices/` | Pre-packaged TTS voice samples | Voices auto-download on first use. |

Copying these is optional — the app will download what it needs on first launch, but this avoids timeouts.

> **Note:** NVIDIA CUDA acceleration is not available on macOS. FasterWhisper and PocketTTS will run on CPU.

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

## Setup whispercpp (optional)

WhisperCPP is an alternative local STT provider. On macOS, it cannot be autostarted and must be run manually:

1. Download the latest stable macOS release from the [whispercpp repository](https://github.com/ggerganov/whisper.cpp/releases) or build it from source
2. Download a model (e.g. `ggml-base.bin`) and place it in your whispercpp models directory
3. Start whispercpp on the host and port configured in Wingman AI — the client UI will show you the exact command
4. Restart Wingman AI Core to connect to the running whispercpp instance

Most developers use FasterWhisper (the default) and don't need whispercpp.

## Developing Skills

See the full [Skills Developer Documentation](../skills/README.md) for everything you need to know about creating skills — discovery metadata, the `@tool` decorator, hooks, custom properties, bundling dependencies, and distribution.

If you're building a major skill or integration, please reach out on [Discord](https://www.shipbit.de/discord) first to make sure it aligns with the project's direction.

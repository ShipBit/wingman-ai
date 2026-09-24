# Developing on Linux

## Pre-requisites

You need **Python 3.11.7** and some system dependencies to run Wingman AI Core. We recommend using `pyenv` to manage Python versions.

### Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev wget curl llvm libncurses-dev \
  libffi-dev liblzma-dev tk-dev portaudio19-dev libsdl2-dev
```

### Arch

```bash
sudo pacman -Syu --noconfirm base-devel openssl zlib bzip2 readline sqlite \
  wget curl llvm ncurses libffi xz tk portaudio sdl2
```

### Fedora

```bash
sudo dnf install -y gcc make openssl-devel zlib-devel bzip2-devel \
  readline-devel sqlite-devel wget curl llvm ncurses-devel \
  libffi-devel xz-devel tk-devel portaudio-devel SDL2-devel
```

### Install Python 3.11.7 with pyenv

```bash
curl https://pyenv.run | bash
```

Add the following to your `~/.bashrc` or `~/.zshrc`:

```bash
export PYENV_ROOT="$HOME/.pyenv"
command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
```

Restart the terminal, then:

```bash
pyenv install 3.11.7
pyenv global 3.11.7
```

Test with `python --version`.

### Keyboard and mouse access

Wingman AI needs access to keyboard and mouse input events. Add your user to the `input` group:

```bash
sudo usermod -aG input $USER
```

Log out and back in for the group change to take effect.

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

## torch: CPU build (recommended)

On Linux, torch from PyPI is the CUDA build and pulls in about 4 GB of NVIDIA libraries. Wingman only needs torch for Pocket TTS, which runs on the CPU. The release build installs the CPU wheel before the requirements, and you can do the same:

```bash
pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

GPU speech recognition (Parakeet) does not use torch. It runs on `onnxruntime-gpu` with the CUDA 12 packages from `requirements.txt`.

## Setup Visual Studio Code

Open the root folder in Visual Studio Code. It should automatically detect the virtual environment and suggest the correct Python interpreter. If not, open the command palette (`Ctrl+Shift+P`), run `Python: Select Interpreter`, and select the `venv` you created.

The repo includes recommended extensions in `.vscode/extensions.json` — install them when prompted.

Press `F5` to launch `main.py` via the preconfigured debugger. The Wingman AI Core API server will start on `127.0.0.1:49111`. Connect the Wingman AI client to use it.

If it doesn't start, verify that:

- The virtual environment is selected as the Python interpreter
- All dependencies are installed (`pip install -r requirements.txt`)
- The integrated terminal is running from the repository root directory

## Setup whispercpp (optional)

WhisperCPP is an alternative local STT provider. On Linux, it cannot be autostarted and must be run manually:

1. Download the latest stable Linux release from the [whispercpp repository](https://github.com/ggerganov/whisper.cpp/releases) or build it from source
2. Download a model (e.g. `ggml-base.bin`) and place it in your whispercpp models directory
3. Start whispercpp on the host and port configured in Wingman AI — the client UI will show you the exact command
4. Restart Wingman AI Core to connect to the running whispercpp instance

Most developers use FasterWhisper (the default) and don't need whispercpp.

## Developing Skills

See the full [Skills Developer Documentation](../skills/README.md) for everything you need to know about creating skills — discovery metadata, the `@tool` decorator, hooks, custom properties, bundling dependencies, and distribution.

If you're building a major skill or integration, please reach out on [Discord](https://www.shipbit.de/discord) first to make sure it aligns with the project's direction.

# wingman-ai

Wingman requires Python 3.10.X.

## Installation

### Windows

Install Python 3.10.13 and add it to your PATH.

### MacOS

Install Python with pyenv:

```bash
brew install pyenv
pyenv install 3.10.13
pyenv global 3.10.13
```

Then add `eval "$(pyenv init --path)"` to your `.zshrc` or `.bashrc` file.

Restart the terminal.
Test with `python --version` and `python3 --version`.

If you get an error like `Could not build wheels for PyAudio, which is required to install pyproject.toml-based projects`, try `brew install portaudio`, then `pip install pyaudio` again.

## Setup your development environment

```bash
python -m venv venv
.venv\scripts\activate
pip install -r requirements.txt
```

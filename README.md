# wingman-ai

Wingman AI allows you to talk to various AI providers and LLMs (like ChatGPT) via your voice, process your conversations and finally trigger actions.

![Wingman Flow](wingman-flow.png)

The idea is pretty simple but the possibilities are endless. You could for example:

- role-play with an AI while gaming for more immersion. Think _ATC_ in _Star Citizen_ or _Flight Simulator_
- enrich your gaming experiece with external data like APIs, databases, wikis or build guides
- trigger existing keybindings in games or programs
- have conversational tuturials and walkthroughs alongside your games or tools
- automate tasks on your computer
- accessibility
- ...

We presented an early prototype of Wingman AI in _Star Citizen_ on YouTube, which caused a lot of excitement and interest in the community:

[![Early prototype on Wingman in Star Citizen](https://img.youtube.com/vi/hHy7OZQX_nQ/0.jpg)](https://www.youtube.com/watch?v=hHy7OZQX_nQ)

Please note that Wingman is **NOT** limited to _Star Citizen_.

It is an external, universal tool that you can run alongside any game or program. Therefore, it does not currently interact directly with _Star Citizen_ or any game, other than its ability to trigger system-wide keypresses, which of course might have an effect on the game.
If you find a way to interact with a game, either via an API or by reading the game's memory, you could however use it to trigger actions in the game directly or to feed your models with live data.

The projects targets two different groups of users:

- Developers who want to build their own Wingmen
- Non-developers who want to use and modify existing Wingmen

## Running Wingman on your computer

### Windows

You can "just run" Wingman AI on Windows using the release package we provide. It's a bundled executable that has all the required dependencies included.

### MacOS

We don't have a ready-to-go package for you yet, sorry. It **does** run on MacOS though, most of us even develop on MacOS.

The easiest way for now is to setup your development environment like described below and to run it from source.

## Configuring Wingmen

// TODO

## Setup your development environment

Are you ready to build your own Wingman or to bring a new feature to the framework? Great! We really appreciate your help.

### Pre-requisites

You need Python 3.11.6 and some dependencies to run Wingman. We recommend using a virtual environment to keep your system clean. If you don't know what that is, don't worry, we'll guide you through the process. If you don't want to use a virtual environment, you can skip the `pyenv` parts and just run `pip install -r requirements.txt` in the repository root once you have Python installed.

#### Windows

##### The quick and easy way

Install Python 3.11.6 and add it to your `PATH`. Make sure to check the box **Add Python 3.11 to PATH** during the installation. If you forgot to do so, you can add it manually.

Then (re-)start your terminal and test with `python --version` and `python3 --version`.

##### The clean and better way

Use [pyenv-win](https://github.com/pyenv-win/pyenv-win) to manage multiple Python versions on your system. Install it using their documentation.

Then start a terminal and run:

```bash
pyenv install 3.11.6    # install Python with pyenv
pyenv global 3.11.6     # set your global Python version
```

Restart the terminal. Test with `python --version` and `python3 --version`.

#### MacOS

Start a terminal and run:

```bash
brew install pyenv      # install pyenv with Homebrew
pyenv install 3.11.6    # install Python with pyenv
pyenv global 3.11.6     # set your global Python version
```

Then add `eval "$(pyenv init --path)"` to your `.zshrc` or `.bashrc` file so that you can just run `python` instead of `python3` in your terminal.

Restart the terminal. Test with `python --version` and `python3 --version`.

### Install dependencies

Checkout the repository and start a terminal in the root folder.

#### Windows

```bash
python -m venv venv                 # create a virtual environment
.venv\scripts\activate              # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

#### MacOS

```bash
python -m venv venv                 # create a virtual environment
source venv/bin/activate            # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

If you get an error like `Could not build wheels for PyAudio, which is required to install pyproject.toml-based projects`, try

```bash
brew install portaudio
pip install pyaudio
```

#### Setup Visual Studio Code

// TODO

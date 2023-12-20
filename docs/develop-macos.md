# Developing on MacOS

## Pre-requisites

You need Python 3.11.7 and some dependencies to run Wingman. We recommend using a virtual environment to keep your system clean. If you don't know what that is, don't worry, we'll guide you through the process. If you don't want to use a virtual environment, you can skip the `pyenv` parts and just run `pip install -r requirements.txt` in the repository root once you have Python installed.

```bash
brew update && brew upgrade            # upgrade all packages
brew install pyenv portaudio           # install dependencies
pyenv install 3.11.7                   # install Python with pyenv
pyenv global 3.11.7                    # set your global Python version
```

Then add `eval "$(pyenv init --path)"` to your `~/.zshrc` or `~/.bashrc` so that you can just run `python` instead of `python3` in your terminal.

Restart the terminal. Test with `python --version` and `python3 --version`.

## Install dependencies

Checkout the repository and start a terminal in the root folder.

```bash
python -m venv venv                 # create a virtual environment
source venv/bin/activate            # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

## Setup Visual Studio Code

Once you have everything installed, open the root folder in Visual Studio Code. It should automatically detect the virtual environment (if you created one) and ask you to install the dependencies. If not, you can do so manually by opening the command palette (`Ctrl+Shift+P`) and running `Python: Select Interpreter`. Then select the virtual environment you created.

Open `main.py` and run it. You should see the Wingman AI window should pop up. If it doesn't, make sure that:

- you have the virtual environment selected
- you have installed all dependencies using `pip install -r requirements.txt`
- the integrated VSCode terminal ran the file from the repository root directory. At least on MacOS, it sometimes runs it from an outside directory, which causes issues with the relative paths. In that case, `cd` into the correct directory and run again.
- you have `main.py` active in the editor when you hit `F5` to run it

We also suggest to install the recommended extensions if you haven't already. We're not forcing any strict syntactic coding styles right now but that might (have to) change in the future. If that will happen, `pylint` will certainly be used to enforce the style and it can help you with some basic stuff already if you aren't super familiar with Python (like us).

### Allow access to microphone and input event monitoring

VSCode will ask you to give it access to your mic and to monitor your input events. You have to allow both for Wingman to work. If you start the app from the terminal and see the message

```bash
This process is not trusted! Input event monitoring will not be possible until it is added to accessibility clients.
```

Go to `System Settings > Privacy & Security > Accessibility` and enable VSCode there, too.

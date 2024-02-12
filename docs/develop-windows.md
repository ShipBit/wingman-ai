# Developing on Windows

## Pre-requisites

You need Python 3.11.7 and some dependencies to run Wingman. We recommend using a virtual environment to keep your system clean. If you don't know what that is, don't worry, we'll guide you through the process. If you don't want to use a virtual environment, you can skip the `pyenv` parts and just run `pip install -r requirements.txt` in the repository root once you have Python installed.

We do NOT recommend to install Python from the Microsoft Store because this runs in a sandbox environment and will create the Wingman config files in weird directories which we can't detect properly.

### The quick and easy way

Install Python 3.11.7 and add it to your `PATH`. Make sure to check the box **Add Python 3.11 to PATH** during the installation. If you forgot to do so, you can add it manually.

Then (re-)start your terminal and test with `python --version` and `python3 --version`.

#### The clean and better way

Use [pyenv-win](https://github.com/pyenv-win/pyenv-win) to manage multiple Python versions on your system. Install it using their documentation.

Then start a terminal and run:

```bash
pyenv install 3.11.7    # install Python with pyenv
pyenv global 3.11.7     # set your global Python version
```

Restart the terminal. Test with `python --version` and `python3 --version`.

## Install dependencies

Checkout the repository and start a terminal in the root folder.

```bash
python -m venv venv                 # create a virtual environment
.\venv\scripts\activate              # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

## Create your config

Start Wingman UI with `python main.py` and provide your OpenAI API key. Wingman will create a `config.yaml` file in the `./configs/configs/` directory. `configs`-ception, yay!

## Setup Visual Studio Code

Once you have everything installed, open the root folder in Visual Studio Code. It should automatically detect the virtual environment (if you created one) and ask you to install the dependencies. If not, you can do so manually by opening the command palette (`Ctrl+Shift+P`) and running `Python: Select Interpreter`. Then select the virtual environment you created.

Open `main.py` and run it. You should see the Wingman AI window should pop up. If it doesn't, make sure that:

- you have the virtual environment selected
- you have installed all dependencies using `pip install -r requirements.txt`
- the integrated VSCode terminal ran the file from the repository root directory. At least on MacOS, it sometimes runs it from an outside directory, which causes issues with the relative paths. In that case, `cd` into the correct directory and run again.
- you have `main.py` active in the editor when you hit `F5` to run it

We also suggest to install the recommended extensions if you haven't already. We're not forcing any strict syntactic coding styles right now but that might (have to) change in the future. If that will happen, `pylint` will certainly be used to enforce the style and it can help you with some basic stuff already if you aren't super familiar with Python (like us).

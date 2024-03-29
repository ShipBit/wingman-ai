# Developing on Linux
This will focus on debian-based distros (specifically Ubuntu), but just
search what package names should be on your system. All python/pip 
commands are distro-independent.

## Pre-requisites
Install required packages
```bash
apt install python3-tk python3.10-venv portaudio
```

for NixOs shell.nix
```nix
{ pkgs ? import <unstable> {} }:
  pkgs.mkShell {
    packages = with pkgs; [
    python311Full
    portaudio
    pyenv
    linuxHeaders
    nix-index
    pkg-config
  ];

  C_INCLUDE_PATH = "${pkgs.linuxHeaders}/include";
}
```


## Setup virtual environment (venv)
```bash
python -m venv venv                 # create a virtual environment
source venv/bin/activate            # activate the virtual environment
pip install -r requirements.txt     # install dependencies
```

## Setup Visual Studio Code
[Same as MacOs.](https://github.com/ShipBit/wingman-ai/blob/main/docs/develop-macos.md#setup-visual-studio-code)
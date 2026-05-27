# Cora: your Star Citizen AI companion

![Cora SC Header](assets/cora-sc/Cora_SC_Image.png)

Cora is a Star Citizen focused AI companion built for immersion and practical in-game support.
It combines voice interaction, keybinding automation, and specialized manager modules for mining, trading, routing, missions, lore, and more.

<div align="center">
  <img src='assets/fankit/STARCITIZEN_BLACK.png' height='100'>
&nbsp; &nbsp; &nbsp; &nbsp;
  <img src='assets/fankit/MadeByTheCommunity_Black.png' height='100'>
</div>

## Important

There is currently no packaged `.exe` release for this fork.
Please run Cora from source.

## Feature Overview

### Core Features

- Automatic loading of Star Citizen keybindings from game files (default + customized mappings)
- Generated instant commands based on available in-game actions (with localization support)
- Command chaining for in-game actions without manually providing keybinds each time
- One activation key setup for controlling multiple wingmen
- In-game overlay feedback for important actions and status updates

### Manager System (new)

Cora uses modular "Manager" components. Each manager can be enabled/disabled via config and can also be toggled at runtime.

- Runtime manager control is available via voice phrases (activate/deactivate)
- Manager capabilities can be listed during a session
- Custom manager command phrases can be configured in `features.manager_command_phrases`

### Available Managers

#### Navigation Manager

- Opens starmap and automates route setup to destinations
- Captures and caches click coordinates for reliable repeated routing
- Supports location name resolution and route execution flow

#### Component Manager

- Searches ship components (coolers, power plants, quantum drives, shields)
- Filters by size, class, and grade
- Returns purchase location and pricing hints

#### Delivery Mission Manager

- Captures delivery missions from in-game screenshots (OCR)
- Maintains active mission list and calculates optimized route order
- Guides next pickup/dropoff step and persists mission state on disk

#### Mining Manager

- Captures refinery work orders from in-game UI
- Stores active refinery work orders locally
- Retrieves or removes locally stored active refinery work orders
- Looks up likely mining resources by radar signature value

#### Trading Division Manager (TDD)

- Provides commodity and trade route information
- Supports route search by origin/destination and commodity focus
- Uses UEX data for trade decisions

#### UEX Data Runner Manager

- Reads terminal commodity prices via OCR
- Validates extracted price data before submission
- Sends buy/sell terminal data to UEX

#### Lore Manager

- Searches Galactapedia lore entries
- Fetches current lore news
- Summarizes detailed article content in TTS-friendly format

#### Issue Council Manager

- Searches known Star Citizen issues and symptoms
- Ranks relevant bug reports and potential duplicates
- Supports creating issue drafts when no good match exists

#### Macro Manager

- Manages named macros with runtime activation/deactivation
- Supports interval keypress sequences, countdowns, reminders, and beep ticker macros
- Includes configurable spoken command phrases and macro reload commands

#### Advanced Generic Log Manager

- Maintains persistent session logs
- Supports filtered retrieval and full-history queries
- Builds and stores custom/automatic summaries

## Screenshot-based Features

Some managers use in-game screenshots (for example Delivery, Mining, UEX Data Runner).

- Screenshots are only triggered by explicit voice command
- Capture is restricted to active Star Citizen window
- OCR/analysis is processed locally through the configured workflow

## Quick Start

1. Install Python `3.11.6`.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start Cora:

```bash
python main.py
```

5. Open `configs/configs/config.yaml` and enable desired managers under `star-citizen-ai.features`.

## Configuration Notes

- Main template: `configs/system/config.example.yaml`
- Runtime config: `configs/configs/config.yaml`
- Manager toggles live under `star-citizen-ai.features`
- Voice phrase overrides for manager toggles live under `star-citizen-ai.features.manager_command_phrases`

## Development

Setup guides:

- [Windows development](docs/develop-windows.md)
- [MacOS development](docs/develop-macos.md)

Useful entry points:

- `main.py`
- `wingmen/star_citizen_wingman.py`
- `wingmen/star_citizen_services/function_manager.py`

Additional docs:

- [FAQ](FAQ.md)
- [Available Edge TTS voices](docs/available-edge-tts-voices.md)

## Demo

[![Feature Demonstration of Cora](https://img.youtube.com/vi/5eE5VLuKtTw/0.jpg)](https://youtu.be/5eE5VLuKtTw)

## If you want to refer to this project

Icon:

![Cora SC Icon](assets/icons/context-icon.png)

Further images:

- [Cora SC Icon 300x300](assets/cora-sc/Cora_icon_300.png)
- [Cora SC Icon 500x500](assets/cora-sc/Cora_icon_500.png)

Project URL: https://github.com/kalumet/cora-sc/tree/kalu_1_sc

README URL: https://github.com/kalumet/cora-sc/blob/kalu_1_sc/README.md

Star Citizen profile: https://robertsspaceindustries.com/citizens/eXpG_kalumet

Contact: via Spectrum or GitHub.

## Acknowledgements and Copyright Notice

"This project is not endorsed by or affiliated with the Cloud Imperium or Roberts Space Industries group of companies. All game content and materials are copyright Cloud Imperium Rights LLC and Cloud Imperium Rights Ltd. Star Citizen, Squadron 42, Roberts Space Industries, and Cloud Imperium are registered trademarks of Cloud Imperium Rights LLC. All rights reserved."

This project also relies on community data providers:

- United Express Corporation API: https://uexcorp.space/
- Star Citizen Wiki API: https://star-citizen.wiki/

## Open Source Acknowledgements

Thanks to the maintainers of the open source projects used by Cora:

- [ShipBit wingman-ai](https://github.com/ShipBit/wingman-ai)
- [opencv](https://github.com/opencv/opencv)
- [pytesseract](https://github.com/madmaze/pytesseract)
- [screeninfo](https://github.com/rr-/screeninfo)
- [edge-tts](https://github.com/rany2/edge-tts)
- [openai-python](https://github.com/openai/openai-python)
- [openai-whisper](https://github.com/openai/whisper)
- [elevenlabslib](https://github.com/lugia19/elevenlabslib)
- [pydirectinput](https://github.com/learncodebygaming/pydirectinput)
- [PyAutoGUI](https://github.com/asweigart/pyautogui)
- [sounddevice](https://github.com/spatialaudio/python-sounddevice/)
- [soundfile](https://github.com/bastibe/python-soundfile)
- [scipy](https://github.com/scipy/scipy)
- [numpy](https://github.com/numpy/numpy)
- [packaging](https://github.com/pypa/packaging)
- [pyinstaller](https://github.com/pyinstaller/pyinstaller)
- [faqtory](https://github.com/willmcgugan/faqtory)

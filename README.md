# Wingman AI

Wingman AI allows you to talk to various AI providers and LLMs (like ChatGPT) via your voice, process your conversations and finally trigger actions.

![Wingman Flow](assets/wingman-flow.png)

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

We try to make it as easy as possible for both groups to get started. If you're a developer, you can just clone the repository and start building your own Wingman. If you're not a developer, you can start with pre-built Wingman from us or the community and [tweak them](#configure-wingmen) to your needs.

## Run Wingman on your Computer / Mac

Get the latest release of Wingman AI in the [releases](https://github.com/ShipBit/wingman-ai/releases) section. Make sure to download the correct one for your system (PC / Mac).

Unzip it and "just run" Wingman AI. It's a bundled executable that has all the required dependencies included.

There could be a Windows Security Warning: IMAGE
This is because it's not propperly signed yet. We are working on it. In the meantime just DO THIS

Before you get too excited and see it fail on first attempt, open `config.yaml` and fill in your API key(s). Please read the [config section](#configure-wingmen)!

### Running Wingman AI

First wait for the welcome screen to appear. It will show you the available Wingmen and their activation keys.

![Wingman Welcome Screen](assets/welcome-screen.png)

This means you can have multiple Wingmen active at the same time. Each is bound to a different activation key. If you see the welcome screen, you're good to go. So start by pressing a specific activation key and hold it down while you talk to your Wingman. Let go of the key when you're done talking. The Wingman AI console do not need to have the focus, so you can just have it running in the background, while you are playing your game. After this you'll see the Wingman's response and other helpful output in the console. To close Wingman AI, just press `CTRL+C` in the console or close the whole console window.

## Default Wingmen

We provide several pre-built Wingmen to get you started quickly.

### OpenAI Wingmen

The next two Wingmen are based on OpenAI API's. The basic process looks like this: Your speech will be recognized by the Whisper API, it then sends the text to the GPT-4 Turbo API, the API responds with a text, which is then read out to you by the Text to speech API. It's literally chatting with ChatGPT. That also means you can customize the Wingmen's behavior by providing your own GPT prompt (in the `config.yaml`).

The magic happens if you configure commands / key-bindings in the `config.yaml`. GPT will then try to match your request with the configured commands and trigger them for you. It will automatically select the best matching command based on the name of the command. So make sure to give it a good name (e.g. `RequestLandingPermission`).

You can find more information about the API in the [OpenAI API documentation](https://beta.openai.com/docs/introduction).

#### Board-computer

The board-computer is your AI companion helping you with all kinds of things. Basically you can talk to it and it will respond to you via GPT. It can also trigger commands / keypresses for you. These are defined in the `config.yaml`. It's a good starting point to get to know Wingman AI.

#### ATC

The ATC wingman is basically the same as the board-computer, but it's specialized on ATC chatter. This is a showcase in how you can build specialized Wingmen for specific use cases / scenarios. The main difference is that it uses a different GPT prompt and a different set of commands.

### Free-Wingman

This is an example of a Wingman that does not use OpenAI online API's and just relies on free to use tools. It's a good starting point if you want to build your own Wingman with different AI services / models. It uses [Open-Source Whisper](https://github.com/openai/whisper) from OpenAI, which runs locally on your machine. On the first start it will download a basic model. This will take some time, based on your internet connection, so be patient. If you say something, it will recognize your speech, but will not send it to GPT. It will try to match your phrases with the ones defined in the `config.yaml` and trigger the configured commands for you. It will also read out the response to you via [Edge-TTS](https://github.com/rany2/edge-tts). Please read the [commands](#commands) section for more information on how to define commands.

## Commands

tbd

## Configure Wingmen

All relevant settings are stored in [config.yaml](https://github.com/ShipBit/wingman-ai/blob/main/config.example.yaml).

If you're running our executable, you'll find your config file next to the executable in the same directory.

If you're running from source, you'll find it as `config.example.yaml` in the repository root. Rename that file to `config.yaml`.

We added several preconfigured Wingmen to show you a wide variety of examples and to get you started quickly. Read the documentation in the file for more information.

The minimal change you have to make is to provide your [OpenAI API key](https://platform.openai.com/account/api-keys) for the preconfigured Wingmen. There is a global setting for this in the `config.yaml`. Replace `YOUR_API_KEY` with your key.

## Set up your development environment

Are you ready to build your own Wingman or to bring a new feature to the framework? Great! We really appreciate your help.

Please follow our guides to get started:

- [Windows](docs/develop-windows.md)
- [MacOS](docs/develop-macos.md)

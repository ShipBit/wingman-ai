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

Get the latest release of Wingman AI in the [releases](https://github.com/ShipBit/wingman-ai/releases) section. Make sure to download the correct one for your operating system.

Unzip it and "just run" Wingman AI. It's a bundled executable that has all the required dependencies included.

There will be a Windows SmartScreen security warning: IMAGE

The problem is that our package is currently _unsigned_ which triggers pretty aggressive Windows SmartScreen warnings when you try to run the executable from our package. Windows is not wrong here. We have to buy an expensive EV certificate that contains a hardware key that is sent via... physical mail. This will take a while, of course, and we didn't want to delay the first test iteration for this.
So if you're not comfortable with running a fairly random executable from the internet on your Windows machine, please wait for a later version. Or try running our application directly in Python from code, like your fellow developers should. Or just trust us.

Before you get too excited and see it fail on first attempt, open `config.yaml` and fill in your API key(s). Please read the [config section](#configure-wingmen)!

### Running Wingman AI

First wait until the welcome screen appears. It shows you the available wingmen and their activation keys.

![Wingman welcome screen](assets/welcome-screen.png)

You can have several wingmen active at the same time. Each one is bound to a different activation key. When you see the welcome screen, you're ready to go. So start by pressing a specific activation key and hold it down while talking to your wingman (push-to-talk). Release the key when you're done talking.

The Wingman AI console doesn't need to be focused, so you can just leave it running in the background while you play your game. You will then see the Wingman's response and other helpful output in the console.

To exit Wingman AI, simply press `CTRL+C` in the console or close the console window.

## Default Wingmen

We provide several pre-built Wingmen to get you started quickly.

### OpenAI Wingmen

Our first two Wingmen are based on OpenAI APIs. The basic process is as follows:

- Your speech is transcribed by the **Whisper API**.
- The transcript is then sent as text to the **GPT-4 Turbo API**, which responds with a text
- The response is then read to you by the **Text-to-Speech API**.

This is literally a chat with ChatGPT. This also means that you can customize the wingmen's behavior by giving the wingman a context (or `system message`) with your own GPT prompt in the `config.yaml`.

The magic happens when you configure _commands_ or key bindings in the `config.yaml`. GPT will then try to match your request with the configured commands and trigger them for you. It will automatically select the best matching command based only on its name, so make sure you give it a good one (e.g. `RequestLandingPermission`).

More information about the API can be found in the [OpenAI API documentation](https://beta.openai.com/docs/introduction).

#### Board computer

The board computer is your AI companion that helps you with all kinds of things. You can talk to it and it answers you via GPT. It can also trigger [commands](#commands) / button presses for you. These are defined in the `config.yaml`. It is a good starting point to get to know Wingman AI.

#### ATC

The ATC Wingman is basically the same as the board computer, but it specializes in ATC chatter. This is a showcase example of how to build specialized wingmen for specific use cases/scenarios. The main difference is that it uses a different GPT prompt and a different set of commands.

### StarHead Wingman

![StarHead](https://star-head.de/assets/images/logo/LOGO_@290.png)

This is where it really gets interesting. The StarHead Wingman is a specialized Wingman for _Star Citizen_ that uses the [StarHead](https://star-head.de) API to enrich your gaming experience with external data. It is a showcase example of how to build specialized wingmen for specific use cases/scenarios.

StarHead is a community project that aims to provide a platform for _Star Citizen_ players to share their knowledge and experience. Right now, it is mainly focused on the trading aspect of _Star Citizen_. With a huge database of trading items, shop inventories and prices, it allows you to find the best trade routes and make the most profit.
A huge community of players is constantly working on keeping the data up to date.

For Updates and more information, visit the [StarHead website](https://star-head.de) or follow @KNEBEL on:

- [Twitch](https://www.twitch.tv/knebeltv)
- [YouTube](https://www.youtube.com/@Knebel_DE)

The StarHead Wingman allows you to access the StarHead API via voice. In version 1 you can ask for the best trade route, based on your ship, your location and your budget. If you forget to provide one of these parameters, the Wingman will ask you for it. It will then call the StarHead API and read the result to you.

The cool thing is: It will remember everything and you can ask follow-up questions. For example, you can ask what the start point of the route is, or what the next stop is. You can also ask for the best trade route from a different location or with a different ship.

### Free-Wingman

This is an example of a wingman that **does not** use OpenAI's online APIs and only relies on freely available tools instead. It is a good starting point if you want to create your own wingman with different AI services or models. It uses [Open-Source Whisper](https://github.com/openai/whisper) from OpenAI, which runs **locally on your machine**.

The first time you start it, a base model is downloaded. This may take some time depending on your internet connection, so be patient. When you say something, it will recognize your language but will not send it to GPT. It will try to match your phrases with the ones defined in the `config.yaml` and trigger the configured commands for you. It will also read you the response via [Edge-TTS](https://github.com/rany2/edge-tts).

Please refer to the [commands](#commands) section for more information on how to define commands.

## Commands

Commands are the heart of the Wingman AI, as they add "functions" in addition to pure conversations. Commands are defined in `config.yaml` and are activated by the corresponding Wingman as a result of a conversation with you. In the first version, they are mainly used to trigger keystrokes, but they can also be used for other actions such as calling external APIs or executing complex scripts.

Here are the most important properties of a command:

- `name`: This is used to match your request with the command. So make sure to give it a good name (e.g. `RequestLandingPermission`). This where Wingman commands are "better" than VoiceAttack: You don't have to say a specific phrase to trigger it. This is a very powerful concept.
- `keys`: A list of keys to press. They will be triggered in the order they are defined. Each key can have these properties:
  - `key`: The key to press.
  - `modifier`: A modifier key to press with the key. _(optional)_
  - `hold`: The time to hold the key in milliseconds. _(optional)_
- `instant_activation`: A list of phrases that will trigger the command instantly (without AI roundtripping). _(optional)_
- `responses`: A list of responses. If the command is executed, a random response is picked and read out to you. _(optional)_

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

## Our Patreons and early access testers

Thank you so much for your support. We really appreciate it!

This list will inevitably remain incomplete. If you miss your name here, please let us know in [Discord](https://discord.com/invite/k8tTBar3gZ) or via [Patreon](https://www.patreon.com/ShipBit).

### Commanders

To our greatest supporters we say: `o7` Commanders!

- [**Rodney W. Harper aka Mactavious-Actual**](https://linktr.ee/rwhnc)

### Premium Donators

- [Weyland](https://robertsspaceindustries.com/orgs/corp)
- Morthius

### Wingmen

Zenith, DiVille, [Hiwada], Hades aka Architeutes, Raziel317, [CptToastey](https://www.twitch.tv/cpttoastey), NeyMR AKA EagleOne (Capt.Epic), a Bit Brutal, AlexeiX, [Dragon Aura](https://robertsspaceindustries.com/citizens/Dragon_Aura), Perry-x-Rhodan, DoublarThackery, SilentCid, Bytebool

## Open Source Acknowledgements

Wingman makes use of other Open Source projects internally (without modifying them in any way).
We would like to thank their creators for their great work and contributions to the Open Source community, especially:

- [edge-tts](https://github.com/rany2/edge-tts) - GPL-3.0
- [openai](https://github.com/openai/openai-python) - Apache-2.0
- [openai-whisper](https://github.com/openai/whisper) - MIT
- [pydirectinput](https://github.com/learncodebygaming/pydirectinput) - MIT, © 2020 Ben Johnson
- [PyAutoGUI](https://github.com/asweigart/pyautogui) - BSD 3, © 2014 Al Sweigart
- [pydub](https://github.com/jiaaro/pydub) - MIT, © 2011 James Robert
- [scipy](https://github.com/scipy/scipy) - BSD 3, © 2001-2002 Enthought, Inc. 2003-2023, SciPy Developers
- [numpy](https://github.com/numpy/numpy) - BSD 3, © 2005-2023, NumPy Developers
- [sounddevice](https://github.com/spatialaudio/python-sounddevice/) - MIT, © 2015-2023 Matthias Geier
- [soundfile](https://github.com/bastibe/python-soundfile) - BSD 3, © 2013 Bastian Bechtold
- [packaging](https://github.com/pypa/packaging) - Apache/BSD, © Donald Stufft and individual contributors

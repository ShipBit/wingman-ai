# Wingman AI Core

Official website: [https://www.wingman-ai.com](https://www.wingman-ai.com)

[![Wingman AI 1.5 Showreel](https://img.youtube.com/vi/qR8FjmQJRGE/0.jpg)](https://youtu.be/qR8FjmQJRGE 'Wingman AI Showreel')

Wingman AI allows you to use your voice to talk to various AI providers and LLMs, process your conversations, and ultimately trigger actions such as pressing buttons or reading answers. Our _Wingmen_ are like characters and your interface to this world, and you can easily control their behavior and characteristics, even if you're not a developer. AI is complex and it scares people. It's also **not just ChatGPT**. We want to make it as easy as possible for you to get started. That's what _Wingman AI_ is all about. It's a **framework** that allows you to build your own Wingmen and use them in your games and programs.

![Wingman Flow](assets/wingman-flow.png)

The idea is simple, but the possibilities are endless. For example, you could:

- **Role play** with an AI while playing for more immersion. Have air traffic control (ATC) in _Star Citizen_ or _Flight Simulator_. Talk to Shadowheart in Baldur's Gate 3 and have her respond in her own (cloned) voice.
- Get live data such as trade information, build guides, or wiki content and have it read to you in-game by a _character_ and voice you control.
- Execute keystrokes in games/applications and create complex macros. Trigger them in natural conversations with **no need for exact phrases.** The AI understands the context of your dialog and is quite _smart_ in recognizing your intent. Say _"It's raining! I can't see a thing!"_ and have it trigger a command you simply named _WipeVisors_.
- Automate tasks on your computer
- improve accessibility
- ... and much more

## Features

<div style="display: grid; grid-template-columns: repeat(4, 1fr); padding: 8px; gap: 8px;">
<img src="assets/wingman-ui-1.png"></img> <img src="assets/wingman-ui-2.png"></img> <img src="assets/wingman-ui-3.png"></img> <img src="assets/wingman-ui-4.png"></img>
</div>

Since version 2.0, Wingman AI Core acts as a "backend" API (using FastAPI and Pydantic) with the following features:

- **Push-to-talk or voice activation** to capture user audio
- **AI providers** with different models:
  - OpenAI
  - Google (Gemini)
  - Azure
  - Groq (llama3 with function calling)
  - Mistral Cloud
  - Open Router
  - Cerebras
  - Groq
  - Perplexity
  - Wingman Pro (unlimited access to several providers and models)
- **Speech-to-text providers** (STT) for transcription:
  - OpenAI Whisper
  - Azure Whisper
  - Azure Speech
  - whispercpp (local, bundled with Wingman AI)
  - Wingman Pro (Azure Speech or Azure Whisper)
- **Text-to-speech** (TTS) providers:
  - OpenAI TTS
  - Azure TTS
  - Edge TTS (free)
  - Elevenlabs
  - XVASynth (local)
- **Sound effects** that work with every supported TTS provider
- **Multilingual** by default
- **Command recording & execution** (keyboard & mouse)
  - **AI-powered**: OpenAI decides when to execute commands based on user input. Users don't need to say exact phrases.
  - **Instant activation**: Users can (almost) instantly trigger commands by saying exact phrases.
  - Optional: Predetermined responses
- **Custom Wingman** support: Developers can easily plug-in their own Python scripts with custom implementations
- **Skills** that can do almost anything. Think Alexa... but better.
- **directory/file-based configuration** for different use cases (e.g. games) and Wingmen. No database needed.
- Wingman AI Core exposes a lot of its functionality via **REST services** (with an OpenAPI/Swagger spec) and can send and receive messages from clients, games etc. using **WebSockets**.
- Sound Library to play mp3 or wav files in commands or Skills (similar to HCS Voice Packs for Voice Attack)
- AI instant sound effects generation with Elevenlabs

We (Team ShipBit) offer an additional [client with a neat GUI](https://www.wingman-ai.com) that you can use to configure everything in Wingman AI Core.

<div style="display: grid; grid-template-columns: repeat(4, 1fr); padding: 8px; gap: 8px;">
<img src="assets/wingman-ui-5.png"></img> <img src="assets/wingman-ui-6.png"></img> <img src="assets/wingman-ui-7.png"></img> <img src="assets/wingman-ui-8.png"></img>
</div>

## Is this a "Star Citizen" thing?

**No, it is not!** We presented an early prototype of Wingman AI in _Star Citizen_ on YouTube, which caused a lot of excitement and interest in the community. Star Citizen is a great game, we love it and it has a lot of interesting use-cases for Wingmen but it's not the only game we play and not the core of our interest. We're also not affiliated with CIG or _Star Citizen_ in any way.

The video that started it all:

[![Early prototype on Wingman in Star Citizen](https://img.youtube.com/vi/hHy7OZQX_nQ/0.jpg)](https://www.youtube.com/watch?v=hHy7OZQX_nQ)

Wingman AI is an external, universal tool that you can run alongside any game or program. As such, it does not currently interact directly with _Star Citizen_ or any other game, other than its ability to trigger system-wide keystrokes, which of course can have an effect on the game.
However, if you find a way to interact with a game, either through an API or by reading the game's memory, you could - in theory - use it to directly trigger in-game actions or feed your models with live data. This is **not** the focus of Wingman AI, though.

## Who is this for?

The project is intended for two different groups of users:

### Developers

If you're a developer, you can just clone the repository and start building your own Wingmen. We try to keep the codebase as open and hackable as possible, with lots of hooks and extension points. The base classes you'll need are well documented, and we're happy to help you get started. We also provide a [development guide](#develop-with-wingman-ai) to help you witht the setup. Wingman AI Core is currently 100% written in Python.

### Gamers & other interested people

If you're not a developer, you can start with pre-built Wingmen from us or from the community and adapt them to your needs. Since version 2, we offer an [eay-to-use client](https://www.wingman-ai.com) for Windows that you can use to cofigure every single detail of your Wingmen. It also handles multiple configurations and offers system-wide settings like audio device selection.

## Providers & cost

Wingman AI Core is free but the AI providers you'll be using might not be. We know that this is a big concern for many people, so we are offering "Wingman Pro" which is a subscription-based service with a flat fee for all the AI providers you need (and additional GUI features). This way, you won't have to worry about intransparent "pay-per-use" costs.

Check out the pricing and features here: [Wingman AI Pro](https://www.wingman-ai.com)

Wingman AI also supports local providers that you have to setup on your own but can then use and connect with our client for free:

### Other providers

You can also use your own API key to use the following services:

#### OpenAI

Our Wingmen use OpenAI's APIs and they charge by usage. That means: You don't pay a flat subscription fee, but rather for each call you make to their APIs. You can find more information about the APIs and their [pricing](https://openai.com/pricing) on the [OpenAI website](https://beta.openai.com/docs/introduction). You will need to create your API key:

- Navigate to [openai.com](https://openai.com/) and click on "Try ChatGPT".
- Choose "Sign-Up" and create an account.
- (if you get an error, go back to [openai.com](https://openai.com/))
- Click "Login".
- Fill in your personal information and verify your phone number.
- **Select API**. You don't need ChatGPT Plus to use Wingman AI.
- (Go to "Settings > Limits" and set a low soft and hard "usage limit" for your API key. We recommend this to avoid unexpected costs. $5 is fine for now)
- Go to "Billing" and add a payment method.
- Select "API Key" from the menu on the left and create one. Copy it! If you forget it, you can always create a new one.

#### ElevenLabs

You don't have to use Elevenlabs as TTS provider, but their voices are great and you can generate instant sound effects with their API - fully integrated into Wingman AI. You can clone any voice with 3 minutes of clean audio, e.g. your friend, an actor or a recording of an NPC in your game.

Elevenlabs offers a $5 tier with 30k characters and a $22 tier with 100k characters. Characters roll over each month with a max of 3 months worth of credits. If you're interested in the service, please consider using our [referral link here](https://elevenlabs.io/pricing?from=partnerlewis2510). It costs you nothing extra and supports Wingman AI. We get 22% of all payments in your first year. Thank you!

Signing up is very similar to OpenAI: Create your account, set up your payment method, and create an API key. Enter that API key in Wingman AI when asked.

#### Edge TTS (Free)

Microsoft Edge TTS is actually free and you don't need an API key to use it. However, it's not as "good" as the others in terms of quality. Their voices are split by language, so the same voice can't speak different languages - you have to choose a new voice for the new language instead. Wingman does this for you, but it's still "Windows TTS" and not as good as the other providers.

### Are local LLMs replacing OpenAI supported?

You can use any LLM offering an OpenAI-compatible API and connect it to Wingman AI Core easily.

## Installing Wingman AI

### Windows

- Download the installer of the latest version from [wingman-ai.com](https://www.wingman-ai.com).
- Install it to a directory of your choice and start the client `Wingman AI.exe`.
  - The client will will auto-start `Wingman AI Core.exe` in the background
  - The client will auto-start `whispercpp` in the background. If you have an NVIDIA RTX GPU, install the latest CUDA driver from NVIDIA and enable GPU acceleration in the Settings view.

If that doesn't work for some reason, try starting `Wingman AI Core.exe` manually and check the terminal or your **logs** directory for errors.

**If you're a developer**, you can also [run from source](#develop-with-wingman-ai). This way you can preview our latest changes on the `develop` branch and debug the code.

### MacOS

Wingman runs well on MacOS. While we don't offer a precompiled package for it, you can [run it from source](#develop-with-wingman-ai). Note that the TTS provider XVASynth is Windows-only and therefore not supported on MacOS.

## Who are these Wingmen?

Our default Wingmen serve as examples and starting points for your own Wingmen, and you can easily reconfigure them using the client. You can also add your own Wingmen very easily.

### Computer & ATC

Our first two default Wingmen are using OpenAI's APIs. The basic process is as follows:

- Your speech is transcribed by the configured TTS provider.
- The transcript is then sent as text to the configured LLM, which responds with text and maybe function calls.
- Wingman AI Core executes function calls which can be command executions or skill functions.
- The response is then read out to you by the configured TTS provider.
- Clients connected to Wingman AI Core are notified about progress and changes live and display them in the UI.

Talking to a Wingman is like chatting with ChatGPT but with your voice. And it can actually do everything that Python can do. This means that you can customize their behavior by giving them a backstory as starting point for your conversation. You can also just tell them how to behave and they will remember that during your conversation.

The magic happens when you configure _commands_ or key bindings. GPT will then try to match your request with the configured commands and execute them for you. It will automatically choose the best matching command based only on its name, so make sure you give it a good one (e.g. `Request landing permission`).

### StarHead

![StarHead](https://star-head.de/assets/images/logo/LOGO_@290.png)

StarHead is where it gets really interesting. This Wingman is tailored to _Star Citizen_ and uses the [StarHead API](https://star-head.de) to enrich your gaming experience with external data. It is a showcase of how to build specialized Wingmen for specific use-cases and scenarios. Simply ask StarHead for the best trade route, and it will prompt you for your ship, location, and budget. It will then call the StarHead API and read the result back to you.

Like all of our OpenAI Wingmen, it will remember the conversation history and you can ask follow-up questions. For example, you can ask what the starting point of the route, or what the next stop is. You can also ask for the best trade route from a different location or with a different ship.

StarHead is a community project that aims to provide a platform for _Star Citizen_ players to share their knowledge and experience. At the moment it is mainly focused on the trading aspect of _Star Citizen_. With a huge database of trade items, shop inventories and prices, it allows you to find the best trade routes and make the most profit. A large community of players is constantly working to keep the data up to date.

For updates and more information, visit the [StarHead website](https://star-head.de) or follow @KNEBEL on

- [Twitch](https://www.twitch.tv/knebeltv)
- [YouTube](https://www.youtube.com/@Knebel_DE)

### Noteworthy community projects

- [Community Wingmen](https://discord.com/channels/1173573578604687360/1176141176974360627)
- [Community Skills](https://discord.com/channels/1173573578604687360/1254811139867410462)
- [Different Games with Wingman AI](https://discord.com/channels/1173573578604687360/1254868009940418572)

## Can I configure Wingman AI Core without using your client?

Yes, you can! You can edit all the configs in your `%APP_DATA%\ShipBit\WingmanAI\[version]` directory.

The YAML configs are very indentation-sensitive, so please be careful.

**There is no hot reloading**, so you have to restart Wingman AI Core after you made manual changes to the configs.

### Directory/file-based configuration

Use these naming conventions to create different configurations for different games or scenarios:

- any subdirectory in your config dir is a "configuration" or use case. Do not use special characters.
  - `_[name]` (underscore): marks the default configuration that is launched on start, e.g. `_Star Citizen`.
- Inside of a configuration directory, you can create different `wingmen` by adding `[name].yaml` files. Do not use special characters.
  - `.[name].yaml` (dot): marks the Wingman as "hidden" and skips it in the UI and on start, e.g. `.Computer.yaml`.
  - `[name].png` (image): Sets an avatar for the Wingman in the client, e.g. `StarHead.png`.

There are a couple of other files and directories in the config directory that you can use to configure Wingman AI.

- `defaults.yaml` - contains the default settings for all Wingmen. This is merged with the settings of the individual Wingmen at runtime. Specific wingman settings always override the defaults. Once a wingman is saved using the client, it contains all the settings it needs to run and will no longer fallback to the defaults.
- `settings.yaml` - contains user settings like the selected audio input and output devices
- `secrets.yaml` - contains the API keys for different providers.

Access secrets in code by using `secret_keeper.py`. You can access everything else with `config_manager.py`.

## Does it support my language?

Wingman supports all languages that OpenAI (or your configured AI provider) supports. Setting this up in Wingman is really easy:

Some STT providers need a simple configuration to specifiy a non-English language. Use might also have to find a voice that speaks the desired language.

Then find the `backstory` setting for the Wingman you want to change and add a simple sentence to the `backstory` prompt: `Always answer in the language I'm using to talk to you.`
or something like `Always answer in Portuguese.`

The cool thing is that you can now trigger commands in the language of your choice without changing/translating the `name` of the commands - the AI will do that for you.

## Develop with Wingman AI

Are you ready to build your own Wingman or implement new features to the framework?

Please follow our guides to setup your dev environment:

- [Windows development](docs/develop-windows.md)
- [MacOS development](docs/develop-macos.md)

If you want to read some code first and understand how it all works, we recommend you start here (in this order):

- `http://127.0.0.1:49111/docs` - The OpenAPI (ex: Swagger) spec
- `wingman_core.py` - most of the public API endpoints that Wingman AI exposes
- The config files in `%APP_DATA%\ShipBit\WingmanAI\[version]` to get an idea of what's configurable.
- `Wingman.py` - the base class for all Wingmen
- `OpenAIWingman.py` - derived from Wingman, using all the providers
- `Tower.py` - the factory that creates Wingmen

If you're planning to develop a major feature or new integration, please contact us on [Discord](https://www.shipbit.de/discord) first and let us know what you're up to. We'll be happy to help you get started and make sure your work isn't wasted because we're already working on something similar.

## Acknowledgements

Thank you so much for your support. We really appreciate it!

### Open Source community

Wingman makes use of other Open Source projects internally (without modifying them in any way).
We would like to thank their creators for their great work and contributions to the Open Source community.

- [azure-cognitiveservices-speech](https://learn.microsoft.com/en-GB/azure/ai-services/speech-service/) - Proprietary license, Microsoft
- [edge-tts](https://github.com/rany2/edge-tts) - GPL-3.0
- [elevenlabslib](https://github.com/lugia19/elevenlabslib) - MIT, © 2018 The Python Packaging Authority
- [FastAPI](https://github.com/tiangolo/fastapi) - MIT, © 2018 Sebastián Ramírez
- [numpy](https://github.com/numpy/numpy) - BSD 3, © 2005-2023 NumPy Developers
- [openai](https://github.com/openai/openai-python) - Apache-2.0
- [packaging](https://github.com/pypa/packaging) - Apache/BSD, © Donald Stufft and individual contributors
- [pedalboard](https://github.com/spotify/pedalboard) - GPL-3.0, © 2021-2023 Spotify AB
- [platformdirs](https://github.com/platformdirs/platformdirs) - MIT, © 2010-202x plaformdirs developers
- [pydantic](https://github.com/pydantic/pydantic) - MIT, © 2017 to present Pydantic Services Inc. and individual contributors
- [pydirectinput-rgx](https://github.com/ReggX/pydirectinput_rgx) - MIT, © 2022 dev@reggx.eu, 2020 Ben Johnson
- [pyinstaller](https://github.com/pyinstaller/pyinstaller) - extended GPL 2.0, © 2010-2023 PyInstaller Development Team
- [PyYAML](https://github.com/yaml/pyyaml) - MIT, © 2017-2021 Ingy döt Net, 2006-2016 Kirill Simonov
- [scipy](https://github.com/scipy/scipy) - BSD 3, © 2001-2002 Enthought, Inc. 2003-2023, SciPy Developers
- [sounddevice](https://github.com/spatialaudio/python-sounddevice/) - MIT, © 2015-2023 Matthias Geier
- [soundfile](https://github.com/bastibe/python-soundfile) - BSD 3, © 2013 Bastian Bechtold
- [uvicorn](https://github.com/encode/uvicorn) - BSD 3, © 2017-presen, Encode OSS Ltd. All rights reserved.

### Individual persons

This list will inevitably remain incomplete. If you miss your name here, please let us know in [Discord](https://www.shipbit.de/discord) or via [Patreon](https://www.patreon.com/ShipBit).

#### Special thanks

- [**JayMatthew aka SawPsyder**](https://robertsspaceindustries.com/citizens/JayMatthew), @teddybear082, @Thaendril and @Xul for outstanding moderation in Discord, constant feedback and valuable Core & Skill contributions
- @lugia19 for developing and improving the amazing [elevenlabslib](https://github.com/lugia19/elevenlabslib).
- [Knebel](https://www.youtube.com/@Knebel_DE) who helped us kickstart Wingman AI by showing it on stream and grants us access to the [StarHead API](https://star-head.de/) for Star Citizen.
- @Zatecc from [UEX Corp](https://uexcorp.space/) who supports our community developers and Wingmen with live trading data for Star Citizen using the [UEX Corp API](https://uexcorp.space/api.html).

#### Commanders (Patreons)

To our greatest Patreon supporters we say: `o7` Commanders!

- [**JayMatthew aka SawPsyder**](https://robertsspaceindustries.com/citizens/JayMatthew)
- [**Rodney W. Harper aka Mactavious-Actual**](https://linktr.ee/rwhnc)

#### Premium Donators (Patreons)

- [The Announcer](https://www.youtube.com/TheAnnouncerLive)
- [Weyland](https://robertsspaceindustries.com/orgs/corp)
- Morthius
- [Grobi](https://www.twitch.tv/grobitalks)
- Paradox
- Gopalfreak aka Rockhound
- [Averus](https://robertsspaceindustries.com/citizens/Averus)

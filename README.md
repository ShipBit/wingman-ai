# Wingman AI

Wingman AI allows you to use your voice to talk to various AI providers and LLMs, process your conversations, and ultimately trigger actions such as pressing buttons or reading answers. Our _Wingmen_ are like characters and your interface to this world, and you can easily control their behavior and characteristics, even if you're not a developer.

AI is complex and it scares people. It's also not 'just ChatGPT'. We want to make it as easy as possible for you to get started. That's what _Wingman AI_ is all about. It's a **framework** that allows you to build your own wingmen and use them in your games and programs.

![Wingman Flow](assets/wingman-flow.png)

The idea is simple, but the possibilities are endless. For example, you could:

- **Role play** with an AI while playing for more immersion. Have air traffic control (ATC) in _Star Citizen_ or _Flight Simulator_. Talk to Shadowheart in Baldur's Gate 3 and have her respond in her own (cloned) voice.
- Get live data such as trade information, build guides, or wiki content and have it read to you in-game by a _character_ and voice you control.
- Execute keystrokes in games/applications and create complex macros. Trigger them in natural conversations with **no need for exact phrases.** The AI understands the context of your dialog and is quite _smart_ in recognizing your intent. Say _"It's raining! I can't see a thing!"_ and have it trigger a command you simply named _WipeVisors_.
- Automate tasks on your computer
- improve accessibility
- ... and much more

## Is this a "Star Citizen" thing?

**No**, it is not! We presented an early prototype of Wingman AI in _Star Citizen_ on YouTube, which caused a lot of excitement and interest in the community. Star Citizen is a great game, we love it and it has a lot of interesting use-cases for Wingmen but it's not the only game we play and not the core of our interest. We're also not affiliated with CIG or _Star Citizen_ in any way.

[![Early prototype on Wingman in Star Citizen](https://img.youtube.com/vi/hHy7OZQX_nQ/0.jpg)](https://www.youtube.com/watch?v=hHy7OZQX_nQ)

Wingman AI is an external, universal tool that you can run alongside any game or program. As such, it does not currently interact directly with _Star Citizen_ or any other game, other than its ability to trigger system-wide keystrokes, which of course can have an effect on the game.
However, if you find a way to interact with a game, either through an API or by reading the game's memory, you could - in theory - use it to directly trigger in-game actions or feed your models with live data. This is **not** the focus of Wingman AI, though.

## Who is this for?

The project is intended for two different groups of users:

### Developers

If you're a developer, you can just clone the repository and start building your own Wingmen. We try to keep the codebase as open and hackable as possible, with lots of hooks and extension points. The base classes you'll need are well documented, and we're happy to help you get started. We also provide a [development guide](#set-up-your-development-environment) to help you witht the setup. Wingman is currently 100% written in Python.

### Gamers & other interested people

If you're not a developer, you can start with pre-built wingmen from us or from the community and [reconfigure](#configure-wingmen) them to your needs. We take a very _configuration-heavy_ approach, and while it might be a bit overwhelming and confusing to edit our (very identation-sensitive) YAML config file right now, we're working on a more user-friendly UI to make it easier for you in the future.

## Installing Wingman AI

### Windows

- Download the latest version from [wingman-ai.com](https://www.wingman-ai.com).
- Extract it to a new directory of your choice. All the files, not just the `.exe`.
- Run `WingmanAI.exe` from that directory.
- There will be a Windows SmartScreen security warning (see screenshots below) because our package is currently unsigned. Sorry about that, we're working on it. Just click `More Info` and then `Run anyway` to start the application.
- Follow the instructions and enter your API key(s).
- Try talking to our default/example Wingmen. It's **push to talk**, so keep the activation key pressed while talking. Release the key when you're done talking. We're already working on a voice activation feature, but it's not ready yet.
  - _DELETE_: Board computer
  - _END_: ATC
  - _UP_: StarHead

You can ask them anything you want, so just try something like: _"Hey, what can you do for me?"_.

![Alt text](assets/win-smartscreen-1.png)

![Alt text](assets/win-smartscreen-2.png)

### MacOS

Wingman **does** run on MacOS. While we don't have a precompiled package for it yet, you can run it from source. Please see the [Developer Guide](#set-up-your-development-environment) for more information. Also note that we have to rely on [PyAutoGUI](https://github.com/asweigart/pyautogui) for key presses on MacOS, which does not work well in many games. Developing on MacOS is perfectly fine, though.

Before you get too excited and see it fail on the first try, open `config.yaml` and enter your API key(s). Please read the [config section](#configure-wingmen)!

## Running Wingman AI

// TODO when GUI is ready

<!-- Wait for the welcome screen to appear. It will show you the available wingmen and their activation keys.

![Wingman welcome screen](assets/welcome-screen.png)

You can have multiple wingmen active at the same time. Each one is bound to a different activation key. When you see the welcome screen, you're ready to go. Press and hold a specific activation key while talking to your wingman (push-to-talk). Release the key when you're done.

The Wingman AI console doesn't need to be focused, so you can leave it running in the background while you play. You will see your wingman's replies and other helpful output in the console.

To exit Wingman AI, simply press `CTRL+C` in the console or close the console window. -->

## Who are these wingmen?

Our default wingmen serve as examples and starting points for your own wingmen, and you can easily reconfigure them in the `config.yaml` file. You can also add your own wingmen to this config file.

### board-computer & atc

Our first two wingmen are based on OpenAI's APIs. The basic process is as follows:

- Your speech is transcribed by the **Whisper API**.
- The transcript is then sent as text to the **GPT-4 Turbo API**, which responds with a text.
- The response is then read out to you by the **OpenAI Text-to-Speech API**.

Before you ask: You can change all of these providers in the `config.yaml` file. We're not affiliated with any of them, and we're not paid by them.

Talking to a Wingman is like chatting with ChatGPT. This means that you can customize their behavior by giving them a `context` (or `system`) prompt as starting point for your conversation. You can also just tell them how to behave and they will remember that during your conversation. ATC and board-computer use vey different prompts, so they behave very differently. See `config.yaml` for more information.

The magic happens when you configure _commands_ or key bindings. GPT will then try to match your request with the configured commands and execute them for you. It will automatically choose the best matching command based only on its name, so make sure you give it a good one (e.g. `RequestLandingPermission`).

More information about the API can be found in the [OpenAI API documentation](https://beta.openai.com/docs/introduction).

### StarHead

![StarHead](https://star-head.de/assets/images/logo/LOGO_@290.png)

StarHead is where it gets really interesting. This wingman is tailored to _Star Citizen_ and uses the [StarHead API](https://star-head.de) to enrich your gaming experience with external data. It is a showcase of how to build specialized wingmen for specific use-cases and scenarios. Simply ask StarHead for the best trade route, and it will prompt you for your ship, location, and budget. It will then call the StarHead API and read the result back to you.

Like all of our OpenAI wingmen, it will remember the conversation history and you can ask follow-up questions. For example, you can ask what the starting point of the route, or what the next stop is. You can also ask for the best trade route from a different location or with a different ship.

StarHead is a community project that aims to provide a platform for _Star Citizen_ players to share their knowledge and experience. At the moment it is mainly focused on the trading aspect of _Star Citizen_. With a huge database of trade items, shop inventories and prices, it allows you to find the best trade routes and make the most profit. A large community of players is constantly working to keep the data up to date.

For updates and more information, visit the [StarHead website](https://star-head.de) or follow @KNEBEL on

- [Twitch](https://www.twitch.tv/knebeltv)
- [YouTube](https://www.youtube.com/@Knebel_DE)

## Configuring Wingman

Everything you can change (as non-dev) is stored in the `config.yaml' file.

**Be careful: It is very indentation-sensitive**!

Please **DO NOT** use the `SPACE` bar to indent lines in the config. Use the `TAB` key instead. Always use a single `TAB` to indent. If you're using an editor that automatically converts `TAB` to `SPACE', please disable this feature for this file.

The file is very **hierarchical**, meaning that entries _belong_ to other entries. The file begins with a general section. These are global (default) settings for all your wingmen.

![Alt text](assets/general-config.png)

The screenshot shows the general section of the config file. It has several sections or entries (colored), and these are all siblings to each other, meaning they have the same indentation level and must _align_ perfectly with each other.

After the general section come the wingmen. Each wingman is defined in its own entry. They are all _children_ of the `wingmen` entry and siblings to each other. Then each wingman has its own commands and other settings.

![Alt text](assets/wingman-config.png)

You can override any setting from the general config in a specific wingman. For example, the `board-computer` wingman overrides the global `features > enable_robot_sound_effect: false` by mirroring the exact same structure with `wingmen > board-computer > features > enable_robot_sound_effect: true`.

Note also the `commands`. The general section defines a global `ResetConversationHistory`command, meaning that every wingman has this command. Then the`board-computer`wingman adds its own keystroke command to the command list. Also note that commands start with a`-`sign. This is because they are lists of commands. You can add as many commands as you like. Please do not remove the`-` sign and add it to your new commands.

### The context prompt

### Adding and editing commands

Commands are the heart of the Wingman AI, as they add _functions_ to otherwise pure conversations. Commands are defined in `config.yaml` and are activated by the corresponding Wingman as a result of a conversation with you. In the first version, they are mainly used to trigger keystrokes, but they can also be used for other actions such as calling external APIs or executing complex scripts.

Here are the most important properties of a command:

- `name`: This is used to match your request with the command. So make sure to give it a good name (e.g. `RequestLandingPermission`). This where Wingman commands are "better" than VoiceAttack: You don't have to say a specific phrase to trigger it. This is a very powerful concept.
- `keys`: A list of keys to press. They will be triggered in the order they are defined. Each key can have these properties:
  - `key`: The key to press.
  - `modifier`: A modifier key to press with the key. _(optional)_
  - `hold`: The time to hold the key in milliseconds. _(optional)_
- `instant_activation`: A list of phrases that will trigger the command instantly (without AI roundtripping). _(optional)_
- `responses`: A list of responses. If the command is executed, a random response is picked and read out to you. _(optional)_

#### Wow, this is hard!

Yes, we know. We're working on a more user-friendly interface to make it easier for you. For now, we recommend the following tools to help you out:

- [VSCode](https://code.visualstudio.com/) with the
- [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)

Both are free and very easy to install and use. VSCode is a great editor for developers, and the YAML extension will help you with indentation by showing you errors and warnings in your config file as you type.

![Alt text](assets/vscode-yaml.png)

Notice how it has detected that something is wrong with the indentation. In this case, there is a single space before the `features` entry, which is not allowed. It also shows you visually how it should be indented.

It will be easier once you get used to it, we promise!

**Remember: Never use `SPACE`, always use `TAB`!**

## Set up your development environment

Are you ready to build your own Wingman or to bring a new feature to the framework?

Great! We really appreciate your contributions!

Please follow our guides to get started on

- [Windows](docs/develop-windows.md)
- [MacOS](docs/develop-macos.md)

## Our Patreons & Early Access Testers

Thank you so much for your support. We really appreciate it!

This list will inevitably remain incomplete. If you miss your name here, please let us know in [Discord](https://discord.com/invite/k8tTBar3gZ) or via [Patreon](https://www.patreon.com/ShipBit).

### Commanders

To our greatest supporters we say: `o7` Commanders!

- [**Rodney W. Harper aka Mactavious-Actual**](https://linktr.ee/rwhnc)

### Premium Donators

- [Weyland](https://robertsspaceindustries.com/orgs/corp)
- Morthius

### Wingmen

[Ira Robinson aka Serene/BlindDadDoes](http://twitch.tv/BlindDadDoes), Zenith, DiVille, [Hiwada], Hades aka Architeutes, Raziel317, [CptToastey](https://www.twitch.tv/cpttoastey), NeyMR AKA EagleOne (Capt.Epic), a Bit Brutal, AlexeiX, [Dragon Aura](https://robertsspaceindustries.com/citizens/Dragon_Aura), Perry-x-Rhodan, DoublarThackery, SilentCid, Bytebool, Exaust A.K.A Nikoyevitch, Tycoon3000, N.T.G, Jolan97, Greywolfe, [JayMatthew](https://robertsspaceindustries.com/citizens/JayMatthew), [Dayel Ostraco aka BlakeSlate](https://dayelostra.co/), Nielsjuh01, Manasy, Sierra-Noble, Simon says aka Asgard, JillyTheSnail, [Admiral-Chaos aka Darth-Igi], The Don, Tristan Import Error, Munkey the pirate, Norman Pham aka meMidgety, [meenie](https://github.com/meenie), [Tilawan](https://github.com/jlaluces123), Mr. Moo42, Geekdomo, Jenpai, Blitz

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

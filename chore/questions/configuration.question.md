---
title: 'Configuring Wingman AI'
alt_titles:
  - 'Edit config'
  - 'commands'
  - 'My command is not working'
  - 'Wingman error'
  - 'Key is not pressed'
  - 'What is this key called?'
  - 'config error'
  - 'How do I open or edit the config?'
  - 'My prompt is not working'
  - 'What is a yaml file?'
  - 'How can I use another provider?'
---

Everything you can change (as non-dev) is stored in the `config.yaml` file.

**Be careful: It is very indentation-sensitive**!

Please **DO NOT** use the `SPACE` bar to indent lines in the config. Use the `TAB` key instead. Always use a single `TAB` to indent. If you're using an editor that automatically converts `TAB` to `SPACE`, please disable this feature for this file.

The file is very **hierarchical**, meaning that entries _belong_ to other entries. The file begins with a general section. These are global (default) settings for all your wingmen.

![Alt text](assets/general-config.png)

The screenshot shows the general section of the config file. It has several sections or entries (colored), and these are all siblings to each other, meaning they have the same indentation level and must _align_ perfectly with each other.

After the general section come the wingmen. Each wingman is defined in its own entry. They are all _children_ of the `wingmen` entry and siblings to each other. Then each wingman has its own commands and other settings.

![Alt text](assets/wingman-config.png)

You can override any setting from the general config in a specific wingman. For example, the `board-computer` wingman overrides the global `features > enable_robot_sound_effect: false` by mirroring the exact same structure with `wingmen > board-computer > features > enable_robot_sound_effect: true`.

Note also the `commands`. The general section defines a global `ResetConversationHistory`command, meaning that every wingman has this command. Then the`board-computer`wingman adds its own keystroke command to the command list. Also note that commands start with a`-`sign. This is because they are lists of commands. You can add as many commands as you like. Please do not remove the`-` sign and add it to your new commands.

## The context prompt

The context prompt describes the _character_ of your Wingman and controls how it behaves. It's a simple ChatGPT prompt that you can edit to your liking. You can do **a lot** with prompting, so play around with that.

You can use the [OpenAI ChatGPT web interface](https://chat.openai.com/) or our **no login required** [open source](https://github.com/ShipBit/slickgpt) tool called [SlickGPT](https://slickgpt.vercel.app/) to test your prompts.

Prompting is a science unto itself. If you want to get better at it, there are great resources like [learnprompting.org](https://learnprompting.org/).

## Adding and editing commands

Commands are the heart of the Wingman AI, as they add _functions_ to otherwise pure conversations. Commands are defined in `config.yaml` and are activated by the corresponding Wingman as a result of a conversation with you. In the first version, they are mainly used to trigger keystrokes, but they can also be used for other actions such as calling external APIs or executing complex scripts.

Here are the most important properties of a command:

- `name`: This is used to associate your request to the command. So make sure to give it a good name, e.g. `RequestLandingPermission`. Use `camelCasing` to separate words. No spaces and don't write everything in lowercase. You do not have to say a specific phrase to trigger the command because the AI is smart enough to detect which command you _meant_. This is a very powerful concept and one of the reason this is way better than other (sometimes "aggressive" 🤭) `voice-to-key` tools.
- `keys`: A list of keys to press. They will be triggered in the order they are defined. Any key can have these properties:
  - `key`: The key to press.
  - `modifier`: A modifier key to press with the key. _(optional)_
  - `hold`: The time to hold the key in milliseconds. _(optional)_
  - `wait`: The time to wait until the next key in this command is pressed _(optional)_
- `instant_activation`: A list of phrases that will trigger the command immediatale without AI round-tripping. _(optional)_
- `responses`: A list of responses. If the command is executed, a random response will be chosen and read out to you. _(optional)_

## Are there tools to help me?

Yaml is hard, we know. We're working on a more user-friendly interface to make it easier for you. For now, we recommend the following tools to help you out:

- [VSCode](https://code.visualstudio.com/) with the
- [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)

Both are free and very easy to install and use. VSCode is a great editor for developers, and the YAML extension will help you with indentation by showing you errors and warnings in your config file as you type.

![Alt text](assets/vscode-yaml.png)

Notice how it has detected that something is wrong with the indentation. In this case, there is a single space before the `features` entry, which is not allowed. It also shows you visually how it should be indented.

It will get easier once you get used to it, we promise!

**Remember: Never use `SPACE`, always use `TAB`!**

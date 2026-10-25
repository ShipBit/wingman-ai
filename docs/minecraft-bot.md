# Minecraft Bot

The Minecraft Bot skill puts your Wingman into your Minecraft Java world as a player. You talk to your Wingman as you would to a friend in the game, and its player walks over, follows you, collects wood, crafts, builds, fights and answers in the game chat. What it says there, your Wingman says to you in its own voice, word for word: the Wingman and the player are one character, with the Wingman's backstory and in your language.

The bot is a [Mindcraft](https://github.com/mindcraft-bots/mindcraft) agent. Mindcraft is the open source project that gives a Mineflayer bot a language model as its brain and a library of actions such as `goToPlayer`, `collectBlocks`, `craftRecipe`, `smeltItem`, `attack` and `goal`. The skill starts Mindcraft for you, creates the bot and connects it to the game.

**The bot thinks with your Wingman's model.** Mindcraft usually needs its own API key. Here it does not: the skill runs a small local endpoint that Mindcraft talks to, and every thought of the bot is answered by whatever model your Wingman uses, the Wingman AI subscription, your own API key or a local model. There is nothing extra to sign up for.

## What you need

- **Minecraft Java Edition** in a version that Mineflayer supports. As of October 2026 that is every version up to 26.1.x; 26.2 and later are not supported yet. Pick an older version under *Installations* in the Minecraft launcher. Bedrock Edition does not work.
- **Node.js 22 LTS** from [nodejs.org](https://nodejs.org/). On Windows, tick *Automatically install the necessary tools* in the installer: Mindcraft has a few native modules. Node.js 24 and newer fail to build them; 20 is the oldest the skill accepts.
- **Mindcraft** itself. Open a terminal and run:

  ```bash
  git clone https://github.com/mindcraft-bots/mindcraft.git
  cd mindcraft
  npm install
  ```

  You can also download the repository as a ZIP file and unpack it. `npm install` takes a few minutes and ends with warnings about patches; those are fine. You do not need a `keys.json` or an API key.

## Set up the skill

The skill is not discoverable by default. Open your Wingman in the client, turn on the Minecraft Bot skill and fill in its settings:

| Setting | What it does |
|---|---|
| Mindcraft folder | The folder from the `git clone` above, the one with `package.json` and `node_modules` in it. |
| Node.js executable | `node` if it is on your PATH. Otherwise the full path to `node.exe` (Windows) or `node` (macOS, Linux). |
| Bot name | The bot's player name in the game, 3 to 16 letters, digits or underscores. Empty uses the Wingman's name. |
| Your Minecraft name | Your own player name, so that "come to me" and "follow me" find you. |
| Minecraft host and port | `127.0.0.1` and port `0` for a world on this computer opened with *Open to LAN*; the skill finds the world by itself. Enter the port the game shows in chat if that fails, or a server's address and port. |
| Minecraft version | `auto` reads the version from the game. Set one only if that fails. |
| Account | *Offline* for LAN worlds and offline-mode servers. *Microsoft account* logs the bot in with the account of your Minecraft launcher, which online-mode servers require. |
| Behavior | Mindcraft's base profile. *Survival* hunts and defends itself, *Assistant* does not hunt, *Creative* skips the survival habits, *God mode* may cheat. |
| AI requests per minute | The brake, see below. Default 10. |
| Speak what the bot says | The Wingman reads out the bot's chat lines. Off shows them only in the chat. |
| Let the bot write code | Mindcraft's `newAction`: the model writes and runs JavaScript for free-form tasks like "build a house with a door and windows". Powerful, but code written by an AI runs on your computer. Keep it off on public servers. |

## Play

1. Start Minecraft, open a world, press Esc and choose *Open to LAN*.
2. Talk to your Wingman: "Spawn the Minecraft bot", or just give an order: "Tell Andy to come to me". The bot joins the game by itself when it is not there yet; the first join takes ten to thirty seconds.
3. Give it work: "follow me", "collect ten oak logs", "craft a wooden pickaxe", "what do you have in your inventory?", "go to bed", "kill that zombie", "build a small shelter here". Mindcraft handles multi-step tasks on its own, for example it collects the logs it needs before it crafts.
4. "Stop", "wait" or "do nothing" halts your player at once; it stays in the game and waits. "Leave the game" takes it out and shuts Mindcraft down.

The player answers in the game chat, and your Wingman says the same lines to you. A line that comes later, like "Done, I have the logs", is spoken when it comes. When the bot talks faster than it can be spoken, only its newest line is read out; the rest is in the chat. What was said in the game while you were busy is given to the Wingman with your next message, so you can ask "did it work?".

## What the bot can see

The bot does not see your screen. It knows its own position, what blocks and creatures are near it, and it finds the nearest block of a kind. On its own, Mindcraft has no idea where *you* look, so "this block", "over there" and "behind you" mean nothing to it. The skill gives the bot three senses for exactly that:

- **By name.** "Get the torches here", "is there a chest?", "find a sheep": the bot looks for the thing within 32 blocks, blocks and creatures, no matter where you look at that moment, and gets how many there are and the nearest with coordinates. "Torch" also finds torches on walls, "flower" every flower.
- **Where you look.** "What is this?", "mine this", "go where I am looking", "the island over there, twenty blocks in that direction": the bot asks where you stand, which way you look and what your line of sight hits, block or creature, with coordinates, and acts on them.
- **A look around.** "Behind you is lava", "go into the water", "go into the house": the bot asks what lies around it within 32 blocks, water, lava, doors, beds, chests, tables, furnaces, bells, hay, trees, ore, creatures and players, each with direction and distance from where it faces.
- **Turning.** It can turn to face a spot without walking there.
- **Doors.** "Go into the house", "come out": the bot walks through a door to its other side and opens it on the way. Without this it walks to the nearest reachable spot, which is outside the wall, and believes it is inside. The look around also tells it whether it stands under a roof.

Point your crosshair at what you mean and the bot gets it right most of the time; a cliff edge or a far shore works, the sky does not. How well the bot uses its senses depends on the model: the prompt tells it when to use which.

Under the hood these are three commands added to Mindcraft while it loads (`senses_hook.mjs` and `senses.mjs` in the skill folder, preloaded through `NODE_OPTIONS`). Nothing in your Mindcraft folder is changed, and if a future Mindcraft looks different, the bot simply plays without them.

## The brake

Every thought of the bot is one request on your Wingman's model and on your plan, about 2,000 to 3,000 tokens each. A quick order costs one or two requests. A bot that works towards a goal thinks again every few seconds until it is done, and a bot that keeps running into a wall keeps thinking too.

*AI requests per minute* limits that. When the limit is reached, the bot waits for the next free slot; it does not fail. The default of 10 is enough for playing along and keeps a runaway bot from eating your monthly budget in an afternoon. Raise it if the bot feels slow on long tasks.

An order also ends after ten commands at most, and the bot is told to give up after two failures in a row and say what went wrong. A bot that keeps running into the same wall stops instead of thinking forever. "Stop" halts it at any time.

Small local models struggle with Mindcraft's command syntax, and a model with a small context window cannot take the bot's prompt at all. The bot works best with the subscription or a cloud model you bring your own key for.

## Troubleshooting

- **"Node.js was not found"**: install Node.js 22 LTS, or put the full path to `node` into the skill settings.
- **"Mindcraft's packages are not installed"**: run `npm install` in the Mindcraft folder.
- **The bot does not join the game.** The Wingman's answer ends with Mindcraft's last log lines. "Supported versions are ..." means the game's version is too new for Mineflayer; pick an older one in the launcher. "MC server not found" means no world is open to LAN, or host and port are wrong. On an online-mode server the bot needs the *Microsoft account* setting.
- **The bot says "My brain disconnected, try again."** The model call failed. The Wingman's log says why, usually a provider error or the plan's quota.
- **Your player leaves and is back ten seconds later.** That is Mindcraft, not a crash: after smelting, and when the bot restarts itself, it logs in again to re-read its inventory.
- **The bot says it has an item but cannot give or drop it.** Mineflayer's view of the inventory goes stale after crafting in the 2x2 grid. The bot is told to restart itself once in that case, which re-reads the inventory. If it keeps failing, tell it to restart itself.
- **`npm install` fails with C++ errors**: you are on Node.js 24 or newer. Install Node.js 22 LTS and run `npm install` again.
- Mindcraft's own web page is at the port the Wingman's log mentions when the bot starts, `http://localhost:<port>`. It shows the bot's view of the world and its chat.

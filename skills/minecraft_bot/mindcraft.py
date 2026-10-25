"""Runs Mindcraft's MindServer and talks to it over Socket.IO.

A ``MindcraftBridge`` owns one Node.js process (the MindServer, started by
launcher.mjs from the user's Mindcraft checkout) and one Socket.IO client. The
client's handlers run on the Socket.IO thread and only call back into the
skill; those callbacks must be thread-safe.

Also here: the pure helpers that build the agent settings, tidy the bot's chat
lines and describe its state, so tests can check them without Node.js.

MindServer events used (src/mindcraft/mindserver.js in Mindcraft):
  create-agent (settings, callback)   start a bot from a settings object
  send-message (agent, {from, message})  a chat line for the bot to act on
  bot-output (agent, message)         everything the bot says, broadcast
  agents-status ([{name, in_game}])   who is in the game
  listen-to-agents / state-update     the bot's full state, once a second
  stop-agent, destroy-agent, shutdown
"""

from __future__ import annotations

import json
import platform
import re
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional

LAUNCHER = Path(__file__).parent / "launcher.mjs"
SENSES_HOOK = Path(__file__).parent / "senses_hook.mjs"
MINDCRAFT_ENTRY = Path("src") / "mindcraft" / "mindcraft.js"
MIN_NODE_MAJOR = 20
"""Mineflayer wants a current Node.js, and the senses hook needs module.register (Node 20.6)."""
READY_MARKER = "WINGMAN_MINDSERVER_READY"
AGENT_EXITED_MARKER = "Agent process exited"
AGENT_RESTARTING_MARKER = "Restarting agent..."
"""Mindcraft restarts the agent process after !smeltItem and !restart (a fresh
login re-reads the inventory) and after a crash. The bot is back in about ten seconds."""

_COMMAND_NOTE = re.compile(r"\*[^*\n]*\bused\b[^*\n]*\*")
_COMMAND_CALL = re.compile(r"!\w+(?:\([^)]*\))?")
_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")


class MindcraftError(Exception):
    """Mindcraft could not be started or reached."""


def mindcraft_problem(directory: str) -> str:
    """Why ``directory`` is no usable Mindcraft checkout, or '' if it is."""
    if not directory:
        return "Set the Mindcraft folder in the skill settings."
    root = Path(directory)
    if not root.is_dir():
        return f"The Mindcraft folder does not exist: {directory}"
    if not (root / MINDCRAFT_ENTRY).is_file():
        return (
            f"{directory} is no Mindcraft checkout: {MINDCRAFT_ENTRY.as_posix()} is missing. "
            "Clone github.com/mindcraft-bots/mindcraft and point the skill at that folder."
        )
    if not (root / "node_modules").is_dir():
        return f"Mindcraft's packages are not installed. Run 'npm install' in {directory}."
    return ""


def node_version(node: str) -> Optional[tuple[int, ...]]:
    """The version of the Node.js executable, like (22, 18, 0); None if it cannot run."""
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def keys_file_api_key(directory: str) -> str:
    """The OPENAI_API_KEY from Mindcraft's keys.json, if the user has one.

    Mindcraft prefers keys.json over the environment, so a bot in such a
    checkout presents that key to the proxy instead of the skill's token.
    """
    try:
        with open(Path(directory) / "keys.json", encoding="utf-8") as handle:
            keys = json.load(handle)
    except (OSError, ValueError):
        return ""
    value = keys.get("OPENAI_API_KEY") if isinstance(keys, dict) else ""
    return str(value).strip() if value else ""


def node_options_with_senses(existing: str = "") -> str:
    """NODE_OPTIONS for every process Mindcraft starts: Node preloads
    senses_hook.mjs, which gives the bot the senses in senses.mjs (where the
    player looks, what lies around the bot). What the user had in NODE_OPTIONS
    stays in front of it."""
    option = f"--import={SENSES_HOOK.resolve().as_uri()}"
    return " ".join(part for part in ((existing or "").strip(), option) if part)


def canned_greeting(bot_name: str) -> str:
    """What Mindcraft says at spawn when no init message is set. Costs no model call."""
    return f"Hello world! I am {bot_name}"


_SYSTEM_LINES = ("Agent stopped.", "Shutting up.", "Exiting.", "Restarting.")


def is_system_line(text: str) -> bool:
    """A line Mindcraft puts into the chat itself, not the bot's character: the
    result of a forced command like !stop or !stfu, or the good-bye before a restart."""
    line = (text or "").strip()
    return any(line.startswith(prefix) for prefix in _SYSTEM_LINES)


def sanitize_bot_name(name: str, fallback: str = "Wingman") -> str:
    """A Minecraft player name: 3 to 16 letters, digits or underscores."""
    cleaned = _NAME_CHARS.sub("", (name or "").strip().replace(" ", "_").replace("-", "_"))
    if len(cleaned) < 3:
        cleaned = _NAME_CHARS.sub("", fallback) or "Wingman"
    return cleaned[:16]


def clean_bot_line(text: str) -> str:
    """A bot chat line fit to be spoken: no command syntax, no empty filler.

    Mindcraft notes a used command as "*used goToPlayer*" and, with full
    command syntax on, leaves "!collectBlocks('oak_log', 10)" in the line.
    Neither is something to read out.
    """
    if not text:
        return ""
    line = _COMMAND_NOTE.sub(" ", str(text))
    line = _COMMAND_CALL.sub(" ", line)
    line = re.sub(r"\s+", " ", line).strip()
    if not re.search(r"\w", line):
        return ""
    return line


PERSONA_LIMIT = 1500
"""Characters of the Wingman's backstory that go into the bot's prompt."""

DEFAULT_PERSONA = "a friendly, casual, effective and efficient player"


def conversing_prompt(persona: str, language: str, player_name: str = "") -> str:
    """Mindcraft's chat prompt for the bot, with the Wingman's character and language.

    Built on Mindcraft's default (profiles/defaults/_default.json): the
    $PLACEHOLDERS are filled by Mindcraft with the bot's name, memory, stats,
    inventory, command docs and examples. The Wingman and the bot are one
    character, so the Wingman's backstory is the bot's, and the bot answers
    in the user's language right away: no translation step in between.

    Rules of our own: a few words before every command, because the player
    hears only the bot's words and a bare command leaves the Wingman with
    nothing to say for twenty seconds. Two keep the bot out of loops: it gives
    up after two failures and tells the player, and when giving or dropping an
    item fails although the inventory lists it, it restarts once. Mineflayer's view of
    the inventory goes stale after crafting in the 2x2 grid (ghost stacks stay
    in the crafting slots); a fresh login re-reads it, which is also why
    Mindcraft itself restarts the agent after smelting.
    """
    persona = " ".join((persona or "").split())
    if len(persona) > PERSONA_LIMIT:
        persona = persona[:PERSONA_LIMIT].rsplit(" ", 1)[0] + " ..."
    player = (
        f"The player you talk to is {player_name}; in commands like !goToPlayer use exactly that name.\n"
        if player_name
        else ""
    )
    view = f'!playerView("{player_name}")' if player_name else '!playerView("<player name>")'
    senses = (
        "You cannot see the player's screen, but you have senses: when the player speaks of what they see or "
        f"where they look (this block, over there, in front of me, where I am looking), use {view} first. "
        "When they speak of your surroundings (behind you, the water, the house, the lava), use !lookAround "
        "first. Then act on the coordinates you got, for example with !goToCoordinates.\n"
    )
    return (
        "You are $NAME, a player in Minecraft. You can converse with players, see, move, mine, "
        "build and interact with the world by using commands.\n"
        f"Your character: {persona or DEFAULT_PERSONA}\n"
        f"{player}{senses}"
        "$SELF_PROMPT Be brief: one or two short sentences, spoken like a friend playing alongside. "
        "Don't apologize, don't give instructions or make lists unless asked, don't refuse requests. "
        "Don't pretend to act, use commands immediately when requested. "
        "Do NOT say 'Sure, I've stopped. *stops*', say 'Sure, I'll stop. !stop'. "
        f"Always put a few words for the player before a command, like 'On my way! !goToPlayer(\"{player_name or 'Player'}\", 3)': "
        "a command alone is not an answer, the player hears only your words. "
        "Respond only as $NAME, never pretend to be someone else. "
        "If you have nothing to say or do, respond with just a tab '\t'.\n"
        "If a command fails twice in a row, do not try it again: say what went wrong and wait for the player. "
        "If giving or dropping an item fails although your inventory lists it, your inventory view is stale: "
        "use !restart once, then try again.\n"
        "Summarized memory:'$MEMORY'\n$STATS\n$INVENTORY\n$COMMAND_DOCS\n$EXAMPLES\n"
        f"Speak {language} in everything you say. Commands keep their exact syntax, "
        "like !collectBlocks(\"oak_log\", 10).\n"
        "Conversation Begin:"
    )


def build_agent_settings(
    *,
    bot_name: str,
    proxy_url: str,
    host: str,
    port: int,
    version: str,
    auth: str,
    base_profile: str,
    allow_coding: bool,
    persona: str = "",
    language: str = "English",
    player_name: str = "",
) -> dict:
    """The settings object for Mindcraft's create-agent event.

    The bot's chat and embedding models point at the skill's proxy, so every
    thought goes through this Wingman's model. The prompt is kept small
    (shortened command docs, one example, fifteen messages of history): it is
    the user's plan that pays for it, and the facade caps a request anyway.
    An order ends after ten commands at most: a bot that keeps running into
    the same wall stops instead of thinking forever.
    """
    model = {"api": "openai", "url": proxy_url, "model": "wingman"}
    return {
        "profile": {
            "name": bot_name,
            "model": model,
            "embedding": dict(model),
            "cooldown": 2000,
            "conversing": conversing_prompt(persona, language, player_name),
        },
        "minecraft_version": version or "auto",
        "host": host or "127.0.0.1",
        "port": -1 if not port or int(port) <= 0 else int(port),
        "auth": auth or "offline",
        "base_profile": base_profile or "survival",
        "init_message": None,  # Mindcraft's canned hello at spawn, no model call for it
        "only_chat_with": [],
        "speak": False,
        "language": "en",
        "allow_vision": False,
        "allow_insecure_coding": bool(allow_coding),
        "code_timeout_mins": 10,
        "max_messages": 15,
        "max_commands": 10,
        "num_examples": 1,
        "relevant_docs_count": 3,
        "show_command_syntax": "none",
        "narrate_behavior": False,
        "chat_ingame": True,
        "chat_bot_messages": True,
        "render_bot_view": False,
        "load_memory": False,
        "spawn_timeout": 60,
    }


def format_status(state: Optional[dict], *, running: bool, in_game: bool, bot_name: str) -> str:
    """One short paragraph about the bot for the model, from Mindcraft's full state."""
    if not running:
        return "No Minecraft bot is running."
    if not in_game:
        return f"{bot_name} is not in the game right now (Mindcraft is running)."
    if not state:
        return f"{bot_name} is in the game; no details have arrived yet."

    gameplay = state.get("gameplay") or {}
    position = gameplay.get("position") or {}
    where = ", ".join(
        f"{axis} {position.get(axis):.0f}"
        for axis in ("x", "y", "z")
        if isinstance(position.get(axis), (int, float))
    )
    setting = ", ".join(
        str(gameplay[key]) for key in ("biome", "timeLabel", "weather") if gameplay.get(key)
    )
    parts = [f"{bot_name} is in the game"]
    if where:
        parts[-1] += f" at {where}"
    if gameplay.get("dimension"):
        parts[-1] += f" in the {gameplay['dimension']}"
    if setting:
        parts[-1] += f" ({setting})"
    parts[-1] += "."
    if gameplay.get("health") is not None:
        parts.append(f"Health {gameplay.get('health')}/20, hunger {gameplay.get('hunger')}/20.")
    action = state.get("action") or {}
    kind = action.get("kind")
    if kind in ("idle", "stopped"):
        parts.append("Doing: nothing, waiting for instructions.")
    elif kind == "thinking":
        parts.append("Doing: thinking about its goal.")
    elif str(action.get("current") or "").startswith("mode:"):
        # Mindcraft's automatic behaviors, like "mode:hunting" or "mode:self_defense"
        parts.append(f"Doing: {action['current'][5:].replace('_', ' ')} on its own.")
    elif action.get("current"):
        parts.append(f"Doing: {action['current']}.")
    nearby = state.get("nearby") or {}
    players = nearby.get("humanPlayers") or []
    parts.append(f"Players nearby: {', '.join(players) if players else 'none'}.")
    counts = (state.get("inventory") or {}).get("counts") or {}
    if counts:
        top = sorted(counts.items(), key=lambda item: -item[1])[:8]
        more = f" and {len(counts) - len(top)} more" if len(counts) > len(top) else ""
        parts.append("Inventory: " + ", ".join(f"{name} x{count}" for name, count in top) + more + ".")
    else:
        parts.append("Inventory: empty.")
    return " ".join(parts)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


class MindcraftBridge:
    """One MindServer process and the Socket.IO connection to it."""

    def __init__(
        self,
        *,
        node: str,
        mindcraft_dir: str,
        env: dict[str, str],
        on_log: Callable[[str], None],
        on_bot_output: Callable[[str, str], None],
        on_agents_status: Callable[[list], None],
        on_state_update: Callable[[dict], None],
    ) -> None:
        self._node = node
        self._dir = mindcraft_dir
        self._env = env
        self._on_log = on_log
        self._on_bot_output = on_bot_output
        self._on_agents_status = on_agents_status
        self._on_state_update = on_state_update
        self.port = 0
        self._process: Optional[subprocess.Popen] = None
        self._client = None
        self._reader: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._log: deque[str] = deque(maxlen=300)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def connected(self) -> bool:
        return bool(self._client is not None and self._client.connected)

    def recent_log(self, count: int = 12) -> list[str]:
        lines = list(self._log)
        return lines[-count:]

    def start(self, timeout: float = 40.0) -> None:
        """Start the MindServer and connect to it. Raises MindcraftError."""
        if self.running:
            return
        if not LAUNCHER.is_file():
            raise MindcraftError(f"The skill's launcher is missing: {LAUNCHER}")
        self.port = find_free_port()
        self._ready.clear()
        self._log.clear()
        try:
            self._process = subprocess.Popen(
                [self._node, str(LAUNCHER), "--port", str(self.port)],
                cwd=self._dir,
                env=self._env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            raise MindcraftError(f"Could not start Node.js ('{self._node}'): {error}") from error

        self._reader = threading.Thread(
            target=self._read_output, name="minecraft-bot-mindcraft-log", daemon=True
        )
        self._reader.start()

        deadline = time.monotonic() + timeout
        while True:
            code = self._process.poll()
            if code is not None:
                tail = "\n".join(self.recent_log(6))
                raise MindcraftError(f"Mindcraft exited with code {code}.\n{tail}".strip())
            if self._ready.is_set() or _port_open(self.port):
                break
            if time.monotonic() > deadline:
                self.shutdown(timeout=2)
                raise MindcraftError("Mindcraft's MindServer did not come up in time.")
            time.sleep(0.2)

        try:
            self._connect()
        except Exception as error:
            self.shutdown(timeout=2)
            raise MindcraftError(f"Could not connect to Mindcraft's MindServer: {error}") from error

    def _read_output(self) -> None:
        process = self._process
        if not process or not process.stdout:
            return
        for raw in iter(process.stdout.readline, ""):
            line = raw.rstrip()
            if not line:
                continue
            self._log.append(line)
            if READY_MARKER in line:
                self._ready.set()
            try:
                self._on_log(line)
            except Exception:
                pass

    def _connect(self) -> None:
        import socketio  # bundled with the skill; imported here so the module loads without it

        client = socketio.Client(
            reconnection=True, reconnection_attempts=5, logger=False, engineio_logger=False
        )
        client.on("bot-output", self._bot_output)
        client.on("agents-status", self._agents_status)
        client.on("state-update", self._state_update)
        client.connect(f"http://localhost:{self.port}", wait_timeout=15)
        client.emit("listen-to-agents")
        self._client = client

    def _bot_output(self, agent_name, message) -> None:
        try:
            self._on_bot_output(str(agent_name), str(message))
        except Exception:
            pass

    def _agents_status(self, agents) -> None:
        try:
            self._on_agents_status(list(agents or []))
        except Exception:
            pass

    def _state_update(self, states) -> None:
        try:
            self._on_state_update(dict(states or {}))
        except Exception:
            pass

    def create_agent(self, settings: dict, timeout: float = 150.0) -> dict:
        """Ask the MindServer to start the bot. Returns its {success, error} answer."""
        if not self._client:
            return {"success": False, "error": "Not connected to Mindcraft."}
        try:
            response = self._client.call("create-agent", settings, timeout=timeout)
        except Exception as error:
            return {"success": False, "error": f"{type(error).__name__}: {error}"}
        if isinstance(response, (list, tuple)):
            response = response[0] if response else None
        if not isinstance(response, dict):
            return {"success": False, "error": "Mindcraft gave no answer."}
        return response

    def send_message(self, agent: str, sender: str, message: str) -> None:
        if self._client:
            self._client.emit("send-message", (agent, {"from": sender, "message": message}))

    def stop_agent(self, agent: str) -> None:
        if self._client:
            self._client.emit("stop-agent", agent)

    def destroy_agent(self, agent: str) -> None:
        if self._client:
            self._client.emit("destroy-agent", agent)

    def shutdown(self, timeout: float = 8.0) -> None:
        """Stop the bot and the MindServer. Safe to call twice."""
        client, process = self._client, self._process
        self._client = None
        if client is not None:
            try:
                if client.connected:
                    client.emit("shutdown")
            except Exception:
                pass
        if process is not None and process.poll() is None:
            deadline = time.monotonic() + timeout
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            if process.poll() is None:
                self._kill_tree(process)
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
        self._process = None

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:
        # The MindServer spawns one Node process per bot. On Windows terminate()
        # leaves the children running, so the whole tree is killed.
        if platform.system() == "Windows":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

"""Minecraft Bot: an AI-controlled player in the user's Minecraft world.

The bot is a Mindcraft agent (github.com/mindcraft-bots/mindcraft). This skill
starts Mindcraft, puts the bot into the game and passes the user's spoken
instructions on to it. The bot's "brain" is this Wingman's own model: Mindcraft
is pointed at a local OpenAI-compatible endpoint (llm_proxy.py) that answers
through self.wingman.ai, so the bot needs no API key of its own and runs on
the subscription, the user's key or a local model, whatever the Wingman uses.

Threads: the Socket.IO client, the proxy server and Mindcraft's log reader run
on their own threads. Their callbacks only touch thread-safe state (a queue,
events, plain assignments). Everything that talks to the Wingman runs on an
event loop: the tools on the turn's loop, the speaker on its own.
"""

from __future__ import annotations

import asyncio
import os
import queue
import secrets
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from api.enums import SpeechPriority, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.skill_local_ai import SamplingPreset
from skills.minecraft_bot.llm_proxy import ContextTooLong, ProxyServer, RateLimiter, create_app
from skills.minecraft_bot.mindcraft import (
    AGENT_EXITED_MARKER,
    MIN_NODE_MAJOR,
    MindcraftBridge,
    MindcraftError,
    build_agent_settings,
    canned_greeting,
    clean_bot_line,
    format_status,
    keys_file_api_key,
    mindcraft_problem,
    node_version,
    sanitize_bot_name,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

RELAY_PROMPT_FILE = Path(__file__).parent / "relay_prompt.md"
SPAWN_TIMEOUT = 75.0
"""Seconds to wait for the bot to appear in the game after Mindcraft accepted it."""
REPLY_TIMEOUT = 20.0
"""Seconds tell_minecraft_bot waits for the bot's first line. The bot's thinking is one call on the user's model."""
REPLY_SETTLE = 4.0
"""After a line, a further line within this time still belongs to the same reply: a
query like !inventory makes the bot answer in two steps, a thought apart."""
REPLY_MAX_EXTRA = 12.0
"""The most a reply may grow after its first line."""
SPAWN_GRACE = 1.0
"""Seconds after the bot spawned, so its first chat line is spoken and not taken for a reply."""
DEFAULT_REQUESTS_PER_MINUTE = 10


class _ReplyCollector:
    """Catches the bot's lines while a tell_minecraft_bot call waits for them."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._first = threading.Event()
        self._lock = threading.Lock()

    def add(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
        self._first.set()

    def wait(self, first_timeout: float, settle: float, max_extra: float = REPLY_MAX_EXTRA) -> str:
        if not self._first.wait(first_timeout):
            return ""
        seen = 0
        deadline = time.monotonic() + max_extra
        while time.monotonic() < deadline:
            with self._lock:
                count = len(self.lines)
            if count == seen:
                break
            seen = count
            time.sleep(min(settle, max(0.0, deadline - time.monotonic())))
        with self._lock:
            return " ".join(self.lines)


class _WingmanModel:
    """The proxy's backend: the bot thinks with this Wingman's main model."""

    def __init__(self, skill: "MinecraftBot") -> None:
        self._skill = skill

    async def chat(self, messages: list[dict]) -> str:
        try:
            return await self._skill.wingman.ai.generate(messages=messages)
        except Exception as error:
            text = str(error)
            if "limit is" in text or "too long" in text or "context" in text.lower():
                raise ContextTooLong(text) from error
            self._skill.log.error(f"The bot's model call failed: {text}")
            return ""

    async def embed(self, texts: list[str]):
        local = self._skill.wingman.local_ai
        if not local.available:
            return None
        try:
            vectors = await local.embed(texts)
        except Exception as error:
            self._skill.log.warning(f"Embeddings for the bot failed: {error}", server_only=True)
            return None
        return vectors or None


class MinecraftBot(Skill):
    """Spawns a Mindcraft bot into Minecraft and relays the user's commands to it."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._bridge: Optional[MindcraftBridge] = None
        self._proxy: Optional[ProxyServer] = None
        self._token = ""
        self._agent = ""
        self._in_game = False
        self._spawned = False
        self._agent_exited = False
        self._state: Optional[dict] = None
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._pending: Optional[_ReplyCollector] = None
        self._pending_lock = threading.Lock()
        self._services_lock = threading.Lock()
        self._unreported: deque[str] = deque(maxlen=12)
        self._speaker_run = 0

    # ------------------------------------------------------------------ config

    def _text(self, key: str, default: str = "") -> str:
        value = self.retrieve_custom_property_value(key, [])
        text = str(value).strip() if value is not None else ""
        return text or default

    def _number(self, key: str, default: int) -> int:
        value = self.retrieve_custom_property_value(key, [])
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _flag(self, key: str, default: bool) -> bool:
        value = self.retrieve_custom_property_value(key, [])
        return default if value is None else bool(value)

    def _node(self) -> str:
        return self._text("node_executable", "node")

    def _bot_name(self) -> str:
        return sanitize_bot_name(self._text("bot_name"), fallback=self.wingman.name)

    def _player_name(self) -> str:
        configured = self._text("player_name")
        if configured:
            return configured
        nearby = ((self._state or {}).get("nearby") or {}).get("humanPlayers") or []
        if len(nearby) == 1:
            return str(nearby[0])
        return "Player"

    def _config_error(self, message: str) -> WingmanInitializationError:
        return WingmanInitializationError(
            wingman_name=self.name,
            message=message,
            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
        )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        directory = self.retrieve_custom_property_value("mindcraft_dir", errors)
        problem = mindcraft_problem(str(directory or "").strip())
        if problem:
            errors.append(self._config_error(problem))
        node = self._node()
        if not shutil.which(node):
            errors.append(
                self._config_error(
                    f"Node.js was not found ('{node}'). Install Node.js 22 LTS from nodejs.org, "
                    "or set the full path to node in the skill settings."
                )
            )
        return errors

    async def get_prompt(self) -> str | None:
        base = await super().get_prompt() or ""
        if self._in_game:
            status = f"The bot {self._agent} is in the game."
        elif self._bridge and self._bridge.running:
            status = f"The bot {self._agent} is not in the game right now."
        else:
            status = "The bot has not been spawned yet; tell_minecraft_bot spawns it when needed."
        player = self._text("player_name")
        who = f" The user's Minecraft name is {player}." if player else ""
        return f"{base}\n{status}{who}".strip()

    # ------------------------------------------------------------------- tools

    @tool(name="minecraft_bot", wait_response=True)
    async def minecraft_bot(self, action: Literal["spawn", "stop", "status"]) -> str:
        """Spawns the AI bot into the running Minecraft game, stops it, or reports its status.

        Args:
            action: spawn puts the bot into the game; stop removes it and shuts Mindcraft down; status says where the bot is, its health, what it is doing and what it carries.
        """
        await self._forget_a_dead_mindcraft()
        if action == "spawn":
            return await self._spawn()
        if action == "stop":
            return await self._stop()
        return format_status(
            self._state,
            running=bool(self._bridge and self._bridge.running),
            in_game=self._in_game,
            bot_name=self._agent or self._bot_name(),
        )

    @tool(name="tell_minecraft_bot", wait_response=True)
    async def tell_minecraft_bot(self, message: str) -> str:
        """Tells the Minecraft bot what to do or asks it something. The bot plans and acts on its own and answers in chat.

        Args:
            message: One short instruction or question in English, addressed to the bot like to a player, e.g. "come to me", "follow me", "collect 10 oak logs", "craft a wooden pickaxe", "what is in your inventory?", "stop".
        """
        message = (message or "").strip()
        if not message:
            return "There was nothing to tell the bot."
        await self._forget_a_dead_mindcraft()
        if not self._in_game:
            spawned = await self._spawn()
            if not self._in_game:
                return spawned
        deadline = time.monotonic() + 15
        while not self._ready and self._in_game and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
        if not self._in_game or not self._bridge:
            return f"{self._agent} is not in the game."

        collector = _ReplyCollector()
        with self._pending_lock:
            self._pending = collector
        try:
            self._bridge.send_message(self._agent, self._player_name(), message)
            reply = await asyncio.to_thread(collector.wait, REPLY_TIMEOUT, REPLY_SETTLE)
        finally:
            with self._pending_lock:
                self._pending = None
        if reply:
            return f"{self._agent} replied: {reply}"
        return f"Delivered to {self._agent}. No reply yet; the bot's answer will be spoken when it comes."

    # ---------------------------------------------------------------- lifecycle

    async def _spawn(self) -> str:
        if self._in_game:
            return f"{self._agent} is already in the game."
        try:
            await asyncio.to_thread(self._start_services)
        except MindcraftError as error:
            return f"Could not start Mindcraft: {error}"
        except Exception as error:
            self.log.error(f"Could not start the Minecraft bot: {error}")
            return f"Could not start the Minecraft bot: {error}"

        bot = self._bot_name()
        settings = build_agent_settings(
            bot_name=bot,
            proxy_url=self._proxy.base_url,
            host=self._text("minecraft_host", "127.0.0.1"),
            port=self._number("minecraft_port", 0),
            version=self._text("minecraft_version", "auto"),
            auth=self._text("auth", "offline"),
            base_profile=self._text("base_profile", "survival"),
            allow_coding=self._flag("allow_coding", False),
        )
        self._agent = bot
        self._in_game = False
        self._spawned = False
        self._agent_exited = False
        self._state = None
        self._drain_lines()

        result = await asyncio.to_thread(self._bridge.create_agent, settings)
        if not result.get("success"):
            error = result.get("error") or "unknown error"
            return f"Mindcraft could not create the bot: {error}. {self._join_hints()}"

        self._speaker_run += 1
        self.wingman.run_in_thread(self._speaker_loop, self._speaker_run)

        deadline = time.monotonic() + SPAWN_TIMEOUT
        while time.monotonic() < deadline and not self._ready and not self._agent_exited:
            await asyncio.sleep(0.5)
        if self._ready:
            await asyncio.sleep(SPAWN_GRACE)
            self.log.info(f"{bot} joined the game. Mindcraft runs on port {self._bridge.port}.")
            return f"{bot} is now in the game and listening to you."

        self._bridge.destroy_agent(bot)
        tail = "\n".join(self._bridge.recent_log(8))
        self.log.warning(f"{bot} could not join the game. Mindcraft said:\n{tail}")
        return f"{bot} could not join the game. {self._join_hints()} Mindcraft's last lines:\n{tail}"

    async def _forget_a_dead_mindcraft(self) -> None:
        """A Mindcraft process that died takes the bot with it; the next spawn starts fresh."""
        bridge = self._bridge
        if bridge is not None and not bridge.running:
            self.log.warning("Mindcraft is no longer running; the bot is gone.", server_only=True)
            await asyncio.to_thread(self._stop_services)

    @property
    def _ready(self) -> bool:
        """In the game and spawned: Mindcraft reports the login before the bot stands in the world."""
        return self._in_game and (self._spawned or self._state is not None)

    def _drain_lines(self) -> None:
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _join_hints() -> str:
        return (
            "Check that a Minecraft Java world is open to LAN (or the server is running), "
            "that its version is one Mineflayer supports, and that host and port in the skill settings match."
        )

    async def _stop(self) -> str:
        name = self._agent if self._in_game else ""
        await asyncio.to_thread(self._stop_services)
        if name:
            return f"{name} left the game and Mindcraft was stopped."
        return "Mindcraft was stopped."

    def _start_services(self) -> None:
        """Start the model proxy and Mindcraft. Blocking; runs in a worker thread."""
        with self._services_lock:
            node = self._node()
            directory = self._text("mindcraft_dir")
            if not self._bridge or not self._bridge.running:
                problem = mindcraft_problem(directory)
                if problem:
                    raise MindcraftError(problem)
                version = node_version(node)
                if version is None:
                    raise MindcraftError(
                        f"Could not run '{node} --version'. Install Node.js 22 LTS or set the path to node in the skill settings."
                    )
                if version[0] < MIN_NODE_MAJOR:
                    raise MindcraftError(
                        f"Node.js {'.'.join(map(str, version))} is too old. Mindcraft needs Node.js {MIN_NODE_MAJOR} or newer; 22 LTS is recommended."
                    )

            if not self._proxy or not self._proxy.running:
                self._token = secrets.token_urlsafe(24)
                limiter = RateLimiter(
                    lambda: self._number("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE)
                )
                tokens = {self._token}
                users_key = keys_file_api_key(directory)
                if users_key:
                    # Mindcraft prefers keys.json over the environment: a checkout
                    # with a key in it presents that key to the proxy.
                    tokens.add(users_key)
                app = create_app(
                    _WingmanModel(self),
                    tokens,
                    limiter,
                    log=lambda line: self.log.info(line, server_only=True),
                )
                self._proxy = ProxyServer(app)
                self._proxy.start()

            if not self._bridge or not self._bridge.running:
                env = dict(os.environ)
                env["OPENAI_API_KEY"] = self._token
                self._bridge = MindcraftBridge(
                    node=node,
                    mindcraft_dir=directory,
                    env=env,
                    on_log=self._on_mindcraft_log,
                    on_bot_output=self._on_bot_output,
                    on_agents_status=self._on_agents_status,
                    on_state_update=self._on_state_update,
                )
                self._bridge.start()
                self.log.info(
                    f"Mindcraft started with Node.js {'.'.join(map(str, version))} on port {self._bridge.port}. "
                    f"The bot thinks through this Wingman's model at {self._proxy.base_url}.",
                    server_only=True,
                )

    def _stop_services(self) -> None:
        with self._services_lock:
            self._speaker_run += 1
            bridge, proxy = self._bridge, self._proxy
            self._bridge = self._proxy = None
            self._in_game = False
            self._spawned = False
            self._state = None
            self._drain_lines()
            if bridge:
                bridge.shutdown()
            if proxy:
                proxy.stop()

    async def unload(self) -> None:
        await super().unload()
        self._speaker_run += 1
        try:
            await asyncio.to_thread(self._stop_services)
        except Exception as error:
            self.log.warning(f"Stopping Mindcraft failed: {error}", server_only=True)

    # -------------------------------------------- callbacks (Mindcraft threads)

    def _on_mindcraft_log(self, line: str) -> None:
        self.log.info(f"[Mindcraft] {line}", server_only=True)
        if AGENT_EXITED_MARKER in line:
            self._agent_exited = True
        elif self._agent and line.strip() == f"{self._agent} spawned.":
            self._spawned = True

    def _on_bot_output(self, agent: str, message: str) -> None:
        if agent != self._agent:
            return
        text = clean_bot_line(message)
        if not text or text == canned_greeting(agent):
            return
        with self._pending_lock:
            pending = self._pending
        if pending is not None:
            pending.add(text)
            return
        self._lines.put(text)

    def _on_agents_status(self, agents: list) -> None:
        for agent in agents:
            if not isinstance(agent, dict) or agent.get("name") != self._agent:
                continue
            was_ready = self._ready
            self._in_game = bool(agent.get("in_game"))
            if not self._in_game:
                self._spawned = False
                self._state = None
            if was_ready and not self._in_game:
                self._lines.put("I left the game.")

    def _on_state_update(self, states: dict) -> None:
        state = states.get(self._agent)
        if isinstance(state, dict):
            self._state = state

    # ------------------------------------------------------------- the speaker

    async def _speaker_loop(self, run_id: int) -> None:
        """Says what the bot says, on its own thread and loop. Stops when run_id is stale."""
        while run_id == self._speaker_run and not self.is_unloaded:
            try:
                line = await asyncio.to_thread(self._lines.get, True, 0.5)
            except queue.Empty:
                continue
            try:
                await self._relay(line)
            except Exception as error:
                self.log.warning(f"Could not relay a bot line: {error}", server_only=True)

    async def _relay(self, line: str) -> None:
        self._unreported.append(line)
        text = await self._localize(line)
        await self.wingman.conversation.show(f"{self._agent}: {text}", skill_name=self.name)
        if self._flag("speak_bot_messages", True):
            await self.wingman.tts.speak(text, priority=SpeechPriority.EVENT)

    async def _localize(self, line: str) -> str:
        """The bot speaks English; the user may not. The support model translates when it can."""
        language = self.wingman.language
        if (language.code or "en") == "en" or not self.wingman.local_ai.available:
            return line
        try:
            template = RELAY_PROMPT_FILE.read_text(encoding="utf-8")
        except OSError:
            return line
        prompt = template.format(language=language.name, line=line)
        result = (await self.wingman.local_ai.generate(prompt, preset=SamplingPreset.PRECISE)).strip()
        result = result.strip('"').strip()
        if not result or len(result) > 4 * len(line) + 40:
            return line
        return result

    async def on_add_user_message(self, message: str) -> None:
        if not self._unreported:
            return
        lines = list(self._unreported)
        self._unreported.clear()
        await self.wingman.conversation.add_note(
            f"The Minecraft bot {self._agent} said meanwhile: " + " | ".join(lines)
        )

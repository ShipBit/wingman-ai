"""Minecraft Bot: the Wingman as a player in the user's Minecraft world.

The bot is a Mindcraft agent (github.com/mindcraft-bots/mindcraft). This skill
starts Mindcraft, puts the bot into the game and passes the user's words on to
it. The bot's "brain" is this Wingman's own model: Mindcraft is pointed at a
local OpenAI-compatible endpoint (llm_proxy.py) that answers through
self.wingman.ai, so the bot needs no API key of its own and runs on the
subscription, the user's key or a local model, whatever the Wingman uses.

The Wingman and the bot are one character. What the bot says is spoken
word for word in the Wingman's voice, not retold; the bot gets the Wingman's
backstory and answers in the user's language.

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
from typing import TYPE_CHECKING, Literal, Optional

from api.enums import SpeechPriority, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.minecraft_bot.llm_proxy import ContextTooLong, ProxyServer, RateLimiter, create_app
from skills.minecraft_bot.mindcraft import (
    AGENT_EXITED_MARKER,
    AGENT_RESTARTING_MARKER,
    MIN_NODE_MAJOR,
    MindcraftBridge,
    MindcraftError,
    build_agent_settings,
    canned_greeting,
    clean_bot_line,
    format_status,
    is_system_line,
    keys_file_api_key,
    mindcraft_problem,
    node_options_with_senses,
    node_version,
    sanitize_bot_name,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

SPAWN_TIMEOUT = 75.0
"""Seconds to wait for the bot to appear in the game after Mindcraft accepted it."""
REPLY_TIMEOUT = 20.0
"""Seconds tell_minecraft_bot waits for the bot's first line. The bot's thinking is one
call on the user's model. That first line is the answer and is spoken at once; every
later line is spoken as it comes. Waiting to join lines made the voice start seconds
after the game chat and then read a block of old news."""
SPAWN_GRACE = 1.0
"""Seconds after the bot spawned, so its first chat line is spoken and not taken for a reply."""
DEFAULT_REQUESTS_PER_MINUTE = 10
FRESH_LINE_SECONDS = 20.0
"""A line of the bot older than this when its turn comes is shown but not spoken:
the voice stays with the game instead of trailing it by a backlog."""
REPEAT_SILENCE = 60.0
"""The same line again within this time is shown but not spoken: a bot retrying
a step says the same thing each time."""
RESTART_GRACE = 30.0
"""Seconds the bot may be out of the game before that counts as gone: Mindcraft
restarts the agent after smelting and after !restart, and it is back in about ten."""


class _ReplyCollector:
    """Catches the bot's first line while a tell_minecraft_bot call waits for it."""

    def __init__(self) -> None:
        self.line = ""
        self._first = threading.Event()
        self._lock = threading.Lock()

    def add(self, line: str) -> bool:
        """Take the line as the reply. False once a reply is taken: that line is spoken on its own."""
        with self._lock:
            if self.line:
                return False
            self.line = line
        self._first.set()
        return True

    def wait(self, timeout: float) -> str:
        if not self._first.wait(timeout):
            return ""
        with self._lock:
            return self.line


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
        self._lines: "queue.Queue[tuple[str, float]]" = queue.Queue()
        self._pending: Optional[_ReplyCollector] = None
        self._pending_lock = threading.Lock()
        self._services_lock = threading.Lock()
        self._unreported: deque[str] = deque(maxlen=12)
        self._speaker_run = 0
        self._gone_since: Optional[float] = None
        self._restarting = False
        self._gone_announced = False
        self._last_spoken: Optional[tuple[str, float]] = None

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

    def _backstory(self) -> str:
        try:
            return str(self.wingman.config.prompts.backstory or "")
        except Exception:
            return ""

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
            status = f"You are in the Minecraft world right now, as the player {self._agent}."
        elif self._bridge and self._bridge.running:
            status = f"You are not in the Minecraft world at the moment (your player is {self._agent})."
        else:
            status = "You have not joined the Minecraft world yet; tell_minecraft_bot joins when needed."
        player = self._text("player_name")
        who = f" The user plays as {player}." if player else ""
        return f"{base}\n{status}{who}".strip()

    # ------------------------------------------------------------------- tools

    @tool(name="minecraft_bot", wait_response=True)
    async def minecraft_bot(self, action: Literal["spawn", "halt", "leave", "status"] = "status") -> str:
        """Joins the Minecraft game as your player, halts your player, takes it out of the game, or reports its state.

        Args:
            action: spawn joins the game. halt stops everything your player is doing at once and leaves it standing in the game, waiting; use it when the user says stop, wait, hold on, enough or do nothing. leave takes your player out of the game and shuts Mindcraft down. status says where your player is, its health, what it is doing and what it carries.
        """
        await self._forget_a_dead_mindcraft()
        if action == "spawn":
            return await self._spawn()
        if action == "halt":
            return await self._halt()
        if action == "leave":
            return await self._leave()
        return format_status(
            self._state,
            running=bool(self._bridge and self._bridge.running),
            in_game=self._in_game,
            bot_name=self._agent or self._bot_name(),
        )

    @tool(name="tell_minecraft_bot")
    async def tell_minecraft_bot(self, message: str):
        """Passes what the user said to your player in Minecraft, who acts on it and answers. The answer is spoken as your own words.

        Args:
            message: The user's words, as they said them and in their language, not rephrased, not translated, not in the third person, e.g. "Komm mal her", "Sammel zehn Eichenstämme", "Was hast du dabei?".
        """
        message = (message or "").strip()
        if not message:
            return "There was nothing to pass on."
        await self._forget_a_dead_mindcraft()
        if not self._in_game and not self._coming_back:
            spawned = await self._spawn()
            if not self._in_game:
                return spawned
        await self._wait_ready(RESTART_GRACE if self._coming_back else 15)
        if not self._in_game or not self._bridge:
            return f"{self._agent} is not in the game."

        collector = _ReplyCollector()
        with self._pending_lock:
            self._pending = collector
        try:
            self._bridge.send_message(self._agent, self._player_name(), message)
            reply = await asyncio.to_thread(collector.wait, REPLY_TIMEOUT)
        finally:
            with self._pending_lock:
                self._pending = None
        if reply:
            # Spoken word for word, in the Wingman's voice: the turn ends with it.
            return reply, reply
        return (
            "You have not said a word yet; what you say is spoken as soon as you say it. "
            "Answer now with a few words in the first person about what you are doing, in the "
            "user's language, like 'Moment, bin unterwegs.' You are the one acting: "
            "never 'he', never 'the bot'."
        )

    # ---------------------------------------------------------------- lifecycle

    async def _spawn(self) -> str:
        if self._in_game:
            return f"{self._agent} is already in the game."
        if self._coming_back:
            # Mindcraft is restarting the agent itself; a second create-agent
            # would put two bots of the same name into one world.
            if await self._wait_ready(RESTART_GRACE):
                return f"{self._agent} is back in the game."
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
            persona=self._backstory(),
            language=self.wingman.language.name,
            player_name=self._text("player_name"),
        )
        self._agent = bot
        self._in_game = False
        self._spawned = False
        self._agent_exited = False
        self._state = None
        self._gone_since = None
        self._restarting = False
        self._gone_announced = False
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

    @property
    def _coming_back(self) -> bool:
        """Out of the game, but only for a moment: Mindcraft is restarting the agent."""
        return (
            not self._in_game
            and self._restarting
            and self._gone_since is not None
            and time.monotonic() - self._gone_since < RESTART_GRACE
            and bool(self._bridge and self._bridge.running)
        )

    async def _wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while (
            not self._ready
            and (self._in_game or self._coming_back)
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.5)
        return self._ready

    def _drain_lines(self) -> list[tuple[str, float]]:
        """Take everything that waits to be spoken off the queue."""
        drained = []
        while True:
            try:
                drained.append(self._lines.get_nowait())
            except queue.Empty:
                return drained

    def _queue_line(self, text: str) -> None:
        self._lines.put((text, time.monotonic()))

    @staticmethod
    def _join_hints() -> str:
        return (
            "Check that a Minecraft Java world is open to LAN (or the server is running), "
            "that its version is one Mineflayer supports, and that host and port in the skill settings match."
        )

    async def _halt(self) -> str:
        """Stop the bot at once, in the game, without a model call: Mindcraft runs
        a command a player types right away. !stop interrupts the action, !stfu
        ends the bot's thinking about its last order and keeps it quiet until the
        next message. In that order: a message from the player first lets the bot
        talk again, so the silence has to come last."""
        self._drain_lines()
        if not self._in_game or not self._bridge:
            return "Your player is not in the game; there was nothing to stop."
        sender = self._player_name()
        self._bridge.send_message(self._agent, sender, "!stop")
        await asyncio.sleep(0.3)
        self._bridge.send_message(self._agent, sender, "!stfu")
        return f"{self._agent} stopped everything and stands still now, waiting for the next word."

    async def _leave(self) -> str:
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
                env["NODE_OPTIONS"] = node_options_with_senses(env.get("NODE_OPTIONS", ""))
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
            self._gone_since = None
            self._restarting = False
            self._gone_announced = False
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
            if self._gone_since is None:
                self._gone_since = time.monotonic()
        elif AGENT_RESTARTING_MARKER in line:
            self._restarting = True
        elif self._agent and line.strip() == f"{self._agent} spawned.":
            self._spawned = True

    def _on_bot_output(self, agent: str, message: str) -> None:
        if agent != self._agent:
            return
        text = clean_bot_line(message)
        if not text or text == canned_greeting(agent) or is_system_line(text):
            return
        with self._pending_lock:
            pending = self._pending
        if pending is not None and pending.add(text):
            return
        self._queue_line(text)

    def _on_agents_status(self, agents: list) -> None:
        for agent in agents:
            if not isinstance(agent, dict) or agent.get("name") != self._agent:
                continue
            was_in_game = self._in_game
            self._in_game = bool(agent.get("in_game"))
            if self._in_game:
                self._gone_since = None
                self._restarting = False
                self._gone_announced = False
            else:
                self._spawned = False
                self._state = None
                if was_in_game and self._gone_since is None:
                    self._gone_since = time.monotonic()

    def _on_state_update(self, states: dict) -> None:
        state = states.get(self._agent)
        if isinstance(state, dict):
            self._state = state

    # ------------------------------------------------------------- the speaker

    async def _speaker_loop(self, run_id: int) -> None:
        """Says what the bot says, on its own thread and loop. Stops when run_id is stale.

        A line is said in a task of its own, so the loop keeps reading the
        queue. The next line to say cuts off the one still in the air, being
        synthesized or playing: the voice follows the game live, like someone
        who corrects himself mid-sentence, and nothing waits to be old news."""
        speaking: Optional[asyncio.Task] = None
        while run_id == self._speaker_run and not self.is_unloaded:
            try:
                first = await asyncio.to_thread(self._lines.get, True, 0.5)
            except queue.Empty:
                first = None
            try:
                if first is None:
                    await self._check_gone()
                    continue
                text = await self._say([first] + self._drain_lines())
                if text is None:
                    continue
                await self._hush()
                if speaking is not None and not speaking.done():
                    speaking.cancel()
                speaking = asyncio.create_task(self._speak(text))
            except Exception as error:
                self.log.warning(f"Could not relay a bot line: {error}", server_only=True)
        if speaking is not None and not speaking.done():
            speaking.cancel()

    async def _say(self, batch: list[tuple[str, float]]) -> Optional[str]:
        """Show every line; the newest is the one to say, while it is fresh and not a repeat.

        Saying a line takes longer than the bot needs for its next one. When
        the voice falls behind, the lines in between are progress chatter that
        the newest supersedes; and nothing is said about a state that is over."""
        for text, _ in batch[:-1]:
            await self._show(text)
        text, stamp = batch[-1]
        await self._show(text)
        if not self._flag("speak_bot_messages", True):
            return None
        now = time.monotonic()
        last = self._last_spoken
        repeat = last is not None and last[0] == text and now - last[1] < REPEAT_SILENCE
        if now - stamp >= FRESH_LINE_SECONDS or repeat:
            return None
        self._last_spoken = (text, now)
        return text

    async def _hush(self) -> None:
        """Cut off what is in the air, so the next line is the latest word."""
        if self.wingman.audio.is_playing:
            await self.wingman.tts.stop()

    async def _speak(self, text: str) -> None:
        """One line in the Wingman's voice; waits for the user, never talks over them."""
        try:
            await self.wingman.tts.speak(text, priority=SpeechPriority.EVENT)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.log.warning(f"Could not speak a bot line: {error}", server_only=True)

    async def _check_gone(self) -> None:
        """A bot out of the game for longer than a restart takes is gone: noted in the chat, not spoken."""
        if (
            self._gone_since is None
            or self._in_game
            or self._gone_announced
            or time.monotonic() - self._gone_since < RESTART_GRACE
        ):
            return
        self._gone_announced = True
        await self._show("I left the game.")

    async def _show(self, line: str) -> None:
        """A line the player said in the game, shown in the chat as the Wingman's own."""
        self._unreported.append(line)
        await self.wingman.conversation.show(line, skill_name=self.name)

    async def on_add_user_message(self, message: str) -> None:
        # The user is talking: what the bot said meanwhile goes to the model as
        # context and is not spoken over the exchange that follows.
        for text, _ in self._drain_lines():
            self._unreported.append(text)
        if not self._unreported:
            return
        lines = list(self._unreported)
        self._unreported.clear()
        await self.wingman.conversation.add_note(
            f"What you said in Minecraft meanwhile, as the player {self._agent}: " + " | ".join(lines)
        )

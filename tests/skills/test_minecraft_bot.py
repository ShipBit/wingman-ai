"""Minecraft Bot skill: the model proxy, the brake and the Mindcraft plumbing.

No Node.js, no Minecraft and no network: the proxy is driven with FastAPI's
test client against a fake backend, Mindcraft is a stub that records what the
skill sends and feeds back what a bot would say.
"""

import asyncio
import json
import queue
import threading
import time
from collections import deque
from types import SimpleNamespace

from fastapi.testclient import TestClient

from skills.minecraft_bot import main as skill_module
from skills.minecraft_bot.llm_proxy import (
    ContextTooLong,
    RateLimiter,
    apply_stop,
    clean_messages,
    create_app,
)
from skills.minecraft_bot.main import MinecraftBot, _ReplyCollector
from skills.minecraft_bot.mindcraft import (
    build_agent_settings,
    clean_bot_line,
    conversing_prompt,
    format_status,
    is_system_line,
    keys_file_api_key,
    mindcraft_problem,
    node_options_with_senses,
    sanitize_bot_name,
)
from skills.minecraft_bot import mindcraft as mindcraft_module

TOKEN = "wingman-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeBackend:
    def __init__(self, answer="Sure, on my way!", vectors=None, fail=None):
        self.answer = answer
        self.vectors = vectors
        self.fail = fail
        self.seen = []

    async def chat(self, messages):
        self.seen.append(messages)
        if self.fail:
            raise self.fail
        return self.answer

    async def embed(self, texts):
        return self.vectors


def _client(backend, tokens=TOKEN, limit=100):
    return TestClient(create_app(backend, tokens, RateLimiter(lambda: limit)))


def _chat(client, headers=AUTH, **body):
    body.setdefault("model", "wingman")
    body.setdefault("messages", [{"role": "user", "content": "Timo: come here"}])
    return client.post("/v1/chat/completions", json=body, headers=headers)


# ----------------------------------------------------------------- the proxy


def test_chat_completions_answer_with_the_wingmans_model():
    backend = FakeBackend(answer="Coming!")
    response = _chat(
        _client(backend),
        messages=[
            {"role": "system", "content": "You are andy.", "name": "ignored"},
            {"role": "user", "content": "Timo: come here"},
        ],
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "Coming!"}
    assert choice["finish_reason"] == "stop"
    assert backend.seen == [[
        {"role": "system", "content": "You are andy."},
        {"role": "user", "content": "Timo: come here"},
    ]]


def test_the_stop_sequence_cuts_the_answer():
    client = _client(FakeBackend(answer="Sure! !goToPlayer('Timo', 3)*** and more"))

    response = _chat(client, stop="***")

    assert response.json()["choices"][0]["message"]["content"] == "Sure! !goToPlayer('Timo', 3)"
    assert apply_stop("abc***def", ["zzz", "***"]) == "abc"
    assert apply_stop("abc", None) == "abc"


def test_requests_need_one_of_the_accepted_tokens():
    client = _client(FakeBackend(), tokens={TOKEN, "sk-users-own-key"})

    assert _chat(client, headers={}).status_code == 401
    assert _chat(client, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert _chat(client).status_code == 200
    assert _chat(client, headers={"Authorization": "Bearer sk-users-own-key"}).status_code == 200
    assert client.get("/v1/models", headers=AUTH).json()["data"][0]["id"] == "wingman"


def test_a_request_too_long_for_the_model_reports_context_length_exceeded():
    client = _client(FakeBackend(fail=ContextTooLong("limit is 2000 tokens")))

    response = _chat(client)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"


def test_no_answer_is_a_server_error_not_an_empty_line():
    assert _chat(_client(FakeBackend(answer=""))).status_code == 502
    assert _chat(_client(FakeBackend()), messages=[]).status_code == 400


def test_embeddings_come_from_the_local_model_or_are_not_supported():
    with_vectors = _client(FakeBackend(vectors=[[0.1, 0.2]]))
    response = with_vectors.post("/v1/embeddings", json={"input": "oak log"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"][0]["embedding"] == [0.1, 0.2]

    without = _client(FakeBackend(vectors=None))
    assert without.post("/v1/embeddings", json={"input": "oak log"}, headers=AUTH).status_code == 501


def test_messages_keep_only_role_and_content():
    cleaned = clean_messages([
        {"role": "user", "content": "hi", "extra": 1},
        {"role": "tool", "content": "no"},
        "garbage",
        {"role": "assistant", "content": 42},
    ])
    assert cleaned == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "42"},
    ]


# ----------------------------------------------------------------- the brake


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_the_brake_holds_the_request_over_the_limit_until_a_slot_frees():
    clock = FakeClock()
    limiter = RateLimiter(lambda: 2, clock=clock, sleep=clock.sleep)

    async def run():
        waits = [await limiter.acquire(), await limiter.acquire()]
        clock.now = 10.0
        waits.append(await limiter.acquire())
        return waits

    waits = asyncio.run(run())

    assert waits[:2] == [0.0, 0.0]
    assert waits[2] == 50.0  # the first slot was taken at 0 and frees at 60
    assert clock.sleeps == [50.0]


def test_the_brake_reads_the_limit_on_every_request():
    clock = FakeClock()
    limit = {"value": 1}
    limiter = RateLimiter(lambda: limit["value"], clock=clock, sleep=clock.sleep)

    async def run():
        await limiter.acquire()
        limit["value"] = 3
        return await limiter.acquire()

    assert asyncio.run(run()) == 0.0
    assert clock.sleeps == []


# ------------------------------------------------------------ the agent setup


def test_the_agent_settings_point_the_bot_at_the_proxy():
    settings = build_agent_settings(
        bot_name="Andy",
        proxy_url="http://127.0.0.1:5123/v1",
        host="127.0.0.1",
        port=0,
        version="auto",
        auth="offline",
        base_profile="survival",
        allow_coding=False,
        persona="A grumpy old pirate who loves gold.",
        language="German",
        player_name="Yoda3001",
    )

    profile = settings["profile"]
    assert profile["name"] == "Andy"
    assert "A grumpy old pirate who loves gold." in profile["conversing"]
    assert "Speak German" in profile["conversing"]
    assert "The player you talk to is Yoda3001" in profile["conversing"]
    assert '!playerView("Yoda3001")' in profile["conversing"] and "!lookAround" in profile["conversing"]
    assert "!goThroughDoor" in profile["conversing"]
    assert "use !whereIs with its English name first" in profile["conversing"]
    assert "a command alone is not an answer" in profile["conversing"]  # else the Wingman has nothing to say
    assert "Never say coordinates to the player" in profile["conversing"]
    assert settings["max_commands"] == 10  # an order ends; a wall is not run into forever
    for placeholder in ("$NAME", "$MEMORY", "$STATS", "$INVENTORY", "$COMMAND_DOCS", "$EXAMPLES"):
        assert placeholder in profile["conversing"]
    assert profile["model"] == {"api": "openai", "url": "http://127.0.0.1:5123/v1", "model": "wingman"}
    assert profile["embedding"] == profile["model"]
    assert settings["port"] == -1  # 0 means: find the LAN world
    assert settings["allow_insecure_coding"] is False
    assert settings["speak"] is False
    assert settings["show_command_syntax"] == "none"
    assert settings["init_message"] is None  # Mindcraft's canned hello, no model call
    assert json.dumps(settings)  # what goes over the socket must be JSON


def test_the_bots_senses_are_preloaded_into_mindcrafts_processes():
    option = node_options_with_senses("")
    assert option.startswith("--import=file:") and option.endswith("/senses_hook.mjs")
    assert node_options_with_senses(" --max-old-space-size=4096 ") == f"--max-old-space-size=4096 {option}"

    hook = mindcraft_module.SENSES_HOOK.read_text(encoding="utf-8")
    senses = (mindcraft_module.SENSES_HOOK.parent / "senses.mjs").read_text(encoding="utf-8")
    assert "queryList.push(...wingmanSenses(wingmanSkills))" in hook  # appended to Mindcraft's queries.js as it loads
    assert "export function wingmanSenses" in senses
    for command in ("'!playerView'", "'!lookAround'", "'!turnTo'", "'!goThroughDoor'", "'!whereIs'"):
        assert command in senses


def test_the_bots_prompt_keeps_a_long_backstory_short_and_has_a_default():
    assert "a friendly, casual" in conversing_prompt("", "English")
    long_story = "word " * 1000
    prompt = conversing_prompt(long_story, "English")
    assert prompt.count("word") < 400
    assert " ..." in prompt


def test_bot_names_follow_minecrafts_rules():
    assert sanitize_bot_name("Yoda 3001") == "Yoda_3001"
    assert sanitize_bot_name("", fallback="Computer") == "Computer"
    assert sanitize_bot_name("A", fallback="Wing man") == "Wingman"
    assert sanitize_bot_name("ThisNameIsFarTooLongForMinecraft") == "ThisNameIsFarToo"
    assert sanitize_bot_name("Böse Ärger!") == "Bse_rger"


def test_bot_lines_lose_the_command_syntax():
    assert clean_bot_line("Sure, coming!  *used goToPlayer*") == "Sure, coming!"
    assert clean_bot_line("*used collectBlocks*") == ""
    assert clean_bot_line("On it! !collectBlocks('oak_log', 10)") == "On it!"
    assert clean_bot_line("Done! I collected 10 oak logs.") == "Done! I collected 10 oak logs."
    assert clean_bot_line("\t") == ""
    assert clean_bot_line("") == ""


def test_mindcrafts_own_chat_lines_are_not_the_bots_words():
    assert is_system_line("Agent stopped.")
    assert is_system_line("Agent stopped. Self-prompting still active.")
    assert is_system_line("Shutting up.")
    assert not is_system_line("I stopped, what now?")


def test_the_status_summarizes_mindcrafts_state():
    state = {
        "gameplay": {"position": {"x": 12.4, "y": 64.0, "z": -7.6}, "dimension": "overworld",
                     "health": 18, "hunger": 20, "biome": "plains", "timeLabel": "Morning", "weather": "Clear"},
        "action": {"current": "Collecting oak_log", "kind": "acting"},
        "nearby": {"humanPlayers": ["Timo"]},
        "inventory": {"counts": {"oak_log": 7, "dirt": 3}},
    }

    text = format_status(state, running=True, in_game=True, bot_name="Andy")

    assert text.startswith("Andy is in the game at x 12, y 64, z -8 in the overworld (plains, Morning, Clear).")
    assert "Health 18/20, hunger 20/20." in text
    assert "Doing: Collecting oak_log." in text
    assert "Players nearby: Timo." in text
    assert "Inventory: oak_log x7, dirt x3." in text
    assert format_status(None, running=False, in_game=False, bot_name="Andy") == "No Minecraft bot is running."
    assert "not in the game" in format_status(None, running=True, in_game=False, bot_name="Andy")
    idle = {"action": {"current": "Stopped", "kind": "stopped"}}
    assert "waiting for instructions" in format_status(idle, running=True, in_game=True, bot_name="Andy")
    hunting = {"action": {"current": "mode:self_defense", "kind": "acting"}}
    assert "Doing: self defense on its own." in format_status(hunting, running=True, in_game=True, bot_name="Andy")


def test_mindcraft_problem_says_what_is_missing(tmp_path):
    assert "Set the Mindcraft folder" in mindcraft_problem("")
    assert "does not exist" in mindcraft_problem(str(tmp_path / "nope"))
    assert "no Mindcraft checkout" in mindcraft_problem(str(tmp_path))
    entry = tmp_path / "src" / "mindcraft" / "mindcraft.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("export function init() {}", encoding="utf-8")
    assert "npm install" in mindcraft_problem(str(tmp_path))
    (tmp_path / "node_modules").mkdir()
    assert mindcraft_problem(str(tmp_path)) == ""


def test_the_key_from_mindcrafts_keys_json_is_found(tmp_path):
    assert keys_file_api_key(str(tmp_path)) == ""
    (tmp_path / "keys.json").write_text('{"OPENAI_API_KEY": "sk-own", "OTHER": 1}', encoding="utf-8")
    assert keys_file_api_key(str(tmp_path)) == "sk-own"
    (tmp_path / "keys.json").write_text("not json", encoding="utf-8")
    assert keys_file_api_key(str(tmp_path)) == ""


# ------------------------------------------------------------- the skill side


class FakeBridge:
    def __init__(self, skill, reply=None, delay=0.05):
        self.skill = skill
        self.reply = reply
        self.delay = delay
        self.sent = []
        self.running = True
        self.port = 8080

    def shutdown(self, timeout=0):
        self.running = False

    def send_message(self, agent, sender, message):
        self.sent.append((agent, sender, message))
        if self.reply:
            lines = self.reply if isinstance(self.reply, list) else [self.reply]

            def answer():
                for line in lines:
                    self.skill._on_bot_output(agent, line)

            threading.Timer(self.delay, answer).start()


def _quiet_log():
    return SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)


def _skill(**properties):
    skill = object.__new__(MinecraftBot)
    skill.name = "MinecraftBot"
    skill.config = SimpleNamespace(
        custom_properties=[SimpleNamespace(id=key, value=value, required=False) for key, value in properties.items()]
    )
    skill.wingman = SimpleNamespace(name="Computer")
    skill.log = _quiet_log()
    skill._bridge = None
    skill._proxy = None
    skill._token = ""
    skill._agent = "Andy"
    skill._in_game = False
    skill._spawned = False
    skill._agent_exited = False
    skill._state = None
    skill._lines = queue.Queue()
    skill._pending = None
    skill._pending_lock = threading.Lock()
    skill._services_lock = threading.Lock()
    skill._unreported = deque(maxlen=12)
    skill._speaker_run = 0
    skill._gone_since = None
    skill._restarting = False
    skill._gone_announced = False
    skill._last_spoken = None
    skill.is_unloaded = False
    return skill


def _voice(skill):
    """A wingman that records what the skill shows and speaks."""
    shown, spoken = [], []
    skill.wingman = SimpleNamespace(
        name="Computer",
        conversation=SimpleNamespace(show=lambda text, **kw: shown.append(text) or asyncio.sleep(0)),
        tts=SimpleNamespace(speak=lambda text, **kw: spoken.append(text) or asyncio.sleep(0)),
    )
    return shown, spoken


def test_a_reply_goes_to_the_waiting_tell_and_not_to_the_speaker():
    skill = _skill()
    collector = _ReplyCollector()
    skill._pending = collector

    skill._on_bot_output("Andy", "Sure, coming!  *used goToPlayer*")
    skill._on_bot_output("Someone", "not our bot")
    skill._pending = None
    skill._on_bot_output("Andy", "Done, I am here.")
    skill._on_bot_output("Andy", "*used stop*")
    skill._on_bot_output("Andy", "*Timo used stop*")
    skill._on_bot_output("Andy", "Agent stopped.")  # Mindcraft's answer to a forced !stop
    skill._on_bot_output("Andy", "Hello world! I am Andy")  # Mindcraft's canned hello at spawn

    assert collector.line == "Sure, coming!"
    assert skill._lines.get_nowait()[0] == "Done, I am here."
    assert skill._lines.empty()


def test_the_agents_status_tells_whether_the_bot_is_in_the_game():
    skill = _skill()

    skill._on_agents_status([{"name": "Other", "in_game": True}, {"name": "Andy", "in_game": True}])
    assert skill._in_game is True
    assert skill._ready is False  # logged in, but not standing in the world yet

    skill._on_mindcraft_log("Andy spawned.")
    assert skill._ready is True

    skill._on_agents_status([{"name": "Andy", "in_game": False}])
    assert skill._in_game is False
    assert skill._ready is False
    assert skill._lines.empty()  # not announced: Mindcraft may be restarting the agent
    assert skill._gone_since is not None


def test_a_restart_by_mindcraft_is_a_moment_out_of_the_game_not_a_leave():
    skill = _skill()
    skill._bridge = FakeBridge(skill)
    skill._in_game = True
    skill._spawned = True

    skill._on_mindcraft_log("Agent process exited with code 1 and signal null")
    skill._on_agents_status([{"name": "Andy", "in_game": False}])
    skill._on_mindcraft_log("Restarting agent...")
    assert skill._coming_back is True

    skill._on_agents_status([{"name": "Andy", "in_game": True}])
    skill._on_mindcraft_log("Andy spawned.")
    assert skill._coming_back is False and skill._ready is True
    assert skill._gone_since is None

    skill._on_agents_status([{"name": "Andy", "in_game": False}])
    skill._on_mindcraft_log("Restarting agent...")
    skill._gone_since -= 2 * skill_module.RESTART_GRACE
    assert skill._coming_back is False  # gone too long: the next order spawns anew


def test_a_bot_gone_for_good_is_noted_in_the_chat_once_and_not_spoken():
    skill = _skill()
    shown, spoken = _voice(skill)

    skill._gone_since = time.monotonic() - 5
    asyncio.run(MinecraftBot._check_gone(skill))
    assert shown == []

    skill._gone_since = time.monotonic() - 2 * skill_module.RESTART_GRACE
    asyncio.run(MinecraftBot._check_gone(skill))
    asyncio.run(MinecraftBot._check_gone(skill))
    assert shown == ["I left the game."] and spoken == []


def test_halt_stops_the_bot_at_once_and_drops_the_backlog():
    skill = _skill(player_name="Timo")
    skill._in_game = True
    skill._spawned = True
    skill._bridge = FakeBridge(skill)
    skill._queue_line("Trying again.")
    skill._queue_line("Still not working.")

    result = asyncio.run(MinecraftBot.minecraft_bot(skill, "halt"))

    # !stop first, !stfu last: a player's message lets the bot talk again, so the silence must come last
    assert skill._bridge.sent == [("Andy", "Timo", "!stop"), ("Andy", "Timo", "!stfu")]
    assert skill._lines.empty()
    assert "stands still" in result
    assert skill._in_game is True  # halt is not leave


def test_the_speaker_shows_every_line_but_says_only_a_fresh_newest_one():
    skill = _skill()
    shown, spoken = _voice(skill)
    now = time.monotonic()

    said = [
        asyncio.run(MinecraftBot._say(skill, [("Trying again.", now - 40), ("Still nothing.", now - 30), ("Got it!", now - 1)])),
        asyncio.run(MinecraftBot._say(skill, [("Long ago.", now - 2 * skill_module.FRESH_LINE_SECONDS)])),
        asyncio.run(MinecraftBot._say(skill, [("Got it!", now)])),  # the same line again, a step retried
        asyncio.run(MinecraftBot._say(skill, [("Done.", now)])),
    ]

    assert shown == ["Trying again.", "Still nothing.", "Got it!", "Long ago.", "Got it!", "Done."]
    assert said == ["Got it!", None, None, "Done."]
    assert spoken == []  # saying is the loop's job, see the cut-off test
    assert list(skill._unreported) == shown


def test_a_new_line_cuts_off_the_one_still_in_the_air():
    skill = _skill()
    events = []
    playing = {"on": False}

    async def speak(text, **kw):
        events.append(f"speak {text}")
        playing["on"] = True
        await asyncio.sleep(0.6)
        playing["on"] = False
        events.append(f"done {text}")
        return True

    async def stop():
        playing["on"] = False
        events.append("stop")

    class Audio:
        @property
        def is_playing(self):
            return playing["on"]

    skill.wingman = SimpleNamespace(
        name="Computer",
        conversation=SimpleNamespace(show=lambda text, **kw: asyncio.sleep(0)),
        tts=SimpleNamespace(speak=speak, stop=stop),
        audio=Audio(),
    )

    async def play_along():
        skill._speaker_run = 1
        loop = asyncio.create_task(MinecraftBot._speaker_loop(skill, 1))
        skill._queue_line("Collecting.")
        await asyncio.sleep(0.3)  # the first line is in the air
        skill._queue_line("Done, got it!")
        await asyncio.sleep(1.0)
        skill._speaker_run = 2  # ends the loop
        await asyncio.wait_for(loop, 3)

    asyncio.run(play_along())

    assert events == ["speak Collecting.", "stop", "speak Done, got it!", "done Done, got it!"]


def test_tell_passes_the_message_on_as_the_player_and_returns_the_reply(monkeypatch):
    monkeypatch.setattr(skill_module, "REPLY_TIMEOUT", 2.0)
    skill = _skill(player_name="Timo")
    skill._in_game = True
    skill._spawned = True
    skill._bridge = FakeBridge(skill, reply=["On my way!", "*used goToPlayer*"])

    result = asyncio.run(MinecraftBot.tell_minecraft_bot(skill, "come to me"))

    assert skill._bridge.sent == [("Andy", "Timo", "come to me")]
    assert result == ("On my way!", "On my way!")  # spoken word for word, no retelling
    assert skill._pending is None
    assert skill._lines.empty()


def test_tell_without_a_reply_says_the_answer_comes_later(monkeypatch):
    monkeypatch.setattr(skill_module, "REPLY_TIMEOUT", 0.2)
    skill = _skill()
    skill._in_game = True
    skill._state = {"nearby": {"humanPlayers": ["Timo"]}}  # spawned: a state has arrived
    skill._bridge = FakeBridge(skill, reply=None)

    result = asyncio.run(MinecraftBot.tell_minecraft_bot(skill, "build a house"))

    assert result.startswith("You have not said a word yet")
    assert "first person" in result and "never 'he'" in result
    assert skill._bridge.sent == [("Andy", "Timo", "build a house")]  # the one player nearby


def test_the_first_line_is_the_reply_and_later_lines_are_spoken_as_they_come():
    collector = _ReplyCollector()
    threading.Timer(0.05, lambda: collector.add("Let me look.")).start()

    assert collector.wait(1.0) == "Let me look."
    assert collector.add("I carry 3 oak logs.") is False  # not joined and not held back: spoken when it comes
    assert _ReplyCollector().wait(0.05) == ""


def test_lines_after_the_reply_go_to_the_speaker():
    skill = _skill()
    collector = _ReplyCollector()
    skill._pending = collector
    for line in ("One.", "Two.", "Three."):
        skill._on_bot_output("Andy", line)

    assert collector.line == "One."
    assert skill._lines.get_nowait()[0] == "Two."
    assert skill._lines.get_nowait()[0] == "Three."


def test_a_mindcraft_that_died_is_forgotten_and_the_settings_are_checked_first(tmp_path):
    skill = _skill(mindcraft_dir=str(tmp_path / "gone"))
    skill._in_game = True
    skill._spawned = True
    skill._bridge = FakeBridge(skill)
    skill._bridge.running = False

    result = asyncio.run(MinecraftBot.tell_minecraft_bot(skill, "come here"))

    assert skill._bridge is None and skill._in_game is False
    assert result.startswith("Could not start Mindcraft: The Mindcraft folder does not exist")
    assert skill._proxy is None  # nothing was started for a configuration that cannot work


def test_lines_the_bot_said_meanwhile_reach_the_conversation_as_a_note():
    skill = _skill()
    notes = []
    skill.wingman = SimpleNamespace(
        name="Computer",
        conversation=SimpleNamespace(add_note=lambda text: notes.append(text) or asyncio.sleep(0)),
    )
    skill._unreported.extend(["Collected 10 oak logs.", "I am at the house."])
    skill._queue_line("Hm, that did not work.")  # waiting to be spoken: told instead, not spoken over the user

    asyncio.run(MinecraftBot.on_add_user_message(skill, "what now?"))
    asyncio.run(MinecraftBot.on_add_user_message(skill, "and now?"))

    assert notes == [
        "What you said in Minecraft meanwhile, as the player Andy: "
        "Collected 10 oak logs. | I am at the house. | Hm, that did not work."
    ]
    assert skill._lines.empty()

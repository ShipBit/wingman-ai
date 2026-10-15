"""A short spoken line while a turn with tools runs.

When the main model calls a tool and says nothing alongside it, the user hears
silence until the tool and a second model call are done — ten seconds for a
UEXCorp price lookup, six for an MCP tool that first has to be activated. The support model writes one line in the Wingman's voice
("Moment, ich schau nach...") and the Wingman speaks it while the tool runs.

It replaces the old generic instant responses: those were twenty phrases the
main model wrote once per start, in English whatever the user spoke, from the
whole system prompt. This line is written per turn from the request itself, so
it is in the user's language and can say what the Wingman is doing.

Rules for when it plays:

- At most once per turn, and only if nothing was said yet in that turn.
- It starts with the first round of tool calls and covers the rest of the
  turn: activating a capability, the tool, the model writing the answer. Most
  of the wait is model calls, not the tool — an MCP tool that ran 1.6 s sat in
  a 6.4 s turn.
- A tool whose skill asks for a waiting response starts the line at once.
  Everything else — MCP tools, commands, other skills — waits
  ``FILLER_DELAY_S`` first, so a turn that is done in a moment costs no call.
- If the answer is ready before the line, the line is dropped.
- The line is never added to the conversation; the main model does not see it.

It runs on its own thread, not as a task on the turn's event loop: the main
model's providers call ``requests`` inside their ``async def ask``, so that
loop is blocked for every model call — five seconds each — and a task on it
only got to run once the answer was already there.
"""

import re
import threading
import time
import traceback
from typing import TYPE_CHECKING, Callable, Optional

from api.enums import SpokenLanguage
from services.file import get_prompt
from services.printr import Printr
from services.skill_local_ai import SamplingPreset
from services.spoken_language import language_name
from services.token_utils import truncate_to_tokens

if TYPE_CHECKING:
    from api.interface import SettingsConfig
    from services.local_ai_service import LocalAiService

printr = Printr()

FILLER_DELAY_S = 1.0
"""How long a turn without a waiting-response tool runs before the line is started.

The line takes 1.5 s from the cloud support model and 0.6 s from local
Qwen3.5-4B (medians, evals/bench_filler.py), plus speech. A turn that is done
within a second would drop it anyway — the call would be paid for and never
heard."""

MAX_WORDS = 7
"""Longer than this and the line is still being spoken when the answer is
ready — it is never cut off, so every extra word delays the answer."""

MAX_OUTPUT_TOKENS = 24

LEARN_RATE = 0.3
"""Weight of the newest turn in the running averages below."""

MIN_SAMPLES = 2
"""Turns seen before an average is trusted to skip the line."""

SPEAK_MARGIN_S = 1.0
"""How much earlier than the answer the line must be ready to be worth it.
A line still playing when the answer is ready holds the answer back."""
BACKSTORY_TOKENS = 300
REQUEST_TOKENS = 200


def language_rule(spoken_language: SpokenLanguage, other=None) -> str:
    """The prompt line that picks the language, same as the system prompt."""
    return f"Write in {language_name(spoken_language, other)}."


def build_user_message(request: str, spoken_language: SpokenLanguage, other=None) -> str:
    """The request, followed by a cue that repeats the language right before
    the answer — where a small model still pays attention to it.

    Measured 2026-09-23 with evals/bench_filler.py, requests in five languages:
    with the rule in the system prompt alone, local Qwen3.5-4B wrote 4 of 24
    lines in English; with this cue 0 of 32. The cloud model got 24 of 24 right
    either way."""
    return (
        f'User request: "{truncate_to_tokens(request, REQUEST_TOKENS)}"\n\n'
        f"Your line, in {language_name(spoken_language, other)}:"
    )


def tool_label(tool_names: list[str]) -> str:
    """``uex_get_commodity_information`` -> ``uex get commodity information``."""
    return ", ".join(name.replace("_", " ").replace("-", " ") for name in tool_names)


def build_system_prompt(
    name: str,
    backstory: str,
    tool_names: list[str],
    spoken_language: SpokenLanguage,
    other=None,
) -> str:
    return get_prompt("filler-response").format(
        name=name,
        backstory=truncate_to_tokens(backstory or "", BACKSTORY_TOKENS).strip()
        or "A helpful assistant.",
        tool_label=tool_label(tool_names),
        language_rule=language_rule(spoken_language, other),
    )


def clean_filler(text: Optional[str], request: str) -> Optional[str]:
    """The line to speak, or None when the model's answer should not be spoken.

    Drops anything that is not a short acknowledgement: a question, a second
    line, a number the user did not say (the model making up a result).
    """
    if not text:
        return None
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    # "Updating panels; Yadar spec only." A second clause is a second line.
    line = re.split(r"[;:]", lines[0])[0]
    line = line.strip().strip("\"'“”„«»").strip()
    if not line or "<think" in line or "?" in line or "¿" in line:
        return None
    if len(line.split()) > MAX_WORDS:
        return None
    if set(re.findall(r"\d+", line)) - set(re.findall(r"\d+", request)):
        return None
    return line


class FillerLine:
    """One turn's filler line, shared between its thread and the turn.

    A skipped line has no thread; it only times the turn, so the responder
    keeps learning how long the rest of a turn with these tools takes."""

    def __init__(self, tools: tuple[str, ...] = (), skipped: bool = False):
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.spoken = False
        self.finished = skipped
        self.tools = tools
        self.skipped = skipped
        self.started_at = time.perf_counter()


class _Average:
    def __init__(self):
        self.value = 0.0
        self.samples = 0

    def add(self, seconds: float) -> None:
        self.value = seconds if not self.samples else (
            LEARN_RATE * seconds + (1 - LEARN_RATE) * self.value
        )
        self.samples += 1

    @property
    def known(self) -> bool:
        return self.samples >= MIN_SAMPLES


class FillerResponder:
    """Starts and stops the filler line for one Wingman."""

    def __init__(
        self,
        settings: "SettingsConfig",
        get_local_ai: Callable[[], Optional["LocalAiService"]],
        speak: Callable[[str], None],
    ):
        """
        Args:
            settings: The live settings object; the switch is read on every turn.
            get_local_ai: Returns the Wingman's ``LocalAiService``, which is
                attached after construction.
            speak: Plays the line and prints it to the client. Called from the
                filler's own thread, so it must not need the turn's loop.
        """
        self._settings = settings
        self._get_local_ai = get_local_ai
        self._speak = speak
        # How long the rest of a turn takes after the model called this tool,
        # and how long the support model takes for the line. In one evening's
        # log the line took 2.3 s and was ready after the answer in 13 of 22
        # turns: a keypress or a HUD panel is followed by one short model call.
        self._rest: dict[str, _Average] = {}
        self._latency = _Average()
        self._lock = threading.Lock()

    def _too_late(self, tool_names: list[str]) -> Optional[float]:
        """The expected rest of the turn when the line would come after the
        answer, else None. None as well while a tool is not known yet."""
        with self._lock:
            rests = [self._rest.get(name) for name in tool_names]
            if not self._latency.known or not all(r and r.known for r in rests):
                return None
            expected = max(r.value for r in rests)
            ready = FILLER_DELAY_S + self._latency.value + SPEAK_MARGIN_S
        return expected if expected < ready else None

    def start(
        self,
        *,
        request: str,
        tool_names: list[str],
        immediate: bool,
        name: str,
        backstory: str,
    ) -> Optional[FillerLine]:
        """Start the line on its own thread, or return None when it is off."""
        if not getattr(self._settings, "filler_responses", False):
            return None
        if not request or not tool_names:
            return None
        local_ai = self._get_local_ai()
        if not local_ai or not local_ai.is_ready():
            printr.print("Filler: skipped, the support model is not ready.", server_only=True)
            return None
        if not immediate:
            expected = self._too_late(tool_names)
            if expected is not None:
                printr.print(
                    f"Filler: skipped for {tool_label(tool_names)!r}, the answer"
                    f" usually comes {expected:.1f} s after it.",
                    server_only=True,
                )
                return FillerLine(tuple(tool_names), skipped=True)
        spoken_language = self._settings.spoken_language
        other = self._settings.other_language
        system_prompt = build_system_prompt(name, backstory, tool_names, spoken_language, other)
        user_message = build_user_message(request, spoken_language, other)
        printr.print(
            f"Filler: started for {tool_label(tool_names)!r}"
            f" ({'now' if immediate else f'after {FILLER_DELAY_S:g} s'}).",
            server_only=True,
        )
        line = FillerLine(tuple(tool_names))
        threading.Thread(
            target=self._run,
            args=(line, local_ai, system_prompt, user_message, request, immediate),
            name="filler",
            daemon=True,
        ).start()
        return line

    def _run(
        self,
        line: FillerLine,
        local_ai: "LocalAiService",
        system_prompt: str,
        user_message: str,
        request: str,
        immediate: bool,
    ) -> None:
        started = time.perf_counter()
        try:
            if not immediate and line.stopped.wait(FILLER_DELAY_S):
                return  # the answer came first; no call made
            try:
                call_started = time.perf_counter()
                result = local_ai.support(
                    user_message,
                    system_prompt,
                    preset=SamplingPreset.BALANCED,
                    reasoning=False,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )
                with self._lock:
                    self._latency.add(time.perf_counter() - call_started)
            except Exception:
                printr.print(
                    f"Filler: support call failed:\n{traceback.format_exc()}",
                    server_only=True,
                )
                return

            text = clean_filler(result.text if result else None, request)
            if not text:
                printr.print(
                    f"Filler: dropped the answer {result.text if result else None!r}.",
                    server_only=True,
                )
                return
            with line.lock:
                if line.stopped.is_set():
                    printr.print(
                        f"Filler: ready after {time.perf_counter() - started:.1f} s,"
                        " too late for this turn.",
                        server_only=True,
                    )
                    return
                printr.print(
                    f"Filler: speaking after {time.perf_counter() - started:.1f} s: {text!r}",
                    server_only=True,
                )
                try:
                    self._speak(text)
                except Exception:
                    printr.print(
                        f"Filler: could not speak:\n{traceback.format_exc()}",
                        server_only=True,
                    )
                    return
                line.spoken = True
        finally:
            line.finished = True

    def stop(self, line: Optional[FillerLine]) -> bool:
        """The answer is ready: drop the line if it is not out yet. True if it was spoken.

        Waits for a line that is being handed out right now, so it reaches the
        client before the answer does.
        """
        if line is None:
            return False
        rest = time.perf_counter() - line.started_at
        with self._lock:
            for name in line.tools:
                self._rest.setdefault(name, _Average()).add(rest)
        if line.skipped:
            return False
        with line.lock:
            if not line.spoken and not line.finished:
                printr.print("Filler: the answer was ready first, line dropped.", server_only=True)
            line.stopped.set()
            return line.spoken

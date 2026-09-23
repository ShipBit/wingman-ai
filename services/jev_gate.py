"""Where Core asks the System One model, and what it does without an answer.

One object per caller, built whether or not the feature is switched on, so
the call sites stay a single ``if`` and never grow a second code path.
Switched off — ``settings.system_one.enabled`` false, or nothing to
authenticate with — every method returns the value that means "decide the way
you did before", and nothing reaches the network.

The switch is read on every call rather than captured at construction. A user
turning it off in Settings expects the next utterance to stop asking, not the
next restart.

Thresholds can still be moved from the environment. They are not user-facing
settings: the right value is what the measurement says, and a user turning a
dial they cannot measure makes their own experience worse.
"""

import asyncio
import os
from typing import Optional

from api.enums import LogType
from api.interface import CommandConfig, SettingsConfig
from providers.typesafe_jev import JevClient, JevResult
from services.jev_decisions import (
    command_questions,
    read_command,
    read_triage,
    read_vocabulary,
    triage_questions,
    vocabulary_questions,
)
from services.printr import Printr

printr = Printr()


def _threshold(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name, fallback))
    except ValueError:
        return fallback


COMMAND_CONFIDENCE = _threshold("WINGMAN_JEV_COMMAND_CONFIDENCE", 0.8)
"""How sure Jev has to be before a key is pressed without asking the main model.

Measured on the shipped Star Citizen config, 40 command turns and 22 that are
not commands (evals/jev_bench, 2026-09-20):

    0.0   fires 40/40, 37 right, 0 fired on a non-command
    0.8   fires 36/40, 34 right, 0 fired on a non-command
    0.9   fires 29/40, 28 right, 0 fired on a non-command

0.8 keeps nine of ten wins that 0.9 throws away. Raising it further is not
the way to stop the remaining errors: the worst of them, "put the gear down"
answered with the full Landing Sequence macro, came back at 0.92 confidence.
Calibration separates unsure from sure, not two commands that genuinely
overlap — a description on each of them does that, and moved exactly those
cases to 0.99. See the findings file."""

MAX_COMMAND_OPTIONS = 254
"""How many commands fit in one question. TypeSafe's limit is 255 options and
one of them is the "no command" escape hatch."""

VOCABULARY_THRESHOLD = _threshold("WINGMAN_JEV_VOCABULARY_THRESHOLD", 0.5)
"""Where "the speaker meant the Star Citizen name" starts.

The middle, and the measurement put a clean gap around it: on 20 cases every
replacement that should happen scored 0.63 or above and every one that
should not scored 0.36 or below. Both errors cost the same here — a wrong
replacement and a missed one each hand the model a word the user did not
say — so there is no reason to lean either way."""


class JevGate:
    """The wingman's line to the System One model.

    Every method here is allowed to fail. What it returns on failure is what
    the caller did before Jev existed, so a gateway outage shows up as the
    old latency and nothing else.
    """

    def __init__(self, wingman_name: str = "", settings: Optional[SettingsConfig] = None):
        self.wingman_name = wingman_name
        self.settings = settings
        self.client = JevClient(subscription=settings.wingman_pro if settings else None)
        self.last: Optional[JevResult] = None
        """The most recent answer, for the log."""
        self.turn_decisions: list[tuple[str, float]] = []
        """What this turn asked and how long each took, for the benchmark the
        client shows. Skills share the wingman's gate, so their decisions land
        here too and the user sees the whole cost of the layer, not only
        Core's part of it."""
        self._warned_without_access = False
        """A plan without System One access must not say so on every utterance."""
        self._warned_about_command_count = False
        """Nor must a config too big to ask about."""

    def update_settings(self, settings: SettingsConfig) -> None:
        """Settings changed in the client. The subscription goes with them: a
        user who signs in gets a token the client has to start using."""
        self.settings = settings
        self.client.subscription = settings.wingman_pro if settings else None

    @property
    def enabled(self) -> bool:
        """What the user asked for, read fresh on every call."""
        return bool(self.settings and self.settings.system_one.enabled)

    @property
    def active(self) -> bool:
        """Whether a call would actually reach a model."""
        if not self.enabled:
            return False
        if self.client.is_ready():
            return True
        if not self._warned_without_access:
            self._warned_without_access = True
            printr.print(
                "System One is on, but there is no Wingman Pro session and no "
                "AI_GATEWAY_API_KEY - decisions stay with the main model.",
                color=LogType.WARNING,
                server_only=True,
            )
        return False

    def take_decisions(self) -> list[tuple[str, float]]:
        """Everything decided since the last call, and reset.

        Read once per turn when the benchmark is assembled. Draining rather
        than clearing separately means a turn that ends early cannot leave
        its timings to be counted against the next one.
        """
        decisions, self.turn_decisions = self.turn_decisions, []
        return decisions

    def _record(self, label: str, result: JevResult) -> JevResult:
        self.last = result
        self.turn_decisions.append((label, result.seconds * 1000))
        return result

    async def _ask(self, state, questions, label: str = "System One") -> JevResult:
        """Off the event loop. An HTTP call of several seconds on the loop
        would hold up playback and the next utterance behind it."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: self.client.system_one(state, questions)
        )
        return self._record(label, result)

    # ── everything the turn wants to know, in one call ──────────────

    async def pick_command(
        self, transcript: str, commands: list[CommandConfig]
    ) -> Optional[str]:
        """The command this request means, or None to let the main model decide.

        Asked before the main model, not alongside it: the model call that
        follows has to know the command already fired, so it cannot be
        started first and corrected afterwards.

        Skill preselection used to ride along in this call and was taken out
        (2026-09-21). It saved about a second on the quarter of turns that
        needed a skill not yet active, which is 0.26 s expected, against
        0.46 s spent on every turn — a net loss of 0.2 s, measured the same
        way on two very different configs. What made most of its value free
        instead was dropping already-active capabilities from the
        `activate_capability` offer.

        None means nothing was decided: off, no access, no commands, a config
        too big to ask about, or an answer below the gate.
        """
        if not (self.active and self.settings and self.settings.system_one.commands):
            return None

        askable = self._askable_commands(commands)
        if not askable:
            return None

        result = await self._ask(
            {"transcript": transcript}, command_questions(askable), "Command choice"
        )
        if not result.ok:
            return None

        picked = read_command(result, COMMAND_CONFIDENCE)
        if not picked:
            printr.print(
                f"Jev: no command at {COMMAND_CONFIDENCE} or above, the main "
                "model decides.",
                color=LogType.SYSTEM,
                server_only=True,
            )
        return picked

    def _askable_commands(self, commands: list[CommandConfig]) -> list[CommandConfig]:
        """The commands that fit in one question, or none at all.

        Nothing is limited or truncated by this. A Wingman may have as many
        commands as its owner likes and the main model is offered every one
        of them, exactly as before. The only thing that stops past the
        ceiling is *asking the System One model*, and that Wingman then
        works the way it did in 3.2.3.

        A choice takes 255 options and one of them is the "no command"
        escape hatch, so 254 is the ceiling. Over it the model answers 400
        and the turn falls back — which works, but costs a rejected request
        and a warning on *every* turn, forever, for exactly the users with
        the biggest configs. Measured 2026-09-20: 254 options go through at
        592 ms and 3,001 input tokens; 400 are refused outright.

        Asking about a subset was the other option and is worse than not
        asking. The fuzzy pre-filters that work elsewhere match letters, and
        the whole reason this question exists is that "Schilde hoch" shares
        no letters with "Toggle Shields" — a pre-filter would throw away the
        right answer and leave a confident wrong one. A prior worth having
        would be which commands this user actually triggers, which nothing
        records today. Not worth building for a ceiling nobody is near: the
        heaviest real config on this machine has 86.
        """
        if len(commands) <= MAX_COMMAND_OPTIONS:
            return commands
        if not self._warned_about_command_count:
            self._warned_about_command_count = True
            printr.print(
                f"{len(commands)} commands is past the {MAX_COMMAND_OPTIONS} a "
                "System One choice takes, so this Wingman's commands stay "
                "with the main model. Nothing else changes.",
                color=LogType.WARNING,
                server_only=True,
            )
        return []

    # ── what an utterance actually was ──────────────────────────────

    def triage(
        self,
        transcript: str,
        wingman_names: list[str],
        during_playback: bool,
        speaking_text: str = "",
    ) -> dict:
        """Synchronous: the transcription thread calls this and has nothing
        else to do meanwhile. Returns probabilities, not a verdict — the
        thresholds belong at the call site, where the consequences are.

        An empty dict means "decide as before".
        """
        if not self.active:
            return {}
        result = self.client.system_one(
            {
                "transcript": transcript,
                "assistant_is_speaking": during_playback,
                "assistant_current_sentence": speaking_text if during_playback else "",
            },
            triage_questions(wingman_names, during_playback),
        )
        self._record("Utterance triage", result)
        if result.error:
            return {}
        return read_triage(result)

    # ── which proposed name corrections are real ────────────────────

    def confirm_vocabulary(
        self, text: str, proposals: list[tuple[str, str, bool]]
    ) -> Optional[set[int]]:
        """Which of the matcher's proposals to apply, or None to change nothing.

        Synchronous: the transcription thread calls this between the speech
        model and the wingman, and has nothing else to do meanwhile.

        Runs only when there is something to ask about, which on ordinary
        speech is usually never. "Shields up." produces no candidate and
        costs nothing.
        """
        if not self.active or not proposals:
            return None
        candidates = [(heard, entry) for heard, entry, _blocked in proposals]
        result = self.client.system_one(
            {"transcript": text}, vocabulary_questions(candidates)
        )
        self._record("Vocabulary check", result)
        if result.error:
            return None
        confirmed = read_vocabulary(result, candidates, VOCABULARY_THRESHOLD)
        applied = [candidates[i] for i in sorted(confirmed or set())]
        if applied:
            printr.print(
                "Jev vocabulary, replacing: "
                + ", ".join(f"{heard} -> {entry}" for heard, entry in applied),
                color=LogType.SYSTEM,
                server_only=True,
            )
        return confirmed

    # ── the open door for skills ────────────────────────────────────

    async def ask(self, state, questions: dict) -> Optional[JevResult]:
        """Any questions a skill wants answered. None when the feature is off.

        Deliberately unconstrained: the four decisions above are Core's, and a
        skill's will be something we did not think of. What it does not get is
        a way around the switch — off is off, here as everywhere.
        """
        if not self.active:
            return None
        return await self._ask(state, questions, f"Skill: {len(questions)} question(s)")

    def ask_sync(self, state, questions: dict) -> Optional[JevResult]:
        """Blocking version, for a skill already off the event loop."""
        if not self.active:
            return None
        return self._record(
            f"Skill: {len(questions)} question(s)",
            self.client.system_one(state, questions),
        )

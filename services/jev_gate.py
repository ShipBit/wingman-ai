"""Where Core asks Jev, and what it does with an answer it does not trust.

One object per wingman, built whether or not Jev is switched on, so the call
sites stay a single ``if`` and never grow a second code path. Switched off —
no key, or ``WINGMAN_JEV`` unset — every method returns the value that means
"decide the way you did before", and nothing reaches the network.

Deliberately not a config setting yet. A field in ``interface.py`` costs a
template default, a migration and a regenerated TypeScript client, and this
is a prototype that has to earn those first. An environment variable is the
honest shape for something we are still measuring:

    WINGMAN_JEV=1 AI_GATEWAY_API_KEY=... python main.py

Thresholds can be moved from the environment too, because the right value is
what the measurement says, not what looked sensible while writing this.
"""

import asyncio
import os
from typing import Optional

from api.enums import LogType
from api.interface import CommandConfig
from providers.typesafe_jev import JevClient, JevResult
from services.jev_decisions import (
    command_questions,
    read_command,
    read_tool_groups,
    read_triage,
    tool_group_questions,
    triage_questions,
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

CAPABILITY_THRESHOLD = _threshold("WINGMAN_JEV_CAPABILITY_THRESHOLD", 0.5)
"""Where "this turn could need that skill" starts.

Higher than the threshold that would suit plain filtering. Filtering starts
from everything and takes away, so erring towards keeping is free apart from
tokens. Preselection starts from nothing and adds, and adding every skill on
a vague sentence undoes progressive disclosure — which exists to keep the
prompt small. A skill this misses is not lost: the model still sees its one
line and can activate it the way it does today."""


class JevGate:
    """The wingman's line to the System One model.

    Every method here is allowed to fail. What it returns on failure is what
    the caller did before Jev existed, so a gateway outage shows up as the
    old latency and nothing else.
    """

    def __init__(self, wingman_name: str = ""):
        self.wingman_name = wingman_name
        self.enabled = os.environ.get("WINGMAN_JEV", "") not in ("", "0", "false")
        self.client = JevClient() if self.enabled else None
        if self.enabled and not (self.client and self.client.is_ready()):
            printr.print(
                "WINGMAN_JEV is set but there is no AI_GATEWAY_API_KEY - staying off.",
                color=LogType.WARNING,
                server_only=True,
            )
            self.enabled = False
        self.last: Optional[JevResult] = None
        """The most recent answer, for the benchmark snapshot and the log."""

    @property
    def active(self) -> bool:
        return self.enabled and self.client is not None

    async def _ask(self, state, questions) -> JevResult:
        """Off the event loop. An HTTP call of up to two seconds on the loop
        would hold up playback and the next utterance behind it."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: self.client.system_one(state, questions)
        )
        self.last = result
        if result.error:
            printr.print(
                f"Jev: {result.error}",
                color=LogType.WARNING,
                server_only=True,
            )
        return result

    # ── the command a transcript asks for ───────────────────────────

    async def pick_command(
        self, transcript: str, commands: list[CommandConfig]
    ) -> Optional[str]:
        """The command to run without asking the main model, or None.

        None is not a failure: it is the answer for every turn that needs a
        sentence rather than a keypress, and for every turn Jev was not sure
        enough about. Both go on to the main model exactly as before.
        """
        if not self.active or not commands:
            return None
        result = await self._ask(
            {"transcript": transcript}, command_questions(commands)
        )
        picked = read_command(result, COMMAND_CONFIDENCE)
        printr.print(
            f"Jev command: {result.choice('command')} "
            f"(confidence {result.confidence('command'):.2f}, "
            f"{result.seconds * 1000:.0f} ms) -> "
            f"{picked or 'main model decides'}",
            color=LogType.SYSTEM,
            server_only=True,
        )
        return picked

    # ── which skills this turn could need ───────────────────────────

    async def preselect_capabilities(
        self, transcript: str, groups: dict[str, str]
    ) -> Optional[set[str]]:
        """The skills worth activating up front, or None to change nothing.

        Today a skill the user needs costs an extra round trip: the model
        calls ``activate_capability``, the tool list changes, and the model
        is called again before anything happens. Naming the skill here skips
        that second call, which is the expensive half of the turn.
        """
        if not self.active or not groups:
            return None
        result = await self._ask({"transcript": transcript}, tool_group_questions(groups))
        kept = read_tool_groups(
            result, groups, CAPABILITY_THRESHOLD, unanswered_kept=False
        )
        if kept is not None:
            printr.print(
                f"Jev capabilities: {', '.join(sorted(kept)) or 'none'} "
                f"({result.seconds * 1000:.0f} ms)",
                color=LogType.SYSTEM,
                server_only=True,
            )
        return kept

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
        self.last = result
        if result.error:
            printr.print(f"Jev triage: {result.error}", color=LogType.WARNING, server_only=True)
            return {}
        return read_triage(result)

"""The three decisions the prototype hands to Jev, and how to read the answers.

Kept apart from the places that use them so each one can be measured on its
own against the path it would replace. Every function here is pure: it builds
questions or reads a ``JevResult``. Nothing calls the gateway, nothing touches
a wingman.

Each decision has a fallback and a threshold, and the two belong together:
below the threshold the caller does what it does today. That is what makes
this safe to switch on — a Jev that is unsure costs a few hundred milliseconds
and changes nothing.
"""

from typing import Any, Optional

from api.interface import CommandConfig
from providers.typesafe_jev import JevResult, choice, noul

NONE_OPTION = "none_of_these"
"""The option that means the user did not ask for any command. Jev's docs
recommend an explicit escape hatch over inferring one from low confidence:
without one, the probability mass has nowhere to go but onto the real
commands, and the confidence gate lets the least wrong one through."""

NONE_DESCRIPTION = (
    "Nothing should be triggered right now. Choose this whenever the speaker "
    "is not ordering an action to happen this moment, even when the sentence "
    "names one. That includes: questions about a command ('should I put the "
    "gear down?', 'what does the landing system do?'), talk about the past "
    "('I forgot to raise the shields', 'you turned the lights on yesterday'), "
    "asking to be reminded of something later ('remind me to jettison the "
    "cargo'), and anything that wants an answer, information or conversation "
    "instead of a keypress."
)
"""Spelled out because the measurement said so.

With a one-line description the model matched on the presence of the command
words rather than on what the speaker wanted done with them: five of five
precision traps fired, among them "remind me to jettison the cargo before I
land", which is a timer, not a keypress. The examples here are written in the
shape the docs recommend for options that are easy to confuse."""


# ── 1. Which command, if any ────────────────────────────────────────


def command_description(command: CommandConfig) -> Optional[str]:
    """What tells this command apart from its neighbours.

    The command name is already written to be self-describing — "DeployLandingGear"
    rather than "cmd_7" — so the description only has to add what the name
    leaves out. The instant-activation phrases are the best material for that:
    they are the user's own words for this command, written by the user.
    """
    parts = []
    phrases = [p for p in (command.instant_activation or []) if p]
    if phrases:
        parts.append("Said as: " + ", ".join(f'"{p}"' for p in phrases[:6]))
    if command.additional_context:
        parts.append(command.additional_context.strip())
    return " — ".join(parts) if parts else None


def command_questions(commands: list[CommandConfig]) -> dict[str, dict]:
    """A single Choice over the command names, plus the escape hatch."""
    criteria: dict[str, Optional[str]] = {
        command.name: command_description(command) for command in commands
    }
    criteria[NONE_OPTION] = NONE_DESCRIPTION
    return {
        "command": choice(
            instructions=(
                "A voice assistant is listening to the pilot of a spacecraft. "
                "It can press keys to trigger the commands below. Which command "
                "is the speaker ordering to happen right now? Decide by what "
                "the speaker wants done, not by which words appear: a command "
                "named inside a question, a memory, or a request for a later "
                "reminder is not an order to run it."
            ),
            criteria=criteria,
        )
    }


def read_command(result: JevResult, min_confidence: float) -> Optional[str]:
    """The command to execute, or None to let the main model decide.

    None covers all three ways this ends without a command: the call failed,
    Jev picked the escape hatch, or it was not sure enough.
    """
    if not result.ok:
        return None
    picked = result.choice("command", min_confidence=min_confidence)
    if picked is None or picked == NONE_OPTION:
        return None
    return picked


# ── 2. Which tool groups this turn could need ───────────────────────


def tool_group_questions(groups: dict[str, str]) -> dict[str, dict]:
    """One yes/no per skill or MCP server: could this turn need it?

    Grouping rather than asking per tool is deliberate. A skill's tools belong
    together — a turn that needs ``play_track`` often needs ``search_track``
    first — and dropping one sibling is the failure that actually hurts. At
    group level a wrong no costs the whole skill, which is easier to see in a
    measurement than a tool quietly missing from a list of thirty.
    """
    return {
        f"group_{name}": noul(
            instructions=(
                f"Could answering the user's last message need {description}? "
                "Answer yes if it might be needed, even indirectly."
            )
        )
        for name, description in groups.items()
    }


def read_tool_groups(
    result: JevResult,
    groups: dict[str, str],
    threshold: float,
    unanswered_kept: bool = True,
) -> Optional[set[str]]:
    """The groups above ``threshold``, or None if there is no usable answer.

    ``unanswered_kept`` is what to do with a question Jev did not answer, and
    the right value depends on which direction the caller is moving in. A
    caller that filters an existing tool list keeps it — a skipped question
    must not silently disable a skill. A caller that activates skills that
    are off drops it — a skipped question must not silently switch one on.
    """
    if not result.ok:
        return None
    kept = set()
    for name in groups:
        value = result.noul_value(f"group_{name}")
        if value is None:
            if unanswered_kept:
                kept.add(name)
            continue
        if value >= threshold:
            kept.add(name)
    return kept


# ── 3. What an utterance heard over the wingman actually was ────────


def triage_questions(wingman_names: list[str], during_playback: bool) -> dict[str, dict]:
    """The three things ``_on_transcript`` decides today by matching words.

    All three in one call, because they are one decision really: the text is
    either for us, or it is a stop, or it is our own voice coming back through
    the speakers. Asking them separately would cost three round trips to learn
    the same thing.
    """
    names = ", ".join(wingman_names) or "the assistant"
    questions = {
        "addressed": noul(
            instructions=(
                f"Is this spoken to a voice assistant ({names}) — a request, a "
                "question, or an order to it? Answer no for talk between people "
                "in the room, thinking out loud, or background noise written out "
                "as words."
            )
        ),
        "stop": noul(
            instructions=(
                "Does the speaker want the assistant to stop talking right now? "
                "Answer yes for interruptions like 'stop', 'be quiet', 'enough'. "
                "Answer no when the word stop is part of a request, as in "
                "'stop the engines'."
            )
        ),
    }
    if during_playback:
        questions["echo"] = noul(
            instructions=(
                "This was picked up while the assistant itself was speaking "
                "through the speakers. Is this the assistant's own sentence "
                "heard back by the microphone, rather than a person talking?"
            )
        )
    return questions


def read_triage(result: JevResult) -> dict[str, Any]:
    """The three answers as probabilities, for a caller that sets its own gates.

    Deliberately not a verdict. The thresholds belong where the consequences
    are: stopping playback by mistake is a small annoyance, answering the room's
    conversation is a large one, and only the caller knows which it is about
    to do.
    """
    return {
        "addressed": result.noul_value("addressed"),
        "stop": result.noul_value("stop"),
        "echo": result.noul_value("echo"),
    }

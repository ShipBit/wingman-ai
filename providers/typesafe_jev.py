"""The System One model, reached through Wingman Pro.

A System One model does not write text. It takes a state and a set of typed
questions and answers all of them in one parallel pass — a `noul` is a yes/no
as a probability, a `choice` picks one of up to 255 named options, a `score`
rates on ordered levels. Every answer carries a calibrated confidence, which
is the whole point: we can act on the confident ones and let the rest fall
through to the model that would have decided anyway.

Because the questions are evaluated in parallel, asking five costs about the
same wall clock as asking one. So the callers here ask everything they might
want in a single call and throw away what the turn did not need, rather than
making one round trip per decision.

Which model answers is the subscription's decision, not ours: it is a fixed
role like transcription and speech, so it can be swapped in the backend
without a Wingman release. Core never names a model here.

There is a second, direct route to the Vercel AI Gateway, used by the
benchmarks in ``evals/jev_bench`` and by anyone with their own gateway key.
It is the same request and the same response — the backend forwards both
untouched — so a measurement taken through one holds for the other.

Failures never raise. Every decision this model makes has an existing path
behind it — the main LLM, a word match, a token threshold — and a backend
that is down or slow must cost a few milliseconds, not the turn.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from api.enums import LogType
from services.printr import Printr

printr = Printr()

GATEWAY_URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
"""The direct route, for a user with their own AI Gateway key."""

MODEL = "typesafe-ai/jev"
"""Only sent on the direct route. Through Wingman Pro the backend picks the
model from the plan's role and ignores anything we would put here."""

INSTRUCTION_CHARS = 160
"""How much of a question reaches the log. Long enough to recognise which one
it was, short enough that a 54-option choice does not bury the answer."""

STATE_CHARS = 300
"""The state can be a whole tool response. This is enough to see what was
being decided about."""

TOP_SHARES = 4
"""Options listed with their share. Everything below the fourth is noise in a
54-option choice and the chosen one is always among them."""

PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
"""TypeSafe's list price, $0.042 per million input tokens, output free. A
53-command Choice measured 1,224 input tokens, so about $0.00005 a call."""

DEFAULT_TIMEOUT = 4.0
"""Jev answers in 70-500 ms direct, p50 503 ms through Wingman Pro, which adds
a hop. Two seconds looked generous against the first of those numbers and was
not: measured 2026-09-20, a normal call through Pro hit it and fell back for
nothing, paying the wait *and* losing the answer.

Four is the point where waiting has stopped being worth it — a chat model's
own p95 is 1.7 s and its worst measured call 7.5 s, so the fallback is not
cheap either. It only bites when something is actually wrong."""


def guidance(
    what: str,
    not_for: Optional[str] = None,
    examples: Optional[list[str]] = None,
) -> Any:
    """Instructions or an option description, plain or structured.

    A bare sentence is enough most of the time. When two things are easy to
    confuse, saying what something is *not* for separates them better than a
    longer description of what it is: measured on the same transcript, a
    structured instruction took the answer from 0.90 confidence to 1.00.

    Returns the plain string when there is nothing to add, so a caller can
    always route through here without producing noise in the request.
    """
    if not_for is None and not examples:
        return what
    block: dict[str, Any] = {"what": what}
    if not_for:
        block["not_for"] = not_for
    if examples:
        block["examples"] = list(examples)
    return block


def noul(
    instructions: str,
    not_for: Optional[str] = None,
    examples: Optional[list[str]] = None,
) -> dict:
    """A yes/no question. The answer is a probability, not a boolean."""
    return {"type": "noul", "instructions": guidance(instructions, not_for, examples)}


def choice(
    instructions: str,
    criteria: dict[str, Any],
    not_for: Optional[str] = None,
    examples: Optional[list[str]] = None,
) -> dict:
    """One of ``criteria``, which maps option name to a description.

    Up to 255 options. A description may be None, a sentence, or the
    structured form from ``guidance()``. Give one to every option that has a
    near neighbour: on Wingman's own command routing, descriptions cut wrong
    answers from 16 to 3 out of 152 and cost nothing in latency.
    """
    return {
        "type": "choice",
        "instructions": guidance(instructions, not_for, examples),
        "criteria": criteria,
    }


def score(
    instructions: str,
    criteria: list[str],
    not_for: Optional[str] = None,
    examples: Optional[list[str]] = None,
) -> dict:
    """A rating on the ordered levels in ``criteria``, lowest first.

    The answer is not one of the levels. It is a position on the scale they
    span — ``1.99`` on three levels means "almost entirely the third one" —
    plus a legend mapping index to label. ``JevResult.level()`` turns that
    back into the label a caller asked about.
    """
    return {
        "type": "score",
        "instructions": guidance(instructions, not_for, examples),
        "criteria": criteria,
    }


@dataclass
class JevResult:
    """What came back, plus what it cost us in time and money."""

    answers: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    cost: float = 0.0
    """What the gateway billed. Measured 2026-09-20 it comes back as 0 on
    every System One call — either it is below the precision the field is
    reported in, or the gateway does not meter this endpoint yet. Use
    ``estimated_cost`` for anything that has to add up."""
    input_tokens: int = 0
    error: Optional[str] = None

    @property
    def estimated_cost(self) -> float:
        """Input tokens at TypeSafe's list price. Output is free."""
        return self.input_tokens * PRICE_PER_INPUT_TOKEN

    @property
    def ok(self) -> bool:
        return self.error is None

    def noul(self, key: str, threshold: float = 0.5) -> Optional[bool]:
        """The yes/no answer, or None if it was not asked or the call failed.

        ``threshold`` is where yes starts. Raise it for a decision that is
        expensive to get wrong in the yes direction.
        """
        answer = self.answers.get(key)
        if not answer:
            return None
        value = answer.get("noul")
        return None if value is None else value >= threshold

    def noul_value(self, key: str) -> Optional[float]:
        """The raw probability, for callers that set their own threshold."""
        answer = self.answers.get(key)
        return None if not answer else answer.get("noul")

    def choice(self, key: str, min_confidence: float = 0.0) -> Optional[str]:
        """The chosen option, or None below ``min_confidence``."""
        answer = self.answers.get(key)
        if not answer or answer.get("choice") is None:
            return None
        if float(answer.get("confidence") or 0.0) < min_confidence:
            return None
        return answer["choice"]

    def confidence(self, key: str) -> float:
        answer = self.answers.get(key)
        return float((answer or {}).get("confidence") or 0.0)

    def probabilities(self, key: str) -> dict[str, float]:
        """Every option with its share, summing to 1, keyed by name.

        A score reports its shares by level index, not by label. They are
        mapped back through the legend here so a caller never has to know
        which of the two kinds of question it asked.
        """
        answer = self.answers.get(key) or {}
        raw = answer.get("probabilities") or {}
        legend = answer.get("legend")
        if not legend:
            return {str(name): float(value) for name, value in raw.items()}
        return {
            legend.get(str(index), str(index)): float(value)
            for index, value in raw.items()
        }

    def keys(self) -> list[str]:
        """The questions that came back with an answer."""
        return sorted(self.answers)

    def raw(self, key: str) -> dict:
        """The answer exactly as the model sent it, for anything not covered
        by a reader above."""
        return dict(self.answers.get(key) or {})

    def score(self, key: str) -> Optional[float]:
        """Where on the scale the answer sits, as a number.

        The levels span 0 to len-1, and the value is continuous: ``1.99`` on
        three levels is "almost entirely the third one", ``1.4`` is between
        the second and the third. Use ``level()`` for the label and this when
        the distance itself matters — a threshold, a slider, a sort.
        """
        answer = self.answers.get(key)
        if not answer or answer.get("score") is None:
            return None
        return float(answer["score"])

    def levels(self, key: str) -> list[str]:
        """The level labels, lowest first, as the model echoed them back."""
        answer = self.answers.get(key) or {}
        legend = answer.get("legend") or {}
        return [legend[index] for index in sorted(legend, key=int)]

    def level(self, key: str) -> Optional[str]:
        """The nearest level label, which is what most callers want.

        Rounds: 1.99 and 1.6 are both the third of three levels. A caller who
        needs the distance rather than the bucket reads ``score()``.
        """
        value = self.score(key)
        labels = self.levels(key)
        if value is None or not labels:
            return None
        index = min(len(labels) - 1, max(0, round(value)))
        return labels[index]


def _shorten(text: Any, limit: int) -> str:
    """One line, no longer than ``limit``. A transcript with a newline in it
    would otherwise break the alignment of everything under it."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def _instructions_of(question: dict) -> str:
    """The question as one line, structured or plain."""
    instructions = question.get("instructions")
    if isinstance(instructions, dict):
        parts = [str(instructions.get("what", ""))]
        if instructions.get("not_for"):
            parts.append(f"NOT: {instructions['not_for']}")
        return _shorten(" | ".join(parts), INSTRUCTION_CHARS)
    return _shorten(instructions, INSTRUCTION_CHARS)


def _answer_line(answer: dict) -> str:
    """What came back, with enough of the distribution to argue with.

    The runners-up are the point: a wrong choice at 0.51 against a 0.49 is a
    different problem from a wrong one at 0.99, and only the log can say
    which happened after the fact.
    """
    kind = answer.get("type")
    if kind == "noul":
        return f"{answer.get('noul')}"
    shares = answer.get("probabilities") or {}
    legend = answer.get("legend")
    if legend:
        shares = {legend.get(str(k), str(k)): v for k, v in shares.items()}
    ranked = sorted(shares.items(), key=lambda item: -float(item[1]))[:TOP_SHARES]
    tail = ", ".join(f"{name} {float(value):.2f}" for name, value in ranked)
    if kind == "score":
        value = answer.get("score")
        label = None
        if legend and value is not None:
            labels = [legend[i] for i in sorted(legend, key=int)]
            label = labels[min(len(labels) - 1, max(0, round(float(value))))]
        head = f"{value} ({label})" if label else f"{value}"
    else:
        head = str(answer.get("choice"))
    return f"{head}  conf {float(answer.get('confidence') or 0):.2f}  [{tail}]"


def _log_failure(state: Any, questions: dict[str, dict], result: "JevResult") -> "JevResult":
    """A call that produced nothing, and what it was about.

    Logged as a warning rather than swallowed: the caller carries on with its
    old path and the user sees a working assistant, so without this line a
    gateway that is down looks exactly like a gateway nobody configured.
    """
    printr.print(
        f"Jev failed after {result.seconds * 1000:.0f} ms: {result.error}\n"
        f"  asked: {', '.join(questions)}\n"
        f"  state: {_shorten(state, STATE_CHARS)}",
        color=LogType.WARNING,
        server_only=True,
    )
    return result


def _log_exchange(state: Any, questions: dict[str, dict], result: "JevResult") -> None:
    """Every exchange, in the log file and nowhere else.

    Always, not behind debug_mode: these decisions happen before the main
    model sees anything and change what it is even asked. When a user reports
    that the wrong command fired or a name came out wrong, this is the only
    place the reason is written down, and asking them to reproduce it with a
    flag set means asking them to reproduce a 300 ms decision they cannot
    see.
    """
    lines = [
        f"Jev: {len(questions)} question(s), {result.seconds * 1000:.0f} ms, "
        f"{result.input_tokens} tok, ${result.estimated_cost:.8f}",
        f"  state: {_shorten(state, STATE_CHARS)}",
    ]
    for key, question in questions.items():
        kind = question.get("type", "?")
        criteria = question.get("criteria")
        size = f"({len(criteria)})" if isinstance(criteria, (dict, list)) else ""
        lines.append(f"  ? {key} [{kind}{size}] {_instructions_of(question)}")
        answer = result.answers.get(key)
        lines.append(f"  = {key}: {_answer_line(answer) if answer else 'not answered'}")
    printr.print("\n".join(lines), color=LogType.SYSTEM, server_only=True)


class JevClient:
    """One HTTP call per decision batch. Holds no state beyond the credential.

    The credential is an AI Gateway key, not a TypeSafe key: the gateway bills
    the call and passes the request through unchanged, so the request and
    response shapes are TypeSafe's own and a later move to TypeSafe direct is
    a base URL change.
    """

    def __init__(
        self,
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        subscription: Optional[Any] = None,
    ):
        self.subscription = subscription
        """``WingmanProSettings`` when Core is signed in. Its presence is what
        chooses the route: the plan pays for the call and the backend picks the
        model, so there is nothing for a user to configure."""
        self.api_key = api_key or os.environ.get("AI_GATEWAY_API_KEY", "")
        self.timeout = timeout
        self._session = requests.Session()
        self._secret_keeper = None

    def _pro_token(self) -> str:
        """The subscription token, read fresh: a user can sign in while Core
        runs, and a client built at startup must not stay signed out."""
        if self.subscription is None:
            return ""
        if self._secret_keeper is None:
            from services.secret_keeper import SecretKeeper

            self._secret_keeper = SecretKeeper()
        return self._secret_keeper.secrets.get("wingman_pro", "") or ""

    def is_ready(self) -> bool:
        return bool(self._pro_token() or self.api_key)

    def system_one(self, state: Any, questions: dict[str, dict]) -> JevResult:
        """Answer every question in ``questions`` against ``state``.

        ``state`` is whatever the decision is about: a transcript, or a dict of
        several things the questions may refer to. It is sent as-is.
        """
        if not questions:
            return JevResult(error="no questions")

        token = self._pro_token()
        if token:
            url = f"{self.subscription.base_url}/api/v1/systemone"
            payload = {"state": state, "questions": questions}
        elif self.api_key:
            token = self.api_key
            url = GATEWAY_URL
            payload = {"model": MODEL, "state": state, "questions": questions}
        else:
            return JevResult(error="not signed in to Wingman Pro and no AI_GATEWAY_API_KEY")

        started = time.perf_counter()
        try:
            response = self._session.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return _log_failure(state, questions, JevResult(
                seconds=time.perf_counter() - started, error=str(e)))

        seconds = time.perf_counter() - started
        if not response.ok:
            return _log_failure(state, questions, JevResult(
                seconds=seconds, error=f"HTTP {response.status_code}: {response.text[:300]}"))
        try:
            body = response.json()
        except json.JSONDecodeError as e:
            return _log_failure(state, questions, JevResult(
                seconds=seconds, error=f"bad JSON: {e}"))

        usage = body.get("usage") or {}
        gateway = ((body.get("provider_metadata") or {}).get("gateway")) or {}
        result = JevResult(
            answers=body.get("answers") or {},
            seconds=seconds,
            cost=float(gateway.get("cost") or 0.0),
            input_tokens=int(usage.get("input_tokens") or 0),
        )
        _log_exchange(state, questions, result)
        return result

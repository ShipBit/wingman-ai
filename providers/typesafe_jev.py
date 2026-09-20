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

GATEWAY_URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
"""The direct route, for a user with their own AI Gateway key."""

MODEL = "typesafe-ai/jev"
"""Only sent on the direct route. Through Wingman Pro the backend picks the
model from the plan's role and ignores anything we would put here."""

PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
"""TypeSafe's list price, $0.042 per million input tokens, output free. A
53-command Choice measured 1,224 input tokens, so about $0.00005 a call."""

DEFAULT_TIMEOUT = 2.0
"""Jev answers in 70-500 ms. Anything past two seconds is a gateway problem,
and waiting it out is worse than falling back: the fallback is the path we
would have taken without Jev at all."""


def noul(instructions: str) -> dict:
    """A yes/no question. The answer is a probability, not a boolean."""
    return {"type": "noul", "instructions": instructions}


def choice(instructions: str, criteria: dict[str, Optional[str]]) -> dict:
    """One of ``criteria``, which maps option name to a description (or None).

    Up to 255 options. Give every option a description when two of them could
    be confused; the descriptions are what the model separates them by.
    """
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: str, criteria: list[str]) -> dict:
    """A rating on the ordered levels in ``criteria``, lowest first."""
    return {"type": "score", "instructions": instructions, "criteria": criteria}


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
        answer = self.answers.get(key)
        return dict((answer or {}).get("probabilities") or {})

    def score(self, key: str) -> Optional[str]:
        answer = self.answers.get(key)
        return None if not answer else answer.get("score")


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
            return JevResult(seconds=time.perf_counter() - started, error=str(e))

        seconds = time.perf_counter() - started
        if not response.ok:
            return JevResult(
                seconds=seconds, error=f"HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
        except json.JSONDecodeError as e:
            return JevResult(seconds=seconds, error=f"bad JSON: {e}")

        usage = body.get("usage") or {}
        gateway = ((body.get("provider_metadata") or {}).get("gateway")) or {}
        return JevResult(
            answers=body.get("answers") or {},
            seconds=seconds,
            cost=float(gateway.get("cost") or 0.0),
            input_tokens=int(usage.get("input_tokens") or 0),
        )

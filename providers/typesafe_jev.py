"""Jev, TypeSafe AI's System One model, reached through the Vercel AI Gateway.

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

Failures never raise. Every decision this model makes has an existing path
behind it — the main LLM, a word match, a token threshold — and a gateway
that is down or slow must cost a few milliseconds, not the turn.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

GATEWAY_URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
MODEL = "typesafe-ai/jev"

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
    input_tokens: int = 0
    error: Optional[str] = None

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

    def __init__(self, api_key: str = "", timeout: float = DEFAULT_TIMEOUT):
        self.api_key = api_key or os.environ.get("AI_GATEWAY_API_KEY", "")
        self.timeout = timeout
        self._session = requests.Session()

    def is_ready(self) -> bool:
        return bool(self.api_key)

    def system_one(self, state: Any, questions: dict[str, dict]) -> JevResult:
        """Answer every question in ``questions`` against ``state``.

        ``state`` is whatever the decision is about: a transcript, or a dict of
        several things the questions may refer to. It is sent as-is.
        """
        if not self.api_key:
            return JevResult(error="no AI_GATEWAY_API_KEY")
        if not questions:
            return JevResult(error="no questions")

        payload = {"model": MODEL, "state": state, "questions": questions}
        started = time.perf_counter()
        try:
            response = self._session.post(
                GATEWAY_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
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

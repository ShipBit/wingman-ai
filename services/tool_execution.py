"""Internal, task-local provenance for tools, including lazily activated skills."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4
from services.elite_runtime_identity import capture

capture(__file__)


@dataclass(frozen=True)
class UserTurn:
    id: str
    text: str
    previous_id: str | None = None
    # Runtime-only decisions. Never included in tool schemas or conversation.
    routes: dict = field(default_factory=dict, compare=False)


@dataclass
class ControlAuthorization:
    turn_id: str
    action: str
    state: str
    mode: str
    context: dict = field(default_factory=dict)
    call_id: str = ""
    _lock: Lock = field(default_factory=Lock, repr=False)

    def validate(self, turn_id, action, state, mode, call_id):
        with self._lock:
            if ((turn_id, action.replace(" ", "_"), state, mode) !=
                    (self.turn_id, self.action, self.state, self.mode)):
                raise ValueError("The control does not match this turn's authorized intent.")
            if self.call_id and self.call_id != call_id:
                raise ValueError("This turn already dispatched its control. No new input sent.")
            self.call_id = call_id


@dataclass(frozen=True)
class SkillRoute:
    kind: str
    request: tuple | None = None
    reply: str = ""
    authorization: ControlAuthorization | None = None


current_turn = ContextVar("wingman_user_turn", default=None)
current_call = ContextVar("wingman_tool_call", default=None)


def begin_turn(wingman, text):
    turn = UserTurn(uuid4().hex, text, previous_id=getattr(wingman, "latest_user_turn_id", None))
    wingman.latest_user_turn_id = turn.id
    current_turn.set(turn)
    return turn


@contextmanager
def tool_call_scope(call_id):
    # Missing provider IDs still get distinct requests, never text-based deduping.
    token = current_call.set(call_id or uuid4().hex)
    try:
        yield
    finally:
        current_call.reset(token)

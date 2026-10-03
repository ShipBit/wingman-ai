"""Small internal result contract. Speech is always rendered from this record."""

from dataclasses import asdict, dataclass, field

SCHEMA_REVISION = 3


@dataclass
class ControlResult:
    request_id: str
    intent: dict
    outcome: str
    reason: str
    first_failing_stage: str = ""
    input_events: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def speech(self):
        if self.outcome == "input_sent":
            # Acknowledge the requested action in the companion's voice. This
            # is deliberately not an assertion of the resulting game state.
            return {"lights": "Toggling lights, Commander.",
                    "night_vision": "Toggling night vision, Commander."}.get(
                        self.intent.get("action"), "Aye, Commander.")
        prefix = {"confirmed": "Confirmed", "already_set": "Already set",
                  "invalid": "Invalid request", "blocked": "Blocked",
                  "failed": "Failed", "unverified": "Unverified",
                  "cancelled": "Cancelled", "duplicate": "Duplicate request",
                  "status": "Controls"}[self.outcome]
        return f"{prefix}: {self.reason}"

    def to_dict(self):
        return {**asdict(self), "schema_revision": SCHEMA_REVISION,
                "input_attempted": bool(self.input_events),
                "windows_accepted": any(e.get("inserted", 0) for e in self.input_events),
                "gameplay_verified": self.outcome == "confirmed",
                "speech": self.speech}

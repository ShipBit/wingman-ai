"""Bounded, literal presentation of committed events; no delivery or state effects.

The default global bucket permits three messages, then one per five seconds.
Unavailable tokens drop messages immediately; there is no deferred rate backlog.
Queued messages expire after ten seconds. Quiet episodes close after thirty
seconds without claiming recovery. Active repeats may summarize every minute.
All clocks are caller supplied monotonic seconds, separate from log timestamps.
"""

import math
from collections import OrderedDict, deque
from dataclasses import dataclass

# Category and wording belong to fixed code, never to a log/instruction template.
_TEMPLATES = {
    "user_login": ("session", "Player logged in"),
    "session_start": ("session", "Session started for player"),
    "join_pu": ("session", "Player joined the universe"),
    "mission_accepted": ("mission", "Mission accepted"),
    "mission_complete": ("mission", "Mission complete observed"),
    "mission_failed": ("mission", "Mission failure observed"),
    "mission_withdrawn": ("mission", "Mission withdrawal observed"),
    "mission_objective_new": ("mission", "Mission objective observed"),
    "objective_new": ("mission", "Objective observed"),
    "objective_complete": ("mission", "Objective completion observed"),
    "restricted_area": ("safety", "Player restricted-area status reported"),
    "armistice_zone": ("safety", "Player armistice-zone status reported"),
    "injury": ("health", "Player injury observed"),
    "med_bed_heal": ("health", "Player received medical-bed healing"),
    "location_arrived": ("location", "Player location reported"),
    "location_departed": ("location", "Player departure reported from location"),
    "location_change": ("location", "Player location code unresolved"),
    "ship_entered": ("ship", "Player boarded ship"),
    "ship_exited": ("ship", "Player left ship"),
    "reward_earned": ("money", "Reward observed"),
    "fined": ("money", "Fine observed"),
    "money_sent": ("money", "Money transfer observed"),
    "shop_buy": ("money", "Shop purchase observation"),
    "shop_sell": ("money", "Shop sale observation"),
}
# Select details by their meaning, never by the first nonempty event field.
# In particular, a player's name cannot supply a location, ship or injury.
_DETAIL_FIELDS = {
    "user_login": ("player_name",),
    "session_start": ("player_name",),
    "join_pu": (),
    "mission_accepted": ("mission_name", "mission_id"),
    "mission_complete": ("mission_name", "mission_id"),
    "mission_failed": ("mission_name", "mission_id"),
    "mission_withdrawn": ("mission_name", "mission_id"),
    "mission_objective_new": ("objective",),
    "objective_new": ("objective",),
    "objective_complete": ("objective",),
    "restricted_area": ("action",),
    "armistice_zone": ("action",),
    "injury": ("body_part",),
    "med_bed_heal": ("body_part",),
    "location_arrived": ("location_name",),
    "location_departed": ("location_name",),
    "location_change": ("location",),
    "ship_entered": ("ship_name",),
    "ship_exited": ("ship_name",),
    "reward_earned": ("mission_name",),
    "fined": (),
    "money_sent": ("recipient",),
    "shop_buy": ("item_name",),
    "shop_sell": ("item_name",),
}
# User-facing observations supported by the reader but omitted from the first
# replacement notification panel. Wording never upgrades a request to success.
_ADDITIONAL = {
    "contract_shared": ("mission", "Contract shared", ("mission_name",)),
    "contract_available": ("mission", "Contract available", ("mission_name",)),
    "objective_withdrawn": ("mission", "Objective withdrawn", ("objective",)),
    "quantum_route_set": ("location", "Quantum route set", ()),
    "quantum_calibration_started": ("location", "Quantum calibration started", ("player",)),
    "quantum_calibration_complete": ("location", "Quantum calibration complete", ()),
    "qt_calibration_complete_group": ("location", "Party member quantum calibration complete", ("player",)),
    "qt_arrived": ("location", "Quantum-drive arrival observed", ("entity_class",)),
    "hangar_ready": ("ship", "Hangar ready notification observed", ()),
    "hangar_queue": ("ship", "Hangar queue notification observed", ()),
    "entered_monitored_space": ("safety", "Player entered monitored space", ()),
    "exited_monitored_space": ("safety", "Player left monitored space", ()),
    "monitored_space_down": ("safety", "Monitored space offline notification observed", ()),
    "monitored_space_restored": ("safety", "Monitored space restored notification observed", ()),
    "jurisdiction_change": ("safety", "Jurisdiction reported", ("jurisdiction",)),
    "emergency_services": ("health", "Emergency services en route notification observed", ()),
    "bleeding": ("health", "Player bleeding observed", ()),
    "incapacitated": ("health", "Player incapacitation observed", ()),
    "fuel_low": ("ship", "Low fuel warning observed", ()),
    "crimestat_increased": ("safety", "CrimeStat increase observed", ()),
    "vehicle_impounded": ("ship", "Vehicle impounded notification observed", ("vehicle",)),
    "party_invite": ("session", "Party invitation received", ("from_player",)),
    "incoming_call": ("session", "Incoming call", ("caller",)),
    "party_member_joined": ("session", "Party member joined", ("player",)),
    "party_left": ("session", "Player left party", ()),
    "journal_entry": ("session", "Journal entry added", ("subject",)),
    "refinery_complete": ("money", "Refinery work-order notification observed", ("location",)),
    "refinery_submitted": ("money", "Refinery submission requested", ()),
    "transaction_complete": ("money", "Transaction completion notification observed", ()),
    "blueprint_received": ("money", "Blueprint received notification observed", ("blueprint_name",)),
    "fatal_collision": ("ship", "Fatal vehicle collision observed", ("vehicle",)),
    "insurance_claim": ("ship", "Insurance claim requested", ()),
    "insurance_claim_complete": ("ship", "Insurance claim result observed", ("result",)),
    "cargo_transfer": ("money", "Cargo transfer requested", ()),
    "commodity_buy": ("money", "Commodity purchase requested", ("item_name",)),
    "commodity_sell": ("money", "Commodity sale requested", ("item_name",)),
}
for _kind, (_category, _wording, _details) in _ADDITIONAL.items():
    _TEMPLATES[_kind] = (_category, _wording)
    _DETAIL_FIELDS[_kind] = _details

# One checkbox for each notification type; opposite directions of the same
# status share a checkbox. Raw inventory/channel observations stay silent.
_GROUPS = {
    "notify_armistice_zone": ("armistice_zone",),
    "notify_ship_boarding": ("ship_entered", "ship_exited"),
    "notify_location_updates": ("location_arrived", "location_departed", "location_change"),
    "notify_monitored_space": ("entered_monitored_space", "exited_monitored_space"),
    "notify_monitored_space_availability": ("monitored_space_down", "monitored_space_restored"),
    "notify_mission_objective_new": ("mission_objective_new", "objective_new"),
    "notify_party_membership": ("party_member_joined", "party_left"),
}
_GROUPED_EVENTS = frozenset(kind for kinds in _GROUPS.values() for kind in kinds)
NOTIFICATION_OPTIONS = {
    **{"notify_" + kind: (kind,) for kind in _TEMPLATES if kind not in _GROUPED_EVENTS},
    **_GROUPS,
}
_LEGACY_OPTIONS = {
    "notify_armistice_zone": ("notify_zone_entered_armistice", "notify_zone_left_armistice"),
    "notify_ship_boarding": ("notify_ship_entered", "notify_ship_exited"),
    "notify_location_updates": ("notify_location_arrived", "notify_location_departed"),
    "notify_monitored_space": ("notify_entered_monitored_space", "notify_exited_monitored_space"),
    "notify_monitored_space_availability": ("notify_monitored_space_down", "notify_monitored_space_restored"),
    "notify_party_membership": ("notify_party_member_joined", "notify_party_left"),
    "notify_hangar_ready": ("notify_hangar_access",),
}
_AMOUNT_EVENTS = frozenset(("reward_earned", "fined", "money_sent", "shop_buy", "shop_sell"))
_CATEGORIES = frozenset(category for category, _ in _TEMPLATES.values())


def enabled_notification_events(settings):
    """Apply visible group masters and the individual notification switches.

    When only old directional switches exist, any disabled direction keeps the
    combined type off until the user explicitly chooses the new switch.
    """
    enabled = set()
    for option, kinds in NOTIFICATION_OPTIONS.items():
        category = _TEMPLATES[kinds[0]][0]
        if not settings.get("notify_" + category, True):
            continue
        if option in settings:
            selected = settings[option]
        else:
            selected = all(
                settings.get(old, True) for old in _LEGACY_OPTIONS.get(option, ())
            )
        if selected:
            enabled.update(kinds)
    return frozenset(enabled)


_KEY_FIELDS = (
    "action",
    "mission_id",
    "mission_name",
    "objective",
    "player_name",
    "location",
    "location_name",
    "ship_name",
    "body_part",
    "recipient",
    "item_name",
    "player",
    "from_player",
    "caller",
    "subject",
    "jurisdiction",
    "vehicle",
    "entity_class",
    "blueprint_name",
    "result",
)
_COUNTERS = (
    "offered",
    "suppressed",
    "unknown",
    "disabled",
    "catchup",
    "invalid",
    "key_evicted",
    "environment_evicted",
    "queue_dropped",
    "expired",
    "context_dropped",
    "rate_dropped",
    "delivered",
    "delivery_failed",
    "clock_resets",
)


def _literal(value, limit=128):
    """Bound scalar text and make control/markup characters visibly literal."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = str(value)[:limit]
    return "".join(ch if ch.isprintable() and ch not in "<>&" else " " for ch in text)[
        :limit
    ].strip()


@dataclass
class _Episode:
    message: dict
    last_seen: float
    last_summary: float
    repeats: int = 0


class NotificationPolicy:
    """Pure presentation policy. Inputs must already be committed canonical rows.

    ``flush`` removes output before a caller attempts delivery. The optional
    ``delivery_failed`` hook counts failures and never requeues them. No callback,
    host, command, network, model, ledger or mutable domain state is referenced.
    Tracking uses deterministic oldest-insertion eviction. References are capped
    at eight strings of 128 characters; text at 512; key fields at 128 each.
    """

    def __init__(
        self,
        enabled_categories=None,
        *,
        enabled_events=None,
        max_keys=256,
        max_pending=100,
        summary_interval=60.0,
        quiet_interval=30.0,
        max_environments=5,
        delivery_burst=3,
        delivery_interval=5.0,
        queue_expiry=10.0,
    ):
        for value, upper in (
            (max_keys, 256),
            (max_pending, 100),
            (max_environments, 5),
            (delivery_burst, 3),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= upper
            ):
                raise ValueError("Invalid presentation capacity")
        for value in (
            summary_interval,
            quiet_interval,
            delivery_interval,
            queue_expiry,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Invalid presentation interval")
        self.enabled_categories = frozenset(
            _CATEGORIES if enabled_categories is None else enabled_categories
        )
        if not self.enabled_categories <= _CATEGORIES:
            raise ValueError("Unknown notification category")
        self.enabled_events = frozenset(
            _TEMPLATES if enabled_events is None else enabled_events
        )
        if not self.enabled_events <= _TEMPLATES.keys():
            raise ValueError("Unknown notification event")
        self.max_keys = max_keys
        self.max_pending = max_pending
        self.max_environments = max_environments
        self.summary_interval = summary_interval
        self.quiet_interval = quiet_interval
        self.delivery_burst = delivery_burst
        self.delivery_interval = delivery_interval
        self.queue_expiry = queue_expiry
        self._streams = OrderedDict()
        self._pending = deque()
        self._counts = dict.fromkeys(_COUNTERS, 0)
        self._clock = None
        self._tokens = float(delivery_burst)

    @property
    def stats(self):
        return dict(
            self._counts,
            pending=len(self._pending),
            environments=len(self._streams),
            tracked_keys=sum(len(stream[1]) for stream in self._streams.values()),
        )

    def _advance(self, now):
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            raise ValueError("Clock must be finite monotonic seconds")
        if self._clock is not None:
            if now < self._clock:
                self._counts["clock_resets"] += 1
                self._counts["context_dropped"] += len(self._pending)
                self._pending.clear()
                self._streams.clear()
                # Keep the high-water clock: oscillation must not mint tokens.
                return
            else:
                self._tokens = min(
                    self.delivery_burst,
                    self._tokens + (now - self._clock) / self.delivery_interval,
                )
        self._clock = now
        kept = deque()
        for created, message in self._pending:
            if now - created >= self.queue_expiry:
                self._counts["expired"] += 1
            else:
                kept.append((created, message))
        self._pending = kept
        for _, episodes in self._streams.values():
            for key in list(episodes):
                if now - episodes[key].last_seen >= self.quiet_interval:
                    del episodes[key]

    def _reset_stream(self, environment):
        self._streams.pop(environment, None)
        kept = deque()
        for item in self._pending:
            if item[1]["environment"] == environment:
                self._counts["context_dropped"] += 1
            else:
                kept.append(item)
        self._pending = kept

    def discard_environment(self, environment):
        """Purge presentation context even when a backlog poll emits no rows."""
        self._reset_stream(environment)

    def _queue(self, message, now):
        if len(self._pending) >= self.max_pending:
            self._counts["queue_dropped"] += 1
            return
        self._pending.append((now, message))

    def offer(self, event: dict, *, now: float, catching_up: bool) -> None:
        self._advance(now)
        self._counts["offered"] += 1
        if not isinstance(event, dict):
            self._counts["invalid"] += 1
            return
        environment = event.get("environment")
        generation = event.get("generation")
        # Exact bounded identities prevent a truncated generation collision.
        if not all(
            isinstance(v, str) and 0 < len(v) <= 128 for v in (environment, generation)
        ):
            self._counts["invalid"] += 1
            return
        if catching_up:
            self._counts["catchup"] += 1
            self._reset_stream(environment)
            return
        previous = self._streams.get(environment)
        if previous and previous[0] != generation:
            self._reset_stream(environment)
        if environment not in self._streams:
            if len(self._streams) >= self.max_environments:
                oldest = next(iter(self._streams))
                self._reset_stream(oldest)
                self._counts["environment_evicted"] += 1
            self._streams[environment] = (generation, OrderedDict())
        kind = event.get("event_type")
        template = _TEMPLATES.get(kind) if isinstance(kind, str) else None
        if template is None:
            self._counts["unknown"] += 1
            return
        category, wording = template
        if category not in self.enabled_categories or kind not in self.enabled_events:
            self._counts["disabled"] += 1
            return
        data = event.get("data")
        if not isinstance(data, dict):
            self._counts["invalid"] += 1
            return
        fields = tuple(_literal(data.get(field)) for field in _KEY_FIELDS)
        key = (
            kind,
            _literal(event.get("status")),
            _literal(event.get("amount_auec")),
            *fields,
        )
        episodes = self._streams[environment][1]
        if key in episodes:
            episode = episodes[key]
            episode.last_seen = now
            episode.repeats += 1
            refs = event.get("source_occurrences")
            if isinstance(refs, list):
                retained = episode.message["source_occurrences"]
                for ref in refs[:8]:
                    literal = _literal(ref) if isinstance(ref, str) else ""
                    if literal and literal not in retained:
                        if len(retained) == 8:
                            retained.pop()
                        retained.append(literal)
            self._counts["suppressed"] += 1
            return
        if len(episodes) >= self.max_keys:
            episodes.popitem(last=False)
            self._counts["key_evicted"] += 1
        detail = next(
            (
                value
                for field in _DETAIL_FIELDS[kind]
                if (value := _literal(data.get(field)))
            ),
            "",
        )
        text = wording + (": " + detail if detail else "")
        if kind in _AMOUNT_EVENTS:
            amount = event.get("amount_auec")
            known = (
                not isinstance(amount, bool)
                and isinstance(amount, (int, float))
                and math.isfinite(amount)
            )
            text += "; amount " + (
                _literal(amount, 32) + " aUEC" if known else "unknown"
            )
            if kind.startswith("shop_"):
                text += "; " + (
                    "confirmed" if event.get("status") == "confirmed" else "requested"
                )
        refs = event.get("source_occurrences")
        refs = (
            [_literal(ref) for ref in refs[:8] if isinstance(ref, str)]
            if isinstance(refs, list)
            else []
        )
        message = {
            "category": category,
            "text": text[:512],
            "source_occurrences": refs,
            "repeat_count": 0,
            "environment": environment,
            "generation": generation,
        }
        episodes[key] = _Episode(message, now, now)
        self._queue(dict(message, source_occurrences=list(refs)), now)

    def flush(self, *, now: float) -> list[dict]:
        self._advance(now)
        for _, episodes in self._streams.values():
            for episode in episodes.values():
                if (
                    episode.repeats
                    and now - episode.last_summary >= self.summary_interval
                ):
                    message = dict(episode.message)
                    message["source_occurrences"] = list(message["source_occurrences"])
                    message["repeat_count"] = episode.repeats
                    message["text"] = (
                        message["text"]
                        + f"; repeated {episode.repeats} additional times"
                    )[:512]
                    self._queue(message, now)
                    episode.repeats = 0
                    episode.last_summary = now
        output = []
        while self._pending:
            _, message = self._pending.popleft()
            if self._tokens >= 1:
                self._tokens -= 1
                output.append(message)
                self._counts["delivered"] += 1
            else:
                self._counts["rate_dropped"] += 1
        return output

    def delivery_failed(self, message=None) -> None:
        """Count one failed caller delivery; retain no message and never retry."""
        self._counts["delivery_failed"] += 1

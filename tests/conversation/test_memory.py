"""Persistent memory: the fact filter, checkpoints, episodes and the MEMORY
block.

A checkpoint hands the stored facts, the episode so far and the new messages
to the support model and takes back the whole list. The block in the system
prompt holds every fact and the recent episodes with their age.

The fact filter lives in code because the prompt alone did not hold: a real
database had "Destination is Area18", "Set a timer for three minutes" and
"Current time is Monday ..." stored as durable facts, every one of them
forbidden by the prompt.
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass

import pytest

from services import persistent_memory as pm
from services.persistent_memory import PersistentMemoryService, age_label


@dataclass
class Result:
    text: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False


@dataclass
class Budget:
    max_input_tokens: int


class FakeAi:
    """Hash embeddings and a scripted answer. Equal strings are equal vectors;
    different strings are close to orthogonal, so the duplicate check never
    merges two different facts by chance. (Python's hash() is salted per run,
    which made an earlier version of this fake flaky.)"""

    def __init__(self, answer: str | None = None, window: int = 100_000):
        self.answer = answer
        self.window = window
        self.support_calls: list[str] = []

    def embed(self, texts):
        out = []
        for t in texts:
            digest = hashlib.sha256(t.encode()).digest()
            out.append([1.0 if (digest[i // 8] >> (i % 8)) & 1 else -1.0 for i in range(128)])
        return out

    def get_token_budget(self, system_prompt="", reasoning=False):
        return Budget(max_input_tokens=self.window)

    def support(self, text, system_prompt="", **kwargs):
        self.support_calls.append(text)
        return Result(text=self.answer)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "get_persistent_memory_dir", lambda: str(tmp_path))
    svc = PersistentMemoryService("Test", FakeAi())
    svc.initialize()
    yield svc
    svc.close()


# ── the filter ─────────────────────────────────────────────────────


def test_typed_facts_outside_the_allowed_kinds_are_dropped(service):
    raw = [
        {"kind": "identity", "text": "Name is Shackles"},
        {"kind": "event", "text": "Was attacked by two Cutlass Blacks near Yela"},
        {"kind": "location", "text": "Destination is Area18"},
        {"kind": "possession", "text": "Owns a Cutlass Black"},
        {"kind": "", "text": "Set a timer for three minutes"},
    ]

    assert service._clean_facts(raw) == ["Name is Shackles", "Owns a Cutlass Black"]


def test_transient_wording_is_dropped_even_without_a_kind(service):
    raw = [
        "Name is Shackles",
        "Current time is Monday, September 14, 2026, at 11:36 AM",
        "Current date is Monday, September 14, 2026",
        "Shields were damaged to fifteen percent during an attack",
        "Status of systems: all operational",
        "Friend is named Marcus",
    ]

    assert service._clean_facts(raw) == ["Name is Shackles", "Friend is named Marcus"]


def test_plain_strings_from_an_old_prompt_still_work(service):
    assert service._clean_facts(["Owns a Prospector", "x", None, 42]) == ["Owns a Prospector"]


def test_a_goal_with_a_number_is_not_mistaken_for_a_status(service):
    assert service._clean_facts([{"kind": "goal", "text": "Saving 12 million aUEC for an Idris"}]) == [
        "Saving 12 million aUEC for an Idris"
    ]


# ── the checkpoint call ────────────────────────────────────────────


def answer(facts, episode=None):
    return json.dumps({
        "facts": [{"kind": "possession", "text": f} for f in facts],
        "episode": episode or {"happened": "", "memorable": "", "open": ""},
    })


def turns(n):
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"user line {i}"})
        msgs.append({"role": "assistant", "content": f"reply {i}"})
    return msgs


def facts_of(svc):
    return sorted(e.content for e in svc.get_all(entry_type="fact"))


def test_the_model_sees_stored_facts_and_the_new_messages(service):
    service._add_memory_impl("fact", "Owns an Aurora MR")
    service.local_ai_service.answer = answer(["Owns a Freelancer (sold the Aurora MR)"])

    service.checkpoint_sync(turns(4))

    sent = service.local_ai_service.support_calls[0]
    assert "STORED FACTS:\n1. Owns an Aurora MR" in sent
    assert "NEW MESSAGES:\nuser: user line 0" in sent
    assert facts_of(service) == ["Owns a Freelancer (sold the Aurora MR)"]


def test_the_list_is_replaced_not_appended(service):
    service._add_memory_impl("fact", "Name is Shackles")
    service._add_memory_impl("fact", "Member of the Sternenjäger org")
    service.local_ai_service.answer = answer(["Name is Shackles", "Owns a Cutlass Black"])

    outcome = service.checkpoint_sync(turns(4))

    assert facts_of(service) == ["Name is Shackles", "Owns a Cutlass Black"]
    assert outcome["before"] == 2 and outcome["after"] == 2 and outcome["changed"]


def test_an_unchanged_fact_keeps_its_row(service):
    fact_id = service._add_memory_impl("fact", "Name is Shackles")
    service.local_ai_service.answer = answer(["Name is Shackles", "Owns a Cutlass Black"])

    service.checkpoint_sync(turns(4))

    kept = [e for e in service.get_all(entry_type="fact") if e.content == "Name is Shackles"]
    assert kept[0].id == fact_id


def test_a_model_that_loses_most_of_the_list_is_refused(service):
    for i in range(9):
        service._add_memory_impl("fact", f"Owns ship number {i}")
    service.local_ai_service.answer = answer(["Owns ships"])

    outcome = service.checkpoint_sync(turns(4))

    assert outcome["skipped"] == "too many facts lost"
    assert len(facts_of(service)) == 9


def test_no_answer_leaves_everything_alone(service):
    service._add_memory_impl("fact", "Name is Shackles")
    service.local_ai_service.answer = None

    outcome = service.checkpoint_sync(turns(4))

    assert outcome["skipped"] == "no usable answer"
    assert facts_of(service) == ["Name is Shackles"]


def test_nothing_new_makes_no_call(service):
    outcome = service.checkpoint_sync([])

    assert outcome["skipped"] == "nothing new"
    assert service.local_ai_service.support_calls == []


def test_a_short_session_is_not_worth_a_call_at_its_end(service):
    service.local_ai_service.answer = answer(["Name is Shackles"])

    outcome = service.checkpoint_sync(turns(pm.MIN_USER_TURNS - 1), final=True)

    assert outcome["skipped"].endswith("user turns")
    assert service.local_ai_service.support_calls == []


def test_the_condensed_summary_rides_along(service):
    service.local_ai_service.answer = answer([])

    service.checkpoint_sync(turns(4), conversation_summary="Earlier: a long mining run.", final=True)

    assert "EARLIER IN THIS SESSION, CONDENSED:\nEarlier: a long mining run." in \
        service.local_ai_service.support_calls[0]


# ── episodes ───────────────────────────────────────────────────────


def test_the_episode_is_written_once_per_session_and_continued(service):
    service.local_ai_service.answer = answer([], {"happened": "Mined on Daymar.", "memorable": "", "open": ""})
    service.checkpoint_sync(turns(4))
    service.local_ai_service.answer = answer([], {
        "happened": "Mined on Daymar, then took a bounty.", "memorable": "A Cutlass ambush.",
        "open": "The bounty is not started.",
    })
    service.checkpoint_sync(turns(4))

    episodes = [e for e in service.get_all() if e.entry_type == "episode"]
    assert len(episodes) == 1
    assert episodes[0].content == "Mined on Daymar, then took a bounty. A Cutlass ambush. Open: The bounty is not started."
    assert "EPISODE SO FAR:\nMined on Daymar." in service.local_ai_service.support_calls[1]


def test_a_final_checkpoint_starts_a_new_session(service):
    service.local_ai_service.answer = answer([], {"happened": "Mined on Daymar.", "memorable": "Nearly lost the ship.", "open": ""})
    first = service.session_id

    service.checkpoint_sync(turns(4), final=True)
    service.checkpoint_sync(turns(4), final=True)

    assert service.session_id != first
    assert len([e for e in service.get_all() if e.entry_type == "episode"]) == 2


def test_a_session_with_nothing_memorable_and_nothing_open_leaves_no_episode(service):
    service.local_ai_service.answer = answer([], {"happened": "Started the ship and flew to New Babbage.", "memorable": "", "open": ""})

    service.checkpoint_sync(turns(4))               # mid-session: kept for the next checkpoint
    assert len([e for e in service.get_all() if e.entry_type == "episode"]) == 1

    service.checkpoint_sync(turns(4), final=True)   # end: a flight log is not an episode
    assert [e for e in service.get_all() if e.entry_type == "episode"] == []


def test_an_open_thread_alone_is_worth_an_episode(service):
    service.local_ai_service.answer = answer([], {"happened": "A few commands.", "memorable": "", "open": "Bounty on Kessler not started."})

    service.checkpoint_sync(turns(4), final=True)

    assert [e.content for e in service.get_all() if e.entry_type == "episode"] == \
        ["A few commands. Open: Bounty on Kessler not started."]


def test_an_empty_episode_is_not_stored(service):
    service.local_ai_service.answer = answer(["Name is Shackles"])

    service.checkpoint_sync(turns(4), final=True)

    assert [e for e in service.get_all() if e.entry_type == "episode"] == []


def test_only_five_episodes_are_kept(service):
    for i in range(8):
        service._add_memory_impl("episode", f"Session number {i} was about something.", session_id=f"s{i}")

    assert len([e for e in service.get_all() if e.entry_type == "episode"]) == pm.MAX_EPISODES


def test_tidy_only_rewrites_facts_and_leaves_the_episode(service):
    service._add_memory_impl("fact", "Name is Sam")
    service._add_memory_impl("fact", "User's name is Sam")
    service._add_memory_impl("episode", "Yesterday's run.", session_id="old")
    service.local_ai_service.answer = answer(["Name is Sam"])

    outcome = asyncio.run(service.consolidate())

    assert outcome == {"before": 2, "after": 1, "changed": True, "episode": "", "skipped": ""}
    assert facts_of(service) == ["Name is Sam"]
    assert [e.content for e in service.get_all() if e.entry_type == "episode"] == ["Yesterday's run."]


# ── the block ──────────────────────────────────────────────────────


def test_the_block_holds_every_fact_and_the_recent_episodes_with_age(service, monkeypatch):
    now = time.time()
    service._add_memory_impl("fact", "Owns a Cutlass Black")
    service._add_memory_impl("fact", "Friend is named Marcus")
    service._add_memory_impl("episode", "Mining with Marcus.", session_id="a")
    service._add_memory_impl("episode", "Took a bounty. Open: not started.", session_id="b")
    with service._lock:
        service._db.execute("UPDATE memory_entries SET created_at = ? WHERE session_id = 'a'", (now - 5 * 86400,))
        service._db.execute("UPDATE memory_entries SET created_at = ? WHERE session_id = 'b'", (now - 1 * 86400,))
        service._db.commit()
    service._block = None

    block = service.memory_block()

    assert block.startswith("# MEMORY")
    assert "- Owns a Cutlass Black" in block and "- Friend is named Marcus" in block
    assert block.index("5 days ago: Mining with Marcus.") < block.index("yesterday: Took a bounty.")
    assert "Only the last one is current" in block
    assert service.block_stats() == (2, 2)


def test_the_current_session_and_old_episodes_stay_out_of_the_block(service):
    now = time.time()
    service._add_memory_impl("episode", "This very session.")  # current session_id
    service._add_memory_impl("episode", "Long ago.", session_id="old")
    with service._lock:
        service._db.execute(
            "UPDATE memory_entries SET created_at = ? WHERE session_id = 'old'",
            (now - (pm.EPISODE_MAX_AGE_DAYS + 1) * 86400,),
        )
        service._db.commit()
    service._block = None

    assert service.memory_block() == ""


def test_old_session_summaries_are_read_as_episodes(service):
    service._add_memory_impl("session_summary", "From the 3.2.2 days.", session_id="old")

    assert "earlier today: From the 3.2.2 days." in service.memory_block()


def test_the_block_is_rebuilt_after_a_write(service):
    assert service.memory_block() == ""
    service._add_memory_impl("fact", "Owns a Cutlass Black")
    assert "Owns a Cutlass Black" in service.memory_block()


def test_the_prompt_lists_the_most_recently_updated_facts_first(service, monkeypatch):
    monkeypatch.setattr(pm, "FACTS_IN_PROMPT", 2)
    for i in range(3):
        service._add_memory_impl("fact", f"Fact number {i}")
        time.sleep(0.01)

    block = service.memory_block()

    assert "Fact number 2" in block and "Fact number 1" in block and "Fact number 0" not in block


def test_age_labels():
    now = 10 * 86400.0
    assert age_label(now - 3600, now) == "earlier today"
    assert age_label(now - 86400, now) == "yesterday"
    assert age_label(now - 5 * 86400, now) == "5 days ago"
    assert age_label(now - 21 * 86400 + 100, now) == "2 weeks ago"


# ── the fact cap ───────────────────────────────────────────────────


def test_the_fact_cap_drops_the_stalest(service, monkeypatch):
    monkeypatch.setattr(pm, "MAX_FACTS", 3)
    for i in range(5):
        service._add_memory_impl("fact", f"Fact number {i}")
        time.sleep(0.01)

    service._enforce_fact_cap()

    kept = [e.content for e in service.get_all(entry_type="fact")]
    assert len(kept) == 3
    assert "Fact number 0" not in kept and "Fact number 1" not in kept

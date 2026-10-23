"""Persistent memory: the fact filter, checkpoints, episodes, open entries
and the MEMORY block.

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
from services.persistent_memory import PersistentMemoryService


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


def answer(facts, episode=None, opened=(), closed=()):
    return json.dumps({
        "facts": [{"kind": "possession", "text": f} for f in facts],
        "opened": list(opened),
        "closed": [{"entry": e, "outcome": o} for e, o in closed],
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
    assert service.block_stats() == (2, 0, 2)


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


# ── open entries ───────────────────────────────────────────────────


def open_of(svc):
    return sorted(e.content for e in svc.get_all(entry_type="open"))


def done_of(svc):
    return sorted(e.content for e in svc.get_all(entry_type="done"))


def age(svc, content, days, column="updated_at"):
    with svc._lock:
        svc._db.execute(
            f"UPDATE memory_entries SET {column} = ? WHERE content = ?",
            (time.time() - days * 86400, content),
        )
        svc._db.commit()
    svc._block = None


def test_tracking_the_same_thing_twice_keeps_one_entry(service):
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")

    assert open_of(service) == ["Accepted a cargo mission to Lorville"]


def test_an_open_entry_never_merges_into_a_fact(service):
    service._add_memory_impl("fact", "Wants to buy an Idris")
    service._add_memory_impl("open", "Wants to buy an Idris")

    assert facts_of(service) == ["Wants to buy an Idris"]
    assert open_of(service) == ["Wants to buy an Idris"]


@pytest.mark.parametrize("description", [
    "Accepted a cargo mission to Lorville.",        # its own words, a period added
    "accepted a cargo mission to lorville",         # another case
    "cargo mission to Lorville",                    # part of it
])
def test_closing_finds_the_entry_in_the_models_words(service, description):
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")
    service._add_memory_impl("open", "Plans to mine on Daymar on Saturday")

    closed = service._close_open_impl(description, "Delivered the cargo to Lorville.")

    assert closed.content == "Delivered the cargo to Lorville."
    assert open_of(service) == ["Plans to mine on Daymar on Saturday"]
    assert done_of(service) == ["Delivered the cargo to Lorville."]


def test_closing_something_never_tracked_closes_nothing(service):
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")

    assert service._close_open_impl("Bounty on Kessler", "Killed Kessler.") is None
    assert open_of(service) == ["Accepted a cargo mission to Lorville"]


def test_a_description_that_fits_two_entries_closes_neither_by_guessing(service):
    service._add_memory_impl("open", "Cargo mission to Lorville")
    service._add_memory_impl("open", "Cargo mission to Area18")

    assert service._close_open_impl("cargo mission", "Done.") is None
    assert len(open_of(service)) == 2


def test_closing_without_an_outcome_keeps_the_entry_text(service):
    service._add_memory_impl("open", "Promised to help Marcus with his hauling run")

    service._close_open_impl("Promised to help Marcus with his hauling run")

    assert done_of(service) == ["Promised to help Marcus with his hauling run"]


def test_the_block_shows_open_and_recently_finished(service):
    service._add_memory_impl("open", "Accepted a bounty on Kessler")
    service._add_memory_impl("open", "Cargo mission to Lorville")
    service._close_open_impl("Cargo mission to Lorville", "Delivered the cargo to Lorville.")

    block = service.memory_block()

    assert "- Accepted a bounty on Kessler (from earlier today)" in block
    assert "earlier today: Delivered the cargo to Lorville." in block
    assert block.index("Open, taken on") < block.index("Recently finished")
    assert service.block_stats() == (0, 1, 0)


def test_finished_entries_leave_the_block_after_a_while(service):
    service._add_memory_impl("done", "Delivered the cargo to Lorville.")
    age(service, "Delivered the cargo to Lorville.", pm.DONE_MAX_AGE_DAYS + 1)

    assert service.memory_block() == ""


def test_an_open_entry_untouched_too_long_is_dropped_on_the_next_write(service):
    service._add_memory_impl("open", "Plans to visit Pyro someday")
    age(service, "Plans to visit Pyro someday", pm.OPEN_MAX_AGE_DAYS + 1)

    service._add_memory_impl("open", "Accepted a bounty on Kessler")

    assert open_of(service) == ["Accepted a bounty on Kessler"]


def test_the_open_cap_drops_the_stalest(service, monkeypatch):
    monkeypatch.setattr(pm, "MAX_OPEN", 2)
    for i in range(3):
        service._add_memory_impl("open", f"Open thing number {i}")
        time.sleep(0.01)

    assert open_of(service) == ["Open thing number 1", "Open thing number 2"]


def test_a_checkpoint_sees_the_open_list_and_opens_and_closes(service):
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")
    service.local_ai_service.answer = answer(
        [],
        opened=["Accepted a bounty on Kessler"],
        closed=[("Accepted a cargo mission to Lorville", "Delivered the cargo to Lorville.")],
    )

    outcome = service.checkpoint_sync(turns(3) + [
        {"role": "user", "content": "Fracht in Lorville abgeliefert. Und ich nehm das Kopfgeld auf Kessler."},
    ])

    assert "OPEN:\n- Accepted a cargo mission to Lorville" in service.local_ai_service.support_calls[0]
    assert open_of(service) == ["Accepted a bounty on Kessler"]
    assert done_of(service) == ["Delivered the cargo to Lorville."]
    assert outcome["opened"] == ["Accepted a bounty on Kessler"]
    assert outcome["closed"] == ["Delivered the cargo to Lorville."]


def test_a_checkpoint_answer_without_open_changes_leaves_the_list_alone(service):
    """An older prompt or a model that drops the keys must not close anything."""
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")
    service.local_ai_service.answer = json.dumps({"facts": [], "episode": {"happened": "", "memorable": ""}})

    service.checkpoint_sync(turns(4))

    assert open_of(service) == ["Accepted a cargo mission to Lorville"]


def test_tidying_facts_never_touches_open_entries(service):
    service._add_memory_impl("fact", "Name is Sam")
    service._add_memory_impl("open", "Accepted a cargo mission to Lorville")
    service.local_ai_service.answer = answer(
        ["Name is Sam"], closed=[("Accepted a cargo mission to Lorville", "Done.")]
    )

    asyncio.run(service.consolidate())

    assert open_of(service) == ["Accepted a cargo mission to Lorville"]


def unit(*xs):
    n = sum(x * x for x in xs) ** 0.5
    return [x / n for x in xs]


@pytest.mark.parametrize("query_vector, closes", [
    (unit(0.8, 0.2, 0.0), "Accepted a cargo mission to Lorville"),  # clearly the cargo one
    (unit(0.5, 0.5, 0.2), None),                                    # as close to both
    (unit(0.2, 0.2, 1.0), None),                                    # close to neither
])
def test_closing_by_meaning_needs_a_clear_winner(service, query_vector, closes):
    vectors = {
        "Accepted a cargo mission to Lorville": unit(1.0, 0.0, 0.0),
        "Accepted a bounty on Kessler": unit(0.0, 1.0, 0.0),
        "the delivery": query_vector,
        "Done.": unit(0.0, 0.0, 1.0),
    }
    service.local_ai_service.embed = lambda texts: [vectors[t] for t in texts]
    for text in ("Accepted a cargo mission to Lorville", "Accepted a bounty on Kessler"):
        service._add_memory_impl("open", text)

    closed = service._close_open_impl("the delivery", "Done.")

    still_open = {"Accepted a cargo mission to Lorville", "Accepted a bounty on Kessler"} - {closes}
    assert (closed is not None) == (closes is not None)
    assert open_of(service) == sorted(still_open)


def test_a_checkpoint_never_closes_an_entry_the_session_did_not_name(service):
    """Small models closed "swap the quantum drive" in a session about
    selling a ship."""
    service._add_memory_impl("open", "Wants to swap the quantum drive of the Cutlass")
    service.local_ai_service.answer = answer(
        [], closed=[("Wants to swap the quantum drive of the Cutlass", "Dropped, the ship was sold.")]
    )

    outcome = service.checkpoint_sync(turns(3) + [
        {"role": "user", "content": "Ich hab die Aurora verkauft und mir eine Freelancer geholt."},
    ])

    assert open_of(service) == ["Wants to swap the quantum drive of the Cutlass"]
    assert outcome["closed"] == []

"""The transcript correction: fix the names, leave the sentence alone."""

from types import SimpleNamespace

from services.audio.vocabulary import (
    Vocabulary,
    format_entry,
    parse_entry,
    spoken_names,
)

SC = Vocabulary(["Hurston", "Crusader", "Port Olisar", "Gladius", "Aurora", "ArcCorp", "Computer"])


def test_misspelled_names_are_corrected():
    assert SC.correct("fly me to Hurstin please") == "fly me to Hurston please"
    assert SC.correct("the cruzader is docked at port olisa") == "the Crusader is docked at Port Olisar"
    assert SC.correct("Arccorp, now.") == "ArcCorp, now."


def test_exact_words_keep_the_entry_spelling():
    assert SC.correct("hurston station") == "Hurston station"


def test_ordinary_words_stay():
    text = "please complete the mission and open the map"
    assert SC.correct(text) == text
    # "Houston" is two edits from "Hurston" but starts with the same letter;
    # that one is accepted on purpose, players do not talk about Texas.
    assert SC.correct("Houston") == "Hurston"
    # "Aurora" vs "Europa": too far.
    assert SC.correct("Europa") == "Europa"


def test_punctuation_and_case_survive():
    assert SC.correct("Gladios? Yes, the Gladios!") == "Gladius? Yes, the Gladius!"


def test_short_entries_are_ignored():
    v = Vocabulary(["Io", "Ava"])
    assert v.entries == ["Ava"]
    assert v.correct("I am here") == "I am here"


def test_empty_vocabulary_is_a_no_op():
    assert Vocabulary([]).correct("anything at all") == "anything at all"


def _config():
    wingman = SimpleNamespace(
        name="Computer",
        disabled=False,
        commands=[
            SimpleNamespace(name="ToggleLandingGear", instant_activation=["Flight Ready", "Deploy gear"]),
        ],
        prompts=SimpleNamespace(system_prompt="", backstory="You serve on the Carrack near Crusader."),
    )
    return SimpleNamespace(wingmen={"Computer": wingman})


def test_spoken_names_are_the_runtime_vocabulary():
    assert spoken_names(_config()) == ["Computer", "Flight Ready", "Deploy gear"]


def test_mapping_entries_replace_exactly():
    v = Vocabulary(["Jump down=Jumptown", "Houston -> Hurston", "Gladius"])
    assert set(v.entries) == {"Jumptown", "Hurston", "Gladius"}
    assert v.correct("go to jump down now") == "go to Jumptown now"
    assert v.correct("Houston, we have a problem") == "Hurston, we have a problem"
    # the correct side of a mapping is also fuzzy-matched on its own
    assert v.correct("jumptowm") == "Jumptown"


def test_parse_and_format_entries():
    assert parse_entry("Houston=Hurston") == ("Hurston", "Houston")
    assert parse_entry("  Hurston ") == ("Hurston", None)
    assert format_entry("Hurston", "Houston") == "Houston=Hurston"
    assert format_entry("Hurston", "hurston") == "Hurston"


def test_common_words_are_never_fuzzy_corrected():
    v = Vocabulary(["Para", "Stanton", "Port Olisar"])
    # "part", "park", "pare" are one edit from "Para" and stay
    assert v.correct("part of the park, pare it down") == "part of the park, pare it down"
    # "Stanten" is nobody's word and is corrected
    assert v.correct("in the Stanten system") == "in the Stanton system"


def test_short_entries_match_exactly_only():
    """"dir" is one edit from "Adir" and "dazu" one from "Dawu"; a name of
    four letters is taken only when it is heard as it is."""
    v = Vocabulary(["Adir", "Dawu", "Hurston"])
    assert v.correct("Wie geht's dir? Was meinst du dazu?") == "Wie geht's dir? Was meinst du dazu?"
    assert v.correct("fly to adir") == "fly to Adir"
    assert v.correct("in Houston") == "in Hurston"


def test_a_pair_overrides_the_protection():
    v = Vocabulary(["park=Para"])
    assert v.correct("fly to park") == "fly to Para"


def test_fix_memories_rewrites_the_wrong_form():
    from services.audio.vocabulary_tools import fix_memories

    class Memory:
        def __init__(self):
            self.entries = [
                SimpleNamespace(id=1, content="User lives near Houston station."),
                SimpleNamespace(id=2, content="User likes the Gladius."),
            ]
            self.updates = []

        def get_all(self):
            return self.entries

        def update_memory_sync(self, entry_id, content):
            self.updates.append((entry_id, content))

    memory = Memory()
    assert fix_memories(memory, "Hurston", "Houston") == 1
    assert memory.updates == [(1, "User lives near Hurston station.")]
    assert fix_memories(memory, "Hurston", "hurston") == 0
    assert fix_memories(None, "Hurston", "Houston") == 0


def test_splits_and_merges_are_corrected_without_eating_neighbours():
    v = Vocabulary(["MicroTech", "New Babbage", "Agricultural Supplies", "Medical Supplies"])
    assert v.correct("take me to micro tech") == "take me to MicroTech"
    assert v.correct("fly to new babage on microtech") == "fly to New Babbage on MicroTech"
    assert (
        v.correct("buy agricultural supplies and medical supplies")
        == "buy Agricultural Supplies and Medical Supplies"
    )


def test_exact_only_entries_fix_casing_and_nothing_else():
    v = Vocabulary(['"Crusader"', "Hurston"])
    assert v.correct("we are near crusader") == "we are near Crusader"
    assert v.correct("the crusade begins") == "the crusade begins"
    assert parse_entry('"Crusader"') == ("Crusader", "Crusader")
    assert parse_entry("“Crusader”") == ("Crusader", "Crusader")


def test_spelled_out_letters_become_the_name():
    from services.audio.vocabulary import join_spelled

    v = Vocabulary(["ATC", "Hurston"])
    assert v.correct("It's called A T C") == "It's called ATC"
    assert v.correct("the name is h u r s t o n") == "the name is Hurston"
    assert v.correct("it is spelled H-U-R-S-T-O-N") == "it is spelled Hurston"
    # letters that make no listed word stay letters
    assert v.correct("go to plan b") == "go to plan b"
    assert v.correct("option a or b") == "option a or b"
    assert join_spelled("A T C") == "ATC"
    assert join_spelled("H-u-r-s-t-o-n please") == "Hurston please"


def test_preset_overrides_are_a_diff_against_the_bundle():
    from services.audio.vocabulary import apply_override, diff_override

    bundled = ["Hurston", "Crusader", "Buckets"]
    wanted = ["Hurston", "Crusader", "Jumptown"]
    added, removed = diff_override(bundled, wanted)
    assert added == ["Jumptown"] and removed == ["Buckets"]
    effective = apply_override(bundled, SimpleNamespace(added=added, removed=removed))
    assert effective == ["Hurston", "Crusader", "Jumptown"]
    # a later bundle update still lands, minus the user's removals
    assert apply_override(bundled + ["Orison"], SimpleNamespace(added=added, removed=removed)) == [
        "Hurston", "Crusader", "Orison", "Jumptown"
    ]
    assert diff_override(bundled, bundled) == ([], [])

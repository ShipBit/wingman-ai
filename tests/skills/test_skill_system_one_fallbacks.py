"""Every skill that uses System One must still work without it.

The rule these pin down: a skill may add System One, it may not delete the
path it replaces. So each test runs the skill's own resolution code with the
feature switched off and checks it behaves exactly as it did before — which
for three of the four means "exact match only", and for Spotify also means
the tool schema keeps its enum.
"""

import asyncio
import sys
import threading
from os import path
from types import SimpleNamespace

from tests.support import REPO_ROOT


def _wingman(enabled: bool):
    """A wingman whose System One is on or off, without a network in sight."""
    from services.jev_gate import JevGate
    from wingmen.facade import SkillSystemOne

    settings = SimpleNamespace(
        system_one=SimpleNamespace(enabled=enabled),
        wingman_pro=SimpleNamespace(base_url="https://example.invalid"),
    )
    gate = JevGate("Test", settings=settings)
    # A credential on purpose: "off" has to mean off even when a call could
    # have been made.
    gate.client.api_key = "not-used"
    return SimpleNamespace(system_one=SkillSystemOne(gate))


# ── UEX name matching ───────────────────────────────────────────────


def _uex_llm(enabled: bool):
    sys.path.insert(0, path.join(REPO_ROOT, "skills", "uexcorp"))
    from uexcorp.api.llm import Llm

    debug = SimpleNamespace(write=lambda *a, **k: None)
    llm = Llm.__new__(Llm)
    llm._Llm__helper = SimpleNamespace(
        get_handler_debug=lambda: debug,
        get_handler_config=lambda: SimpleNamespace(get_wingman=lambda: _wingman(enabled)),
        add_context=lambda *a: None,
    )
    llm._Llm__cache_search = {}
    llm._Llm__name_vectors = {}
    llm._Llm__embedding_lock = threading.Lock()
    return llm


def test_uex_still_finds_an_exact_name_with_system_one_off():
    llm = _uex_llm(False)
    match, options = asyncio.run(llm.find_closest_match("Carrack", ["Carrack", "Cutlass Black"]))
    assert match == "Carrack"
    assert options is None


def test_uex_refuses_to_ask_about_an_unbounded_shortlist():
    """The substring pass after difflib has no limit; a choice takes 255, and
    a list that long is not a disambiguation anyway."""
    from uexcorp.api.llm import Llm

    llm = _uex_llm(True)
    huge = [f"Ship {i}" for i in range(Llm.SYSTEM_ONE_MAX_OPTIONS + 5)]
    # (None, None): System One was not asked, the main model decides as before
    assert asyncio.run(llm._Llm__system_one_match("Ship", huge)) == (None, None)


# ── HUD panel titles ────────────────────────────────────────────────


def _resolve_panel(enabled: bool, asked: str, titles: list[str]):
    from services.hud_tools import resolve_title

    return asyncio.run(resolve_title(_wingman(enabled).system_one, asked, titles))


def test_hud_gives_up_on_a_rephrased_title_with_system_one_off():
    """The caller then reports 'not found' and lists the panels."""
    assert _resolve_panel(False, "the mining panel", ["Mining Yield"]) is None


# ── Spotify playlists ───────────────────────────────────────────────


def _spotify(enabled: bool):
    from skills.spotify.main import Spotify

    skill = Spotify.__new__(Spotify)
    skill.wingman = _wingman(enabled)
    return skill


PLAYLISTS = [{"name": "Late Night Coding", "uri": "a"}, {"name": "Road Trip", "uri": "b"}]


def test_spotify_gives_up_on_a_paraphrase_with_system_one_off():
    skill = _spotify(False)
    assert asyncio.run(skill._match_playlist("my coding playlist", PLAYLISTS)) is None


def test_spotify_keeps_the_enum_when_system_one_is_off():
    """The enum is what makes the exact match work. Taking it away would
    break the skill for anyone who switched the feature off."""
    skill = _spotify(False)
    skill.get_user_playlists = lambda: PLAYLISTS
    parameter = skill._playlist_parameter()
    assert parameter["enum"] == ["Late Night Coding", "Road Trip"]


def test_spotify_drops_the_enum_only_when_system_one_can_resolve_names():
    skill = _spotify(True)
    skill.get_user_playlists = lambda: PLAYLISTS
    assert "enum" not in skill._playlist_parameter()


# ── MSFS command shortlist ──────────────────────────────────────────


def test_msfs_hands_over_the_whole_shortlist_with_system_one_off():
    from skills.msfs2020_control.main import Msfs2020Control

    skill = Msfs2020Control.__new__(Msfs2020Control)
    skill.wingman = _wingman(False)
    matches = [
        {"name": "AP_MASTER", "type": "event", "description": "Toggle autopilot"},
        {"name": "AUTOPILOT_ON", "type": "event", "description": "Turn autopilot on"},
    ]
    assert asyncio.run(skill._pick_one_command("turn on autopilot", matches)) is None

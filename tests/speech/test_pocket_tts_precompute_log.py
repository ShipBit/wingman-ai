"""The automatic voice pass after a model load says what it did in the log.

It only clones voices of the spoken language, and on a plain restart only
clones that are outdated. Without a line of its own a log could not tell a
pass that ran from one that never started.
"""

import asyncio
from types import SimpleNamespace

from wingman_core import WingmanCore


class _Pocket:
    model_id = "german"

    def __init__(self, spoken: list[str], everything: list[str], failed: int = 0):
        self.settings = SimpleNamespace(enable=True, run_locally=True)
        self.model = object()
        self._precompute_running = False
        self._spoken = spoken
        self._everything = everything
        self._failed = failed

    def list_custom_voices_needing_precompute(
        self, only_stale=False, spoken_language_only=False
    ):
        return self._spoken if spoken_language_only else self._everything

    def precompute_custom_voices(self, progress_cb=None, only_stale=False, spoken_language_only=False):
        total = len(self._spoken)
        return {"total": total, "succeeded": total - self._failed, "failed": self._failed}


def _run(pocket: _Pocket) -> list[str]:
    lines = []

    async def set_core_state(*_args, **_kwargs):
        pass

    core = SimpleNamespace(
        pocket_tts=pocket,
        set_core_state=set_core_state,
        printr=SimpleNamespace(print=lambda text, **_kwargs: lines.append(text)),
    )
    core._log_precompute = lambda *args: WingmanCore._log_precompute(core, *args)
    asyncio.run(WingmanCore._precompute_with_indicator(core, only_stale=True))
    return lines


def test_the_pass_logs_what_it_cloned_and_what_it_left_for_later():
    pocket = _Pocket(spoken=["de-ava", "de-boris"], everything=["de-ava", "de-boris", "en-tom"])
    assert _run(pocket) == [
        "PocketTTS voices for 'german': 2 prepared, 1 left for when they are used"
        " (other languages or never cloned)."
    ]


def test_a_pass_with_nothing_to_do_still_logs():
    assert _run(_Pocket(spoken=[], everything=[])) == ["PocketTTS voices for 'german': 0 prepared."]


def test_failed_clones_are_counted():
    pocket = _Pocket(spoken=["de-ava", "de-boris"], everything=["de-ava", "de-boris"], failed=1)
    assert _run(pocket) == ["PocketTTS voices for 'german': 1 prepared, 1 failed."]

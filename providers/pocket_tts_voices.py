"""Voices Wingman ships as recordings, for languages Kyutai has few voices in.

Kyutai recorded one native speaker per language other than English; every
other built-in voice was recorded in English. The German model with such a
voice starts many pieces at full loudness on the first sample, heard as a
click, and speaks with an English accent (Eponine: 8 of 12 pieces, clones of
German readers: 0 or 1 of 12, measured 2026-09-23). So Wingman ships short
recordings of native speakers (public domain or CC0, credited in README.md and
in the list next to them) and clones them like any voice of the user's own.

The recordings live in templates/pocket_tts/voices/ with a list, voices.tsv:
file, name, language, gender, credit. For the spoken language they are copied
into the custom voices folder, where Pocket TTS clones them for the active
model, notices when a clone is outdated, and the user can delete them. A
record in that folder (.wingman_voices.json) keeps a deleted voice deleted
and lets a better recording in a later Wingman replace one the user kept
unchanged.
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from typing import Optional

VOICES_DIR = os.path.join("templates", "pocket_tts", "voices")
RECORD_FILE = ".wingman_voices.json"


@dataclass(frozen=True)
class BundledVoice:
    file: str
    """File name in VOICES_DIR, e.g. "de-claudia.flac"; its stem is the voice id."""
    name: str
    language: str
    gender: str
    credit: str

    @property
    def id(self) -> str:
        return os.path.splitext(self.file)[0]


def load_bundled_voices(app_root: Optional[str]) -> list[BundledVoice]:
    """Every voice in the list whose recording is there."""
    if not app_root:
        return []
    folder = os.path.join(app_root, VOICES_DIR)
    listing = os.path.join(folder, "voices.tsv")
    if not os.path.isfile(listing):
        return []
    voices = []
    with open(listing, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cells = [c.strip() for c in line.rstrip("\n").split("\t")]
            if len(cells) < 5 or not os.path.isfile(os.path.join(folder, cells[0])):
                continue
            voices.append(BundledVoice(*cells[:5]))
    return voices


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_record(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def install_bundled_voices(app_root: Optional[str], voices_dir: str, language: str) -> list[str]:
    """Copy the recordings for ``language`` into ``voices_dir``. Returns the
    ids of the voices copied now.

    - never copied before: copied, and noted with its checksum
    - copied before, then deleted by the user: left deleted
    - copied before and unchanged, but Wingman ships a new recording: replaced
    - a file of the user's own under the same name: never touched
    """
    voices = [v for v in load_bundled_voices(app_root) if v.language == language]
    if not voices:
        return []
    os.makedirs(voices_dir, exist_ok=True)
    record_path = os.path.join(voices_dir, RECORD_FILE)
    record = _read_record(record_path)
    copied = []
    for voice in voices:
        source = os.path.join(app_root, VOICES_DIR, voice.file)
        dest = os.path.join(voices_dir, voice.file)
        wanted = _sha256(source)
        noted = record.get(voice.file)
        if noted is None:
            if os.path.exists(dest):
                continue  # the user's own file
        elif not os.path.exists(dest) or noted == wanted or _sha256(dest) != noted:
            continue  # deleted, current, or changed by the user
        shutil.copyfile(source, dest)
        record[voice.file] = wanted
        copied.append(voice.id)
    if copied:
        tmp = record_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True)
        os.replace(tmp, record_path)
    return copied

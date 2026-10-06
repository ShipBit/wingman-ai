"""Recordings Wingman ships: copied once per language, a deletion sticks."""

import os

from providers.pocket_tts_voices import (
    RECORD_FILE,
    VOICES_DIR,
    install_bundled_voices,
    load_bundled_voices,
)

from tests.support import REPO_ROOT as ROOT


def make_root(tmp_path, recordings):
    folder = tmp_path / "app" / VOICES_DIR
    folder.mkdir(parents=True)
    lines = ["# file\tname\tlanguage\tgender\tcredit"]
    for file, language, content in recordings:
        (folder / file).write_bytes(content)
        lines.append(f"{file}\t{file.split('.')[0].title()}\t{language}\tFemale\tsomeone")
    lines.append("missing.flac\tMissing\tde\tMale\tnobody")
    (folder / "voices.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(tmp_path / "app")


def test_only_the_spoken_language_is_copied(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a"), ("fr-lea.flac", "fr", b"b")])
    voices = tmp_path / "voices"
    assert install_bundled_voices(root, str(voices), "de") == ["de-anna"]
    assert (voices / "de-anna.flac").read_bytes() == b"a"
    assert not (voices / "fr-lea.flac").exists()
    assert install_bundled_voices(root, str(voices), "de") == []


def test_a_deleted_voice_stays_deleted(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a")])
    voices = tmp_path / "voices"
    install_bundled_voices(root, str(voices), "de")
    (voices / "de-anna.flac").unlink()
    assert install_bundled_voices(root, str(voices), "de") == []
    assert not (voices / "de-anna.flac").exists()


def test_a_new_recording_replaces_an_unchanged_copy_only(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a"), ("de-ben.flac", "de", b"b")])
    voices = tmp_path / "voices"
    install_bundled_voices(root, str(voices), "de")
    (voices / "de-ben.flac").write_bytes(b"the user's own take")
    bundled = tmp_path / "app" / VOICES_DIR
    (bundled / "de-anna.flac").write_bytes(b"a2")
    (bundled / "de-ben.flac").write_bytes(b"b2")
    assert install_bundled_voices(root, str(voices), "de") == ["de-anna"]
    assert (voices / "de-anna.flac").read_bytes() == b"a2"
    assert (voices / "de-ben.flac").read_bytes() == b"the user's own take"


def test_a_file_of_the_users_own_is_never_touched(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a")])
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "de-anna.flac").write_bytes(b"mine")
    assert install_bundled_voices(root, str(voices), "de") == []
    assert (voices / "de-anna.flac").read_bytes() == b"mine"
    assert not (voices / RECORD_FILE).exists()


def test_the_shipped_list_names_only_recordings_that_exist():
    for voice in load_bundled_voices(ROOT):
        assert os.path.isfile(os.path.join(ROOT, VOICES_DIR, voice.file))
        assert voice.language and voice.name and voice.credit
        assert voice.gender in ("Male", "Female")
        assert "." not in voice.id  # a dot would read as a model tag


from providers.pocket_tts_voices import BundledVoice, read_voice_details, write_voice_details


def test_a_text_file_describes_a_voice(tmp_path):
    path = tmp_path / "Mara.txt"
    path.write_text("ruhig, gemächlich\nGeschlecht: weiblich\nname: Mara\n", encoding="utf-8")
    details = read_voice_details(str(path))
    assert (details.description, details.gender, details.name) == ("ruhig, gemächlich", "Female", "Mara")


def test_just_a_line_is_the_description_and_nonsense_is_ignored(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("# my note\ntief und rau\ngender: robot\n", encoding="utf-8")
    details = read_voice_details(str(path))
    assert (details.description, details.gender, details.name) == ("tief und rau", None, None)
    assert read_voice_details(str(tmp_path / "missing.txt")).description is None


def test_shipped_voices_get_their_text_file_once(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a")])
    voices = tmp_path / "voices"
    install_bundled_voices(root, str(voices), "de")
    sidecar = voices / "de-anna.txt"
    assert read_voice_details(str(sidecar)).gender == "Female"
    sidecar.write_text("meine Notiz\n", encoding="utf-8")
    install_bundled_voices(root, str(voices), "de")
    assert sidecar.read_text(encoding="utf-8") == "meine Notiz\n"


def test_written_details_read_back(tmp_path):
    path = tmp_path / "v.txt"
    write_voice_details(str(path), BundledVoice("v.flac", "Vera", "de", "Female", "x", "hell, klar"))
    details = read_voice_details(str(path))
    assert (details.description, details.gender, details.name) == ("hell, klar", "Female", "Vera")


def test_a_new_description_replaces_an_unedited_text_file_only(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a"), ("de-ben.flac", "de", b"b")])
    voices = tmp_path / "voices"
    install_bundled_voices(root, str(voices), "de")
    (voices / "de-ben.txt").write_text("meine Notiz\n", encoding="utf-8")
    listing = tmp_path / "app" / VOICES_DIR / "voices.tsv"
    listing.write_text(listing.read_text(encoding="utf-8").replace("\tsomeone", "\tsomeone\tneu, klar"), encoding="utf-8")
    install_bundled_voices(root, str(voices), "de")
    assert read_voice_details(str(voices / "de-anna.txt")).description == "neu, klar"
    assert (voices / "de-ben.txt").read_text(encoding="utf-8") == "meine Notiz\n"


def test_a_deleted_text_file_stays_deleted(tmp_path):
    root = make_root(tmp_path, [("de-anna.flac", "de", b"a")])
    voices = tmp_path / "voices"
    install_bundled_voices(root, str(voices), "de")
    (voices / "de-anna.txt").unlink()
    install_bundled_voices(root, str(voices), "de")
    assert not (voices / "de-anna.txt").exists()

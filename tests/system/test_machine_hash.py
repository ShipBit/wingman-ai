"""GET /system/machine-hash: the same hash every time, never the machine id."""

import hashlib

from services import machine_hash as mh


def test_the_hash_is_stable_and_not_the_raw_id(tmp_path):
    raw = mh.machine_id(str(tmp_path))
    first = mh.machine_hash(str(tmp_path))

    assert first == mh.machine_hash(str(tmp_path))
    assert raw not in first
    assert first == hashlib.sha256((raw + "wingman-device-v1").encode()).hexdigest()


def test_without_a_readable_machine_id_a_stored_random_one_is_used(tmp_path, monkeypatch):
    for reader in ("_windows_machine_guid", "_macos_platform_uuid", "_linux_machine_id"):
        monkeypatch.setattr(mh, reader, lambda: None)

    first = mh.machine_hash(str(tmp_path))

    assert (tmp_path / mh.FALLBACK_FILE).exists()
    assert mh.machine_hash(str(tmp_path)) == first


def test_a_reader_that_fails_does_not_break_the_hash(tmp_path, monkeypatch):
    def broken():
        raise OSError("no registry here")

    monkeypatch.setattr(mh, "_windows_machine_guid", broken)
    monkeypatch.setattr(mh, "_macos_platform_uuid", lambda: None)
    monkeypatch.setattr(mh, "_linux_machine_id", lambda: "abc")

    assert mh.machine_hash(str(tmp_path)) == hashlib.sha256(b"abcwingman-device-v1").hexdigest()

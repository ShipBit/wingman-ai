"""Parakeet comes from our R2 mirror in four files: a broken connection goes
on where it stopped, a wrong file never gets its name, and the 3.2 GB of the
model before go once the new one works."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

import services.model_downloader as downloader_module
from services.model_downloader import ChecksumError, ModelDownloader
from services.stt_provider_manager import SttProviderManager
from tests.support import BODY, FlakyServer

SHA256 = hashlib.sha256(BODY).hexdigest()


@pytest.fixture
def downloader(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module.time, "sleep", lambda _s: None)
    return ModelDownloader(str(tmp_path))


def _download(downloader, **kwargs):
    return asyncio.run(
        downloader.download_file(url="https://example.invalid/m.onnx", category="m", filename="m.onnx", **kwargs)
    )


def test_a_broken_download_goes_on_where_it_stopped(downloader, monkeypatch, tmp_path):
    server = FlakyServer(cut=3000, breaks=3)
    monkeypatch.setattr(downloader_module.requests, "get", server.get)

    _download(downloader, size=len(BODY), sha256=SHA256)

    assert (tmp_path / "m" / "m.onnx").read_bytes() == BODY
    assert server.ranges == [None, "bytes=3000-", "bytes=6000-", "bytes=9000-"]


def test_a_file_with_the_wrong_checksum_is_not_kept(downloader, monkeypatch, tmp_path):
    monkeypatch.setattr(downloader_module.requests, "get", FlakyServer(cut=0, breaks=0).get)

    with pytest.raises(ChecksumError):
        _download(downloader, size=len(BODY), sha256="0" * 64)

    assert list((tmp_path / "m").iterdir()) == []


def test_a_file_of_another_size_is_downloaded_again(downloader, monkeypatch, tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "m.onnx").write_bytes(b"an older model")
    server = FlakyServer(cut=0, breaks=0)
    monkeypatch.setattr(downloader_module.requests, "get", server.get)

    _download(downloader, size=len(BODY), sha256=SHA256)

    assert (tmp_path / "m" / "m.onnx").read_bytes() == BODY
    assert server.ranges == [None]


def _manager(models_root):
    return SttProviderManager(None, None, SimpleNamespace(models_root=str(models_root)), None, ".")


def test_the_old_model_goes_once_the_new_one_works(tmp_path):
    old = tmp_path / "parakeet"
    old.mkdir()
    (old / "encoder-model.onnx.data").write_bytes(b"weights")

    _manager(tmp_path)._remove_old_parakeet()

    assert not old.exists()


def test_a_folder_without_the_old_model_stays(tmp_path):
    other = tmp_path / "parakeet"
    other.mkdir()
    (other / "notes.txt").write_text("mine")

    _manager(tmp_path)._remove_old_parakeet()

    assert (other / "notes.txt").exists()

"""A model download that breaks off goes on where it stopped. Starting over
at zero never got a 261 MB file through a connection that broke near the end
every time."""

from types import SimpleNamespace

import pytest

import services.local_model_manager as lmm
from services.local_model_manager import LocalModelManager
from tests.support import BODY, FlakyServer

@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalModelManager, "_get_models_dir", staticmethod(lambda: str(tmp_path)))
    monkeypatch.setattr(lmm.time, "sleep", lambda _s: None)
    return LocalModelManager(SimpleNamespace())


MODEL = {"repo": "test/repo", "filename": "embed.gguf"}


def test_a_broken_download_goes_on_where_it_stopped(manager, monkeypatch, tmp_path):
    server = FlakyServer(cut=3000, breaks=3)
    monkeypatch.setattr(lmm.requests, "get", server.get)
    assert manager._download_model(MODEL)
    assert (tmp_path / "embed.gguf").read_bytes() == BODY
    assert server.ranges == [None, "bytes=3000-", "bytes=6000-", "bytes=9000-"]


def test_it_gives_up_when_nothing_comes_any_more(manager, monkeypatch, tmp_path):
    server = FlakyServer(cut=0, breaks=100)
    monkeypatch.setattr(lmm.requests, "get", server.get)
    assert not manager._download_model(MODEL)
    assert len(server.ranges) == lmm.MAX_DOWNLOAD_ATTEMPTS
    assert not (tmp_path / "embed.gguf").exists()


def test_the_next_start_continues_the_part_file(manager, monkeypatch, tmp_path):
    (tmp_path / "embed.gguf.part").write_bytes(BODY[:5000])
    server = FlakyServer(cut=0, breaks=0)
    monkeypatch.setattr(lmm.requests, "get", server.get)
    assert manager._download_model(MODEL)
    assert server.ranges == ["bytes=5000-"]
    assert (tmp_path / "embed.gguf").read_bytes() == BODY

"""A mistyped server address for the support model must not stop Core from starting.

The client is built at startup. If the OpenAI client rejects the URL there, Core
dies before the UI is up, and the setting can only be fixed by editing the file.
"""

from types import SimpleNamespace

from providers.llama_cpp_remote import LlamaCppRemote


def _settings(support_host: str, embed_host: str = "http://127.0.0.1"):
    return SimpleNamespace(
        support_remote_host=support_host,
        support_remote_port=49152,
        embed_remote_host=embed_host,
        embed_remote_port=49153,
    )


def test_a_host_with_its_own_port_does_not_crash_startup():
    remote = LlamaCppRemote(_settings("http://192.168.1.50:1432"))

    assert remote.is_ready() is False
    assert remote.support(text="hello", system_prompt="sys").text is None


def test_the_other_server_still_gets_its_client():
    remote = LlamaCppRemote(_settings("http://192.168.1.50:1432"))

    assert remote._support_client is None
    assert remote._embed_client is not None


def test_correcting_the_address_brings_the_client_back():
    remote = LlamaCppRemote(_settings("http://192.168.1.50:1432"))
    remote.update_settings(_settings("http://192.168.1.50"))

    assert remote._support_client is not None


def test_a_mistyped_address_is_a_warning_not_an_error_report(monkeypatch):
    import providers.llama_cpp_remote as remote_module
    from api.enums import LogType

    colors = []
    monkeypatch.setattr(
        remote_module,
        "printr",
        SimpleNamespace(print=lambda text, color=None, **kw: colors.append(color)),
    )

    LlamaCppRemote(_settings("http://192.168.1.50:1432"))

    assert colors == [LogType.WARNING]

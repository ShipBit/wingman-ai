"""Run: PYTHONPATH=. venv/bin/python -m tests.test_local_ai_view"""
import asyncio
from wingmen.facade import SkillLocalAiView, SkillMemory


class _Resp:
    def __init__(self, text): self.text = text


class _FakeLocalAI:
    available = True
    async def support(self, text, **kw): return _Resp(f"gen:{text}")
    def support_sync(self, text, **kw): return _Resp(f"gens:{text}")
    async def summarize(self, text, **kw): return _Resp(f"sum:{text}")
    def summarize_sync(self, text, **kw): return _Resp(f"sums:{text}")
    async def embed(self, texts): return [[0.0]]
    def embed_sync(self, texts): return [[0.0]]
    async def remember_fact(self, content, **kw): return 1
    async def recall_memory(self, query, **kw): return ["x"]


class _FakeWingman:
    def __init__(self): self._la = _FakeLocalAI()
    local_ai_service = True
    @property
    def _local_ai_facade(self): return self._la


def test_localai_generate():
    la = SkillLocalAiView(_FakeLocalAI())
    out = asyncio.get_event_loop().run_until_complete(la.generate("hi"))
    assert out == "gen:hi", out
    assert la.generate_sync("hi") == "gens:hi"
    assert asyncio.get_event_loop().run_until_complete(la.summarize("t")) == "sum:t"
    assert la.available is True
    print("PASS: local_ai view generate/summarize")


def test_memory():
    mem = SkillMemory(_FakeLocalAI())
    out = asyncio.get_event_loop().run_until_complete(mem.remember("fact"))
    assert out == 1
    out2 = asyncio.get_event_loop().run_until_complete(mem.recall("q"))
    assert out2 == ["x"]
    print("PASS: memory remember/recall")


if __name__ == "__main__":
    test_localai_generate()
    test_memory()
    print("ALL OK")

"""Run: PYTHONPATH=. venv/bin/python -m tests.test_skill_tools"""
import asyncio
from wingmen.facade import SkillTools, ToolResult, ToolDescriptor


class _Skill:
    name = "Timer"


class _Manifest:
    display_name = "Weather MCP"


class _ManifestObj:
    def __init__(self, name, display):
        self.name = name; self.display_name = display; self.is_connected = True


class _ToolInfo:
    def __init__(self, n): self.prefixed_name = n


class _Mcp:
    _tool_to_server = {"get_weather": "weather"}
    _manifests = {"weather": _Manifest()}
    def get_connected_servers(self): return [_ManifestObj("weather", "Weather MCP")]
    def get_server_tools(self, name): return [_ToolInfo("get_weather")] if name == "weather" else []


class _W:
    tool_skills = {"set_timer": _Skill()}
    mcp_registry = _Mcp()
    def build_tools(self):
        return [
            {"function": {"name": "set_timer", "description": "d1", "parameters": {"type": "object"}}},
            {"function": {"name": "get_weather", "description": "d2", "parameters": {"type": "object"}}},
        ]
    async def execute_command_by_function_call(self, name, args):
        # Slot 3 is the owning Skill OBJECT in production (not a string) — return a real
        # _Skill so the test verifies ToolResult.skill coerces it to the name.
        return (f"resp:{name}", "instant", _Skill(), "Set Timer")


def test_names_has_source():
    t = SkillTools(_W())
    assert t.names() == {"set_timer", "get_weather"}
    assert t.has("set_timer") and not t.has("nope")
    assert t.source("set_timer") == "Timer"
    assert t.source("get_weather") == "Weather MCP"
    print("PASS: names/has/source")


def test_describe_all_invoke():
    t = SkillTools(_W())
    d = t.describe("set_timer")
    assert isinstance(d, ToolDescriptor) and d.source == "Timer" and d.description == "d1"
    alld = t.all()
    assert len(alld) == 2 and all(isinstance(x, ToolDescriptor) for x in alld)
    r = asyncio.get_event_loop().run_until_complete(t.invoke("set_timer", {"m": 5}))
    assert isinstance(r, ToolResult) and r.response == "resp:set_timer" and r.skill == "Timer"
    print("PASS: describe/all/invoke->ToolResult")


def test_icon():
    t = SkillTools(_W())
    # unknown tool / MCP tool (not in tool_skills) -> None
    assert t.icon("nope") is None
    assert t.icon("get_weather") is None
    # a skill tool whose module dir has no logo.png -> None (no crash)
    assert t.icon("set_timer") is None
    print("PASS: icon() -> None when no logo / not a skill tool")


def test_servers():
    t = SkillTools(_W())
    servers = t.servers()
    assert len(servers) == 1, servers
    assert servers[0]["display_name"] == "Weather MCP"
    assert servers[0]["tools"] == ["get_weather"]
    assert servers[0]["connected"] is True
    print("PASS: servers()")


if __name__ == "__main__":
    test_names_has_source()
    test_describe_all_invoke()
    test_icon()
    test_servers()
    print("ALL OK")

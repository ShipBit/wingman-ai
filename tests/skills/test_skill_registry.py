"""Skills are found first and switched on later: progressive disclosure.

A registered skill is discoverable, but its tools stay out of the model's
prompt until the skill is activated. Deactivating, resetting the conversation or
unregistering takes them away again; skills marked auto-activate are always on
and are never offered. The capability registry puts skills and MCP servers into
one list for the model and sends an activation to the registry that owns it.
"""

import asyncio
from types import SimpleNamespace

import pytest

import services.skill_registry as skill_registry_module
from services.capability_registry import CapabilityRegistry
from services.skill_registry import SkillRegistry


class FakePrintr:
    async def print_async(self, text, **kwargs):
        pass

    def print(self, text, **kwargs):
        pass


@pytest.fixture(autouse=True)
def quiet_printr(monkeypatch):
    monkeypatch.setattr(skill_registry_module, "printr", FakePrintr())


class FakeSkill:
    def __init__(self, name, tools, auto_activate=False):
        self.name = name
        self.tools = tools
        self.config = SimpleNamespace(
            display_name=name.title(),
            description=SimpleNamespace(en=f"{name} does things"),
            tags=[],
            discovery_keywords=[],
            auto_activate=auto_activate,
        )

    def get_enabled_tools(self):
        return [
            (tool, {"type": "function", "function": {"name": tool, "description": tool}})
            for tool in self.tools
        ]

    def needs_activation(self):
        return False


def registry_with(*skills):
    registry = SkillRegistry()
    for skill in skills:
        registry.register_skill(skill)
    return registry


def active_tool_names(registry):
    return {name for name, _ in registry.get_active_tools()}


def run(coroutine):
    return asyncio.run(coroutine)


# ── skills ──


def test_a_registered_skill_is_discoverable_but_its_tools_are_not_active():
    registry = registry_with(FakeSkill("notes", ["save_note"]))

    assert [m.name for m in registry.get_discoverable_skills()] == ["notes"]
    assert active_tool_names(registry) == set()


def test_activating_a_skill_exposes_its_tools_and_finds_the_skill_by_tool():
    notes = FakeSkill("notes", ["save_note", "read_note"])
    registry = registry_with(notes, FakeSkill("music", ["play_track"]))

    success, message, needs_validation = run(registry.activate_skill("notes"))

    assert success and not needs_validation
    assert "save_note" in message
    assert active_tool_names(registry) == {"save_note", "read_note"}
    assert registry.get_skill_for_tool("save_note") is notes


def test_deactivating_hides_the_tools_again():
    registry = registry_with(FakeSkill("notes", ["save_note"]))
    run(registry.activate_skill("notes"))

    ok, _ = registry.deactivate_skill("notes")

    assert ok
    assert active_tool_names(registry) == set()
    assert registry.deactivate_skill("notes")[0] is False  # already off


def test_a_conversation_reset_hides_activated_tools_but_keeps_auto_activated_ones():
    registry = registry_with(
        FakeSkill("notes", ["save_note"]),
        FakeSkill("clock", ["what_time"], auto_activate=True),
    )
    run(registry.activate_skill("notes"))
    assert active_tool_names(registry) == {"save_note", "what_time"}

    registry.reset_activations()

    assert active_tool_names(registry) == {"what_time"}
    # An always-on skill is not something the model has to activate.
    assert [m.name for m in registry.get_discoverable_skills()] == ["notes"]


def test_unregistering_removes_the_skill_and_its_tools():
    registry = registry_with(FakeSkill("notes", ["save_note"]))
    run(registry.activate_skill("notes"))

    registry.unregister_skill("notes")

    assert registry.get_discoverable_skills() == []
    assert registry.get_skill_for_tool("save_note") is None
    assert active_tool_names(registry) == set()
    assert registry.skill_count == 0


def test_activating_an_unknown_skill_fails_and_names_the_ones_that_exist():
    registry = registry_with(FakeSkill("notes", ["save_note"]))

    success, message, _ = run(registry.activate_skill("ghost"))

    assert not success
    assert "notes" in message
    assert registry.active_skill_names == set()


def test_the_meta_tools_list_only_what_can_still_be_activated():
    registry = registry_with(
        FakeSkill("notes", ["save_note"]),
        FakeSkill("clock", ["what_time"], auto_activate=True),
    )

    names = [name for name, _ in registry.get_meta_tools()]
    schema = dict(registry.get_meta_tools())["activate_skill"]["function"]

    assert names == ["activate_skill", "list_active_skills"]
    assert schema["parameters"]["properties"]["skill_name"]["enum"] == ["notes"]
    assert registry_with().get_meta_tools() == []  # nothing to offer, no tool


# ── capabilities (skills + MCP servers) ──


class FakeMcpRegistry:
    def __init__(self, names=()):
        self._manifests = {
            name: SimpleNamespace(
                name=name,
                display_name=name.title(),
                tool_names=[f"mcp_{name}_search"],
                get_discovery_description=lambda name=name: f"{name} server",
            )
            for name in names
        }
        self.active_server_names = set()
        self.activated = []

    def get_connected_servers(self):
        return list(self._manifests.values())

    async def execute_meta_tool(self, tool_name, parameters):
        self.activated.append((tool_name, parameters))
        self.active_server_names.add(parameters["server_name"])
        return "MCP on", True


def capabilities(skills, servers):
    skill_registry = registry_with(*skills)
    mcp_registry = FakeMcpRegistry(servers)
    return CapabilityRegistry(skill_registry, mcp_registry), skill_registry, mcp_registry


def test_the_capability_tool_offers_skills_first_then_mcp_servers():
    registry, _, _ = capabilities([FakeSkill("notes", ["save_note"])], ["docs"])

    tools = dict(registry.get_meta_tools())
    schema = tools["activate_capability"]["function"]

    assert schema["parameters"]["properties"]["capability_name"]["enum"] == ["notes", "docs"]
    assert "list_active_capabilities" in tools
    assert registry.has_capabilities


def test_a_capability_that_is_already_on_is_not_offered_again():
    registry, skills, mcp = capabilities([FakeSkill("notes", ["save_note"])], ["docs"])
    run(skills.activate_skill("notes"))

    schema = dict(registry.get_meta_tools())["activate_capability"]["function"]
    assert schema["parameters"]["properties"]["capability_name"]["enum"] == ["docs"]

    mcp.active_server_names.add("docs")
    assert registry.get_meta_tools() == []  # everything is on


def test_activating_a_capability_goes_to_the_registry_that_owns_it():
    registry, skills, mcp = capabilities([FakeSkill("notes", ["save_note"])], ["docs"])

    _, skill_changed = run(
        registry.execute_meta_tool("activate_capability", {"capability_name": "notes"})
    )
    _, mcp_changed = run(
        registry.execute_meta_tool("activate_capability", {"capability_name": "docs"})
    )
    message, ghost_changed = run(
        registry.execute_meta_tool("activate_capability", {"capability_name": "ghost"})
    )

    assert skill_changed and skills.active_skill_names == {"notes"}
    assert mcp_changed and mcp.activated == [("activate_mcp_server", {"server_name": "docs"})]
    assert not ghost_changed and "ghost" in message


def test_the_active_list_names_skills_and_servers_with_their_tools():
    registry, skills, mcp = capabilities([FakeSkill("notes", ["save_note"])], ["docs"])

    empty, _ = run(registry.execute_meta_tool("list_active_capabilities", {}))
    run(skills.activate_skill("notes"))
    mcp.active_server_names.add("docs")
    listing, changed = run(registry.execute_meta_tool("list_active_capabilities", {}))

    assert "No capabilities" in empty
    assert "Notes: save_note" in listing
    assert "Docs: mcp_docs_search" in listing
    assert not changed

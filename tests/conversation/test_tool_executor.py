"""The tool executor sends each function call from the model to the right place.

A skill's tool must reach that skill, an MCP tool must reach the MCP registry,
the "activate" meta tool must reach the capability registry, and a command call
must run the command. A tool that breaks must come back to the model as an
error text, never as an exception that ends the turn. `fix_tool_calls` repairs
models that put a command name where `execute_command` belongs.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import services.tool_executor as tool_executor_module
from services.tool_executor import ToolExecutor


class FakePrintr:
    async def print_async(self, text, **kwargs):
        pass

    def print(self, text, **kwargs):
        pass


@pytest.fixture(autouse=True)
def quiet_printr(monkeypatch):
    monkeypatch.setattr(tool_executor_module, "printr", FakePrintr())


class FakeSkill:
    def __init__(self, name="Notes", result=("done", None), error=None, validation=None):
        self.name = name
        self.calls = []
        self._result = result
        self._error = error
        self._validation = validation  # (ok, message) or None for "no validation"

    async def execute_tool(self, tool_name, parameters, benchmark):
        self.calls.append((tool_name, parameters))
        if self._error:
            raise self._error
        return self._result

    def needs_activation(self):
        return self._validation is not None

    async def ensure_activated(self):
        return self._validation


class NoMeta:
    """A registry that claims nothing, so the call travels on."""

    def is_meta_tool(self, name):
        return False

    def is_mcp_tool(self, name):
        return False

    def get_skill_display_name(self, name):
        return name


class FakeSkillRegistry(NoMeta):
    def __init__(self, skills=None):
        self.skills = skills or {}
        self.deactivated = []

    def get_skill_for_activation(self, name):
        return self.skills.get(name)

    def deactivate_skill(self, name):
        self.deactivated.append(name)


class FakeCapabilityRegistry(NoMeta):
    def __init__(self, response=("Activated.", True)):
        self.response = response
        self.calls = []

    def is_meta_tool(self, name):
        return name in ("activate_capability", "list_active_capabilities")

    async def execute_meta_tool(self, name, args):
        self.calls.append((name, args))
        return self.response


class FakeMcpRegistry(NoMeta):
    def __init__(self, error=None):
        self.calls = []
        self._error = error
        self._connection = SimpleNamespace(
            config=SimpleNamespace(display_name="Docs", name="docs")
        )

    def is_mcp_tool(self, name):
        return name == "mcp_docs_search"

    def get_connection_for_tool(self, name):
        return self._connection

    def get_original_tool_name(self, name):
        return "search"

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if self._error:
            raise self._error
        return "3 results"


def make_executor():
    return ToolExecutor(
        config=None,
        settings=SimpleNamespace(debug_mode=False),
        wingman_name="Computer",
    )


def dispatch(name, args=None, **overrides):
    wiring = dict(
        tool_skills={},
        skill_registry=FakeSkillRegistry(),
        mcp_registry=NoMeta(),
        capability_registry=NoMeta(),
        persistent_memory_service=None,
        get_command_fn=lambda command_name: None,
        execute_command_fn=None,
        play_to_user_fn=None,
    )
    wiring.update(overrides)
    return asyncio.run(make_executor().execute_by_function_call(name, args or {}, **wiring))


def tool_call(name, arguments, call_id="call_1"):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(id=call_id, function=function)


# ── routing ──


def test_a_skill_tool_reaches_its_skill():
    skill = FakeSkill(result=("note saved", None))

    response, instant, used, label = dispatch(
        "save_note", {"text": "milk"}, tool_skills={"save_note": skill}
    )

    assert skill.calls == [("save_note", {"text": "milk"})]
    assert response == "note saved"
    assert used is skill
    assert "save_note" in label


def test_a_skill_that_raises_answers_with_an_error_text():
    skill = FakeSkill(error=RuntimeError("disk full"))

    response, instant, used, _ = dispatch("save_note", {}, tool_skills={"save_note": skill})

    assert response == "ERROR DURING PROCESSING"
    assert instant is None
    assert used is None


def test_an_mcp_tool_reaches_the_mcp_registry_and_is_labelled_with_its_original_name():
    mcp = FakeMcpRegistry()

    response, _, used, label = dispatch("mcp_docs_search", {"q": "x"}, mcp_registry=mcp)

    assert mcp.calls == [("mcp_docs_search", {"q": "x"})]
    assert response == "3 results"
    assert used is None
    assert label.endswith("Docs: search")

    # A tool that blows up reaches the model as text, not as an exception.
    failing = FakeMcpRegistry(error=ConnectionError("gone"))
    response, _, _, _ = dispatch("mcp_docs_search", {}, mcp_registry=failing)
    assert response == "ERROR DURING MCP TOOL EXECUTION"


def test_activating_a_capability_goes_to_the_capability_registry():
    capabilities = FakeCapabilityRegistry(("Activated 'Notes'.", False))

    response, instant, used, label = dispatch(
        "activate_capability",
        {"capability_name": "Notes"},
        capability_registry=capabilities,
    )

    assert capabilities.calls == [("activate_capability", {"capability_name": "Notes"})]
    assert response == "Activated 'Notes'."
    assert label is None  # meta tools are not timed


def test_a_skill_that_fails_its_check_on_activation_is_switched_off_again():
    skill = FakeSkill(validation=(False, "API key missing"))
    skills = FakeSkillRegistry({"Notes": skill})

    response, _, _, _ = dispatch(
        "activate_capability",
        {"capability_name": "Notes"},
        skill_registry=skills,
        capability_registry=FakeCapabilityRegistry(("Activating...", True)),
    )

    assert response == "API key missing"
    assert skills.deactivated == ["Notes"]


def test_a_command_call_runs_the_command_and_plays_its_response():
    command = SimpleNamespace(name="lights on")
    ran, played = [], []

    async def execute_command(cmd):
        ran.append(cmd)
        return "Lights are on.", "executed"

    async def play(text):
        played.append(text)

    response, instant, _, label = dispatch(
        "execute_command",
        {"command_name": "lights on"},
        get_command_fn=lambda name: command if name == "lights on" else None,
        execute_command_fn=execute_command,
        play_to_user_fn=play,
    )

    assert ran == [command]
    assert response == "executed"
    assert played == ["Lights are on."]
    assert "lights on" in label


def test_an_unknown_tool_tells_the_model_it_does_not_exist():
    """A made-up or no longer active tool used to come back as an empty
    answer, which left the model guessing."""
    response, _, used, _ = dispatch("teleport_ship", {"to": "Pyro"})

    assert "no tool named 'teleport_ship'" in response
    assert used is None


# ── fix_tool_calls ──


def fix(calls, known=("lights on",)):
    executor = make_executor()
    return asyncio.run(
        executor.fix_tool_calls(calls, lambda name: name if name in known else None)
    )


def test_a_command_name_used_as_function_name_becomes_execute_command():
    call = tool_call("lights on", "{}")

    fix([call])

    assert call.function.name == "execute_command"
    assert json.loads(call.function.arguments) == {"command_name": "lights on"}


def test_a_command_name_repeated_in_the_arguments_is_wrapped_too_even_as_a_dict():
    call = tool_call("lights on", {"command_name": "lights on"})

    fix([call])

    assert call.function.name == "execute_command"
    assert json.loads(call.function.arguments) == {"command_name": "lights on"}


def test_real_tool_calls_are_left_alone():
    plain = tool_call("execute_command", '{"command_name": "lights on"}')
    unknown = tool_call("save_note", "{}")
    with_args = tool_call("lights on", '{"brightness": 5}')

    fix([plain, unknown, with_args])

    assert plain.function.name == "execute_command"
    assert unknown.function.name == "save_note"
    assert unknown.function.arguments == "{}"
    assert with_args.function.name == "lights on"


# ── handle_tool_calls ──


def handle(calls, **overrides):
    updated, added = [], []

    async def update(call_id, text):
        updated.append((call_id, text))
        return True

    wiring = dict(
        tool_skills={},
        skill_registry=FakeSkillRegistry(),
        mcp_registry=NoMeta(),
        capability_registry=NoMeta(),
        persistent_memory_service=None,
        get_command_fn=lambda name: None,
        execute_command_fn=None,
        play_to_user_fn=None,
        update_tool_response_fn=update,
        add_tool_response_fn=lambda call, text: added.append((call.function.name, text)),
        pending_tool_calls=[],
    )
    wiring.update(overrides)
    result = asyncio.run(make_executor().handle_tool_calls(calls, **wiring))
    return result, updated, added


def test_a_result_replaces_the_placeholder_answer_and_is_timed():
    skill = FakeSkill(result=("note saved", "Saved!"))
    played = []

    async def play(text):
        played.append(text)

    (instant, used, timings), updated, added = handle(
        [tool_call("save_note", '{"text": "milk"}', call_id="abc")],
        tool_skills={"save_note": skill},
        play_to_user_fn=play,
    )

    assert updated == [("abc", "note saved")]
    assert added == []
    assert instant == "Saved!"
    assert played == ["Saved!"]
    assert used is skill
    assert len(timings) == 1 and "save_note" in timings[0][0]


def test_one_broken_call_does_not_stop_the_calls_after_it():
    skill = FakeSkill(result=("ok", None))

    _, updated, _ = handle(
        [
            tool_call("save_note", "not json", call_id="bad"),
            tool_call("save_note", "{}", call_id="good"),
        ],
        tool_skills={"save_note": skill},
    )

    assert updated == [("bad", "Error"), ("good", "ok")]

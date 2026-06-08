"""Standalone verification for facade value types. Run:
    PYTHONPATH=. venv/bin/python -m tests.test_facade_types
"""
from wingmen.facade import ToolResult, ToolDescriptor, Subscription, CommandCategory


def test_tool_result():
    r = ToolResult(response="hi", instant_response="", skill="Timer", label="set_timer")
    assert r.response == "hi" and r.skill == "Timer"
    print("PASS: ToolResult")


def test_tool_descriptor():
    d = ToolDescriptor(name="set_timer", source="Timer", description="d", parameters={"type": "object"})
    assert d.name == "set_timer" and d.parameters["type"] == "object"
    print("PASS: ToolDescriptor")


def test_subscription():
    calls = []
    sub = Subscription(lambda: calls.append(1))
    sub.unsubscribe()
    sub.unsubscribe()  # idempotent
    assert calls == [1], calls
    print("PASS: Subscription")


def test_command_category():
    cat = CommandCategory(id="abc", name="Timers")
    assert cat.id == "abc" and cat.name == "Timers"
    print("PASS: CommandCategory")


if __name__ == "__main__":
    test_tool_result()
    test_tool_descriptor()
    test_subscription()
    test_command_category()
    print("ALL OK")

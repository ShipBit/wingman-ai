"""Two skills can register the same function names (a bundled skill and an old custom
copy of it). The provider rejects a request that lists a name twice."""

from wingmen.wingman import unique_tools


def tool(name: str, description: str = "") -> dict:
    return {"type": "function", "function": {"name": name, "description": description}}


def test_each_function_name_is_sent_once():
    tools = [tool("uex_get_trade_routes", "bundled"), tool("timer"), tool("uex_get_trade_routes", "copy")]

    assert unique_tools(tools) == [tool("uex_get_trade_routes", "bundled"), tool("timer")]


def test_tools_without_a_name_are_kept():
    odd = {"type": "web_search"}

    assert unique_tools([odd, tool("timer")]) == [odd, tool("timer")]

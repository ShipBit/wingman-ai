"""Exercise actual SDK stdio discovery/calls without network or Core startup."""

import json
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, AsyncMock, patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_wingman_discovery_and_cleanup_across_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            # Only logging is isolated. The real client and SDK execute.
            logger = Mock()
            logger.print_async = AsyncMock()
            with patch("services.printr.Printr", return_value=logger):
                from services.mcp_client import McpClient
                from api.interface import McpServerConfig
            with patch("services.mcp_client.printr", logger):
                config = McpServerConfig(name="elite_test", display_name="Test", type="stdio",
                    command=sys.executable, args=[str(Path("integrations/elite_dangerous/server.py").resolve()),
                    "--cache-dir", directory])
                client = McpClient()
                connection = await asyncio.create_task(client.connect(config))
                self.assertTrue(connection.is_connected, connection.error)
                self.assertIsNone(connection.session)
                result = await client.call_tool(connection, "elite_system_lookup", {"system": "Sol", "galaxy": "legacy"})
                self.assertIn("unsupported", json.loads(result)["error"])
                await asyncio.create_task(client.disconnect(connection))
                self.assertFalse(connection.is_connected)

    async def test_real_stdio_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            params = StdioServerParameters(command=sys.executable, args=[
                str(Path("integrations/elite_dangerous/server.py").resolve()),
                "--cache-dir", directory])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({"elite_system_lookup", "elite_station_lookup", "elite_trade_compare", "elite_nearby_services", "elite_engineering_lookup"},
                                     {tool.name for tool in tools.tools})
                    result = await session.call_tool("elite_engineering_lookup", {"query": "FSD", "galaxy": "legacy"})
                    self.assertFalse(result.isError)
                    self.assertIn("unsupported", json.loads(result.content[0].text)["error"])
                    result = await session.call_tool("elite_system_lookup", {"system": "Sol", "galaxy": "legacy"})
                    self.assertFalse(result.isError)
                    self.assertIn("unsupported", json.loads(result.content[0].text)["error"])
                    result = await session.call_tool("elite_nearby_services", {"system": "Sol", "galaxy": "legacy"})
                    self.assertFalse(result.isError)
                    self.assertIn("unsupported", json.loads(result.content[0].text)["error"])
                    result = await session.call_tool("elite_station_lookup", {"market_id": "123", "galaxy": "legacy"})
                    self.assertFalse(result.isError)
                    self.assertIn("unsupported", json.loads(result.content[0].text)["error"])
                    result = await session.call_tool("elite_trade_compare", {
                        "origin_market_id": "1", "destination_market_id": "2", "free_cargo_tonnes": 10,
                        "credits": 1000, "rebuy_reserve": 500, "ship_pad": "S", "galaxy": "legacy"})
                    self.assertFalse(result.isError)
                    self.assertIn("unsupported", json.loads(result.content[0].text)["error"])


if __name__ == "__main__":
    unittest.main()

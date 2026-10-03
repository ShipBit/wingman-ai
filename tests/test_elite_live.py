"""Opt-in checks of actual journals and public network, excluded by default.

ELITE_LIVE_SMOKE=1 python -m unittest discover -s tests -p test_elite_live.py -v
This never starts Core, plays audio, changes bindings, or uploads the journal.
"""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from skills.elite_dangerous.telemetry import JournalReader, default_journal_dir


@unittest.skipUnless(os.environ.get("ELITE_LIVE_SMOKE") == "1", "Opt-in local/public API checks")
class LiveChecks(unittest.IsolatedAsyncioTestCase):
    async def test_local_journal_and_wingman_mcp_client(self):
        reader = JournalReader(default_journal_dir())
        reader.refresh()
        state = reader.snapshot()
        self.assertTrue(state["game_version"], state)
        self.assertIn(state["galaxy"], ("live", "legacy"))
        self.assertNotIn("warnings", state)

        # Redirect test logging to the ignored workspace instead of user's Core
        # settings. Exercise the real Wingman MCP client without launching Core.
        work = Path(".elite-local/verification").resolve()
        work.mkdir(parents=True, exist_ok=True)

        def writable(subdir=None):
            dest = work / (subdir or "runtime")
            dest.mkdir(parents=True, exist_ok=True)
            return str(dest)

        with patch("services.file.get_writable_dir", side_effect=writable):
            from api.interface import McpConfig
            from services.mcp_client import McpClient
            import yaml

            config = McpConfig.model_validate(yaml.safe_load(Path(
                "integrations/elite_dangerous/mcp.example.yaml").read_text(encoding="utf-8"))).servers[0]
            client = McpClient(wingman_name="Elite verification")
            connection = await client.connect(config)
            self.assertTrue(connection.is_connected, connection.error)
            try:
                text = await client.call_tool(connection, "elite_system_lookup", {"system": "Sol"})
                result = json.loads(text)
                self.assertNotIn("error", result)
                self.assertEqual("Sol", result["system"]["name"])
                self.assertEqual({"x": 0, "y": 0, "z": 0}, result["system"]["coords"])
                stations_text = await client.call_tool(connection, "elite_system_lookup", {
                    "system": "Sol", "kind": "stations", "query": "refuel"})
                stations = json.loads(stations_text)
                self.assertNotIn("error", stations)
                self.assertTrue(stations["found"])
                self.assertLessEqual(len(stations["stations"]), 5)
                nearby_text = await client.call_tool(connection, "elite_nearby_services", {
                    "system": "Sol", "service": "refuel", "radius_ly": 5})
                nearby = json.loads(nearby_text)
                self.assertNotIn("error", nearby)
                self.assertTrue(nearby["candidates"])
                self.assertLessEqual(len(nearby["candidates"]), 5)
                self.assertGreater(nearby["coverage"]["checked_systems"], 0)
                self.assertTrue(all(c["service_reported"] == "refuel" for c in nearby["candidates"]))
                market_text = await client.call_tool(connection, "elite_station_lookup", {
                    "market_id": "3534391808", "section": "market", "query": "gold"})
                market = json.loads(market_text)
                self.assertNotIn("error", market)
                self.assertEqual(3534391808, market["station"]["market_id"])
                self.assertIn("freshness", market)
                self.assertIn("observed_at", market)
                destination = next(str(s["marketId"]) for s in stations["stations"] if s.get("marketId") != 3534391808)
                trade_text = await client.call_tool(connection, "elite_trade_compare", {
                    "origin_market_id": "3534391808", "destination_market_id": destination,
                    "free_cargo_tonnes": 30, "credits": 100000, "rebuy_reserve": 30000, "ship_pad": "S"})
                trade = json.loads(trade_text)
                self.assertNotIn("error", trade)
                self.assertIn(trade["assessment"], ("blocked", "conditional_estimates", "no_viable_observed_quotes"))
                self.assertLessEqual(len(trade["candidates"]), 5)
                engineering = json.loads(await client.call_tool(connection, "elite_engineering_lookup", {
                    "query": "FSD_LongRange", "grade": 5, "applications": 2}))
                self.assertNotIn("error", engineering)
                self.assertFalse(engineering["stale_reference"])
                self.assertEqual(1, len(engineering["recipes"]))
                recipe = engineering["recipes"][0]
                self.assertEqual("FSD_LongRange", recipe["id"])
                self.assertTrue(any(m.get("journal_symbol") == "dataminedwake" for m in recipe["materials"]))
                self.assertTrue(all(m["required_for_requested_applications"] == 2 * m["per_application"] for m in recipe["materials"]))
                # Fixed synthetic planning inputs; never inferred player finances.
                # Save only non-personal evidence, no pilot identity/location.
                evidence = {
                    "local": {k: state[k] for k in ("game_version", "galaxy", "session", "odyssey", "retrieved_at")},
                    "mcp_tools": [tool.name for tool in connection.tools],
                    "system_check": result,
                    "station_check": stations,
                    "nearby_services_check": nearby,
                    "spansh_market_check": market,
                    "trade_check_synthetic_budget": trade,
                    "engineering_check_explicit_two_applications": engineering,
                }
                (work / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            finally:
                await client.disconnect(connection)


if __name__ == "__main__":
    unittest.main()

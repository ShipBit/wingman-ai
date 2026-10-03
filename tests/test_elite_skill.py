"""Real Skill base/schema; audio and secrets services are isolated test doubles."""

import asyncio
from datetime import datetime, timezone
from importlib import util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import yaml
from api.interface import SkillConfig
from services.pub_sub import PubSub
from skills.elite_dangerous.main import EliteDangerous


class SkillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.printr = SimpleNamespace(print=Mock(), print_async=AsyncMock())
        self.secret_keeper = SimpleNamespace(secret_events=PubSub())
        self.wingman = SimpleNamespace(name="Test", audio_player=SimpleNamespace(
            is_playing=False, event_loop=asyncio.get_running_loop()), play_to_user=AsyncMock())
        with open("skills/elite_dangerous/default_config.yaml", encoding="utf-8") as handle:
            self.config = SkillConfig.model_validate(yaml.safe_load(handle))
        self.config.custom_properties[0].value = str(self.root)
        with patch("skills.skill_base.Printr", return_value=self.printr), patch(
                "skills.skill_base.SecretKeeper", return_value=self.secret_keeper):
            self.skill = EliteDangerous(self.config, SimpleNamespace(debug_mode=False), self.wingman)
        self.addAsyncCleanup(self.skill.unload)

    async def test_real_activation_schema_and_unload(self):
        self.assertFalse(self.skill.is_prepared)
        self.assertTrue(self.config.auto_activate)
        success, reason = await self.skill.ensure_activated()
        self.assertTrue(success, reason)
        self.assertTrue(self.skill.is_prepared)
        task = self.skill._task
        self.assertFalse(task.done())
        tools = self.skill.get_tools()
        self.assertEqual(["elite_status"], [t[0] for t in tools])
        self.assertIn("progression", tools[0][1]["function"]["parameters"]["properties"]["topic"]["enum"])
        result = json.loads(await self.skill.elite_status())
        self.assertEqual("offline", result["session"])
        await self.skill.unload()
        self.assertTrue(task.done())
        self.assertIsNone(self.skill._task)

    async def test_live_config_change_and_release_import(self):
        old = self.skill._current_reader()
        self.config.custom_properties[0].value = str(self.root / "different")
        self.assertNotEqual(old.directory, self.skill._current_reader().directory)
        # Match ModuleManager's package-less release loading mode.
        spec = util.spec_from_file_location("main", "skills/elite_dangerous/main.py")
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual("EliteDangerous", module.EliteDangerous.__name__)

    async def test_announcements_fresh_throttled_and_non_interrupting(self):
        old = {"event": "Docked", "StationName": "Old", "timestamp": "2000-01-01T00:00:00Z"}
        await self.skill._announce([old])
        self.wingman.play_to_user.assert_not_awaited()
        event = {"event": "Docked", "StationName": "Test Port", "timestamp": datetime.now(timezone.utc).isoformat()}
        await self.skill._announce([event])
        self.wingman.play_to_user.assert_awaited_once_with("Docking confirmed at Test Port.", no_interrupt=True)
        await self.skill._announce([event])
        self.assertEqual(1, self.wingman.play_to_user.await_count)

    async def test_busy_audio_skips_announcement(self):
        self.wingman.audio_player.is_playing = True
        event = {"event": "MissionCompleted", "timestamp": datetime.now(timezone.utc).isoformat()}
        await self.skill._announce([event])
        self.wingman.play_to_user.assert_not_awaited()

    async def test_monitor_survives_voice_request_loop_and_unloads_cross_loop(self):
        path = self.root / "Journal.2026-09-27T120000.01.log"
        old = {"event": "Docked", "StationName": "Historical", "timestamp": "2000-01-01T00:00:00Z"}
        header = {"event": "Fileheader", "gameversion": "4.4.1.1", "timestamp": "2000-01-01T00:00:00Z"}
        loaded = {"event": "LoadGame", "timestamp": "2000-01-01T00:00:00Z"}
        path.write_text("\n".join(json.dumps(event) for event in (header, loaded, old)) + "\n", encoding="utf-8")
        # Match Core: activation completes, then the voice thread closes its loop.
        success, reason = await asyncio.to_thread(lambda: asyncio.run(self.skill.ensure_activated()))
        self.assertTrue(success, reason)
        self.assertTrue(self.skill._current_reader().running)
        task = self.skill._task
        self.assertIs(task.get_loop(), asyncio.get_running_loop())
        self.assertFalse(task.done())
        self.wingman.play_to_user.assert_not_awaited()
        spoken = asyncio.Event()
        async def speech(*args, **kwargs):
            spoken.set()
        self.wingman.play_to_user.side_effect = speech
        fresh = {"event": "Docked", "StationName": "Test Port", "timestamp": datetime.now(timezone.utc).isoformat()}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fresh) + "\n")
        await asyncio.wait_for(spoken.wait(), timeout=5)
        self.wingman.play_to_user.assert_awaited_once_with("Docking confirmed at Test Port.", no_interrupt=True)
        await asyncio.to_thread(lambda: asyncio.run(self.skill.unload()))
        self.assertTrue(task.done())
        self.assertIsNone(self.skill._task)

    async def test_status_refresh_does_not_discard_narration_events(self):
        event = {"event": "Docked", "StationName": "Test Port", "timestamp": datetime.now(timezone.utc).isoformat()}
        reader = SimpleNamespace(refresh=Mock(return_value=[event]), running=True, summary=Mock(return_value="{}"))
        with patch.object(self.skill, "_current_reader", return_value=reader):
            self.skill._primed_reader = reader
            result = await asyncio.to_thread(lambda: asyncio.run(self.skill.elite_status()))
        self.assertEqual("{}", result)
        self.wingman.play_to_user.assert_awaited_once_with("Docking confirmed at Test Port.", no_interrupt=True)

    async def test_repeated_prepare_starts_one_monitor_and_unload_stops_watchdog(self):
        await self.skill.ensure_activated()
        task, watchdog = self.skill._task, self.skill._watchdog
        await self.skill._start_monitor()
        self.assertIs(task, self.skill._task)
        self.assertIs(watchdog, self.skill._watchdog)
        await self.skill.unload()
        self.assertTrue(task.done())
        self.assertTrue(watchdog.done())

    async def test_watchdog_recovers_unexpected_monitor_exit(self):
        await self.skill.ensure_activated()
        task = self.skill._task
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(2.1)
        self.assertIsNot(task, self.skill._task)
        self.assertFalse(self.skill._task.done())

    async def test_initial_journal_failure_does_not_prevent_activation(self):
        with patch.object(self.skill, "_current_reader", side_effect=OSError("temporarily unavailable")):
            success, reason = await self.skill.ensure_activated()
            self.assertTrue(success, reason)
            await asyncio.sleep(0)
            self.assertFalse(self.skill._task.done())


if __name__ == "__main__":
    unittest.main()

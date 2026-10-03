"""Synthetic status timing regressions, not live gameplay acceptance."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from skills.elite_dangerous import telemetry
from skills.elite_dangerous_controls.observation import observe_status, ObservationUnavailable


class ObservationTimingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.stamp = datetime(2026, 9, 28, 19, 23, 50, tzinfo=timezone.utc)
        self.data = {'event': 'Status', 'timestamp': self.stamp.isoformat(), 'Flags': 1 << 24, 'GuiFocus': 0}
        self.write()
        self.reader = SimpleNamespace(directory=self.directory, running=True, catch_up=False,
                                      session_started=(self.stamp - timedelta(minutes=20)).isoformat(),
                                      galaxy='live', game_version='4.4.1.1', refresh=Mock())

    def write(self):
        (self.directory / 'Status.json').write_text(json.dumps(self.data), encoding='utf-8')

    async def test_quarter_second_live_clock_lead_waits_and_rereads_without_input(self):
        now = self.stamp - timedelta(seconds=0.247681)
        with patch.object(telemetry, 'utc_now', side_effect=[now, self.stamp]):
            result = await observe_status(self.reader, telemetry)
        self.assertAlmostEqual(0.247681, result['initial_clock_lead_seconds'])
        self.assertGreaterEqual(result['timestamp_wait_seconds'], 0.247681)
        self.assertEqual(2, self.reader.refresh.call_count)
        self.assertEqual(self.stamp.isoformat(), result['received_at'])

    async def test_large_future_timestamp_is_rejected_without_wait(self):
        with patch.object(telemetry, 'utc_now', return_value=self.stamp - timedelta(seconds=2)):
            with self.assertRaises(ObservationUnavailable) as caught:
                await observe_status(self.reader, telemetry)
        self.assertEqual(2, caught.exception.evidence['seconds_ahead_of_clock'])
        self.assertEqual(0, caught.exception.evidence['timestamp_wait_seconds'])

    async def test_empty_then_partial_write_is_reread_until_complete(self):
        complete = json.dumps(self.data).encode()
        with patch.object(Path, 'read_bytes', side_effect=[b'', b'{"event":', complete]), patch.object(telemetry, 'utc_now', return_value=self.stamp):
            result = await observe_status(self.reader, telemetry)
        self.assertEqual(2, result['read_retries'])
        self.assertEqual(self.data, result['data'])

    async def test_persistently_incomplete_file_stops_with_useful_evidence(self):
        with patch.object(Path, 'read_bytes', return_value=b''), patch.object(telemetry, 'utc_now', return_value=self.stamp):
            with self.assertRaises(ObservationUnavailable) as caught:
                await observe_status(self.reader, telemetry)
        self.assertEqual('JSONDecodeError', caught.exception.evidence['read_error'])
        self.assertEqual(0, caught.exception.evidence['raw_length'])
        self.assertEqual(5, caught.exception.evidence['read_retries'])

    async def test_complete_but_wrong_status_is_not_retried(self):
        with patch.object(Path, 'read_bytes', return_value=b'[]'), patch.object(telemetry, 'utc_now', return_value=self.stamp):
            with self.assertRaises(ObservationUnavailable) as caught:
                await observe_status(self.reader, telemetry)
        self.assertEqual(0, caught.exception.evidence['read_retries'])

    async def test_shutdown_during_clock_wait_is_not_accepted(self):
        def refresh():
            if self.reader.refresh.call_count == 2:
                self.reader.running = False
        self.reader.refresh.side_effect = refresh
        with patch.object(telemetry, 'utc_now', side_effect=[self.stamp - timedelta(seconds=0.02), self.stamp]):
            with self.assertRaises(ObservationUnavailable):
                await observe_status(self.reader, telemetry)

    async def test_cancellation_interrupts_wait(self):
        with patch.object(telemetry, 'utc_now', return_value=self.stamp - timedelta(seconds=0.8)):
            task = asyncio.create_task(observe_status(self.reader, telemetry))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_continuously_future_data_has_a_fixed_wait_budget(self):
        with patch.object(telemetry, 'utc_now', return_value=self.stamp - timedelta(seconds=0.6)):
            with self.assertRaises(ObservationUnavailable) as caught:
                await observe_status(self.reader, telemetry)
        self.assertLessEqual(caught.exception.evidence['timestamp_wait_seconds'], 1.1)


if __name__ == '__main__':
    unittest.main()

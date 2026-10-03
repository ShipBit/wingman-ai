"""Map confirmation follows game telemetry, never mere OS acceptance."""
import asyncio
from copy import deepcopy
import time
import unittest
from unittest.mock import AsyncMock, Mock

from services.tool_execution import ControlAuthorization
from skills.elite_dangerous_controls.runtime import ControlEngine, routing_context


class MapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = {'pid': 1, 'started': time.time() - 60}
        self.status = {'session': 'live', 'observed': time.time(), 'revision': 'before',
                       'data': {'Flags': 1 << 24, 'GuiFocus': 0}}
        self.backend = Mock(sent=[], context=Mock(side_effect=lambda: dict(self.context)))
        self.binding = {'revision': 'bindings', 'available': {
            ('ship', 'GalaxyMapOpen'): {'chord': ('Key_Numpad_Divide',)},
            ('ship', 'SystemMapOpen'): {'chord': ('Key_Numpad_Multiply',)}}, 'unavailable': {}}
        self.resolver = Mock(stable=AsyncMock(return_value=self.binding), read=Mock(return_value=self.binding))
        self.after_send = lambda: None
        async def send(chord, check):
            await check()
            self.backend.sent.extend([{'inserted': 1, 'release': r} for r in (False, True)])
            self.after_send()
        self.backend.send = AsyncMock(side_effect=send)
        self.observe = AsyncMock(side_effect=lambda: deepcopy(self.status))
        self.engine = ControlEngine(self.backend, self.resolver, self.observe, timeout=0.25)
        self.addAsyncCleanup(self.engine.close)

    def transition(self, focus):
        self.status['data']['GuiFocus'] = focus
        self.status['revision'] = str(focus)

    async def test_both_maps_open_and_close_with_one_press_and_fresh_evidence(self):
        for action, focus in [('galaxy_map', 6), ('system_map', 7)]:
            for start, end in [(0, focus), (focus, 0)]:
                with self.subTest(action=action, start=start):
                    self.transition(start)
                    before_count = self.backend.send.await_count
                    self.after_send = lambda: self.transition(end)
                    result = await self.engine.run_result(action, 'on')
                    self.assertEqual('confirmed', result.outcome)
                    self.assertEqual(end, result.evidence['after']['data']['GuiFocus'])
                    self.assertTrue(result.to_dict()['gameplay_verified'])
                    self.assertEqual(before_count + 1, self.backend.send.await_count)

    async def test_semantic_authorization_allows_only_expected_ui_transition(self):
        auth = ControlAuthorization('turn', 'system_map', 'on', 'auto', routing_context(self.context, self.status))
        self.after_send = lambda: self.transition(7)
        result = await self.engine.run_result('system_map', 'on', request_id='turn:direct', authorization=auth)
        self.assertEqual('confirmed', result.outcome)
        self.assertEqual(1, self.backend.send.await_count)

    async def test_no_map_transition_times_out_without_acknowledgment_or_retry(self):
        result = await self.engine.run_result('galaxy_map')
        self.assertEqual('unverified', result.outcome)
        self.assertEqual('game_observation', result.first_failing_stage)
        self.assertIn('not observed', result.speech)
        self.assertEqual(1, self.backend.send.await_count)

    async def test_stale_revision_cannot_confirm_a_map(self):
        self.after_send = lambda: self.status['data'].update(GuiFocus=6)
        result = await self.engine.run_result('galaxy_map')
        self.assertEqual('unverified', result.outcome)

    async def test_observation_failure_after_press_remains_unverified(self):
        def unavailable():
            self.observe.side_effect = ValueError('Status file unavailable')
        self.after_send = unavailable
        result = await self.engine.run_result('galaxy_map')
        self.assertEqual('unverified', result.outcome)
        self.assertEqual(1, self.backend.send.await_count)

    async def test_unexpected_context_changes_cannot_confirm(self):
        for change in [lambda: self.transition(7),
                       lambda: self.status.update(session='new-session'),
                       lambda: self.context.update(pid=2),
                       lambda: self.status['data'].update(Flags=1 << 26)]:
            with self.subTest(change=change):
                original_status, original_context = deepcopy(self.status), dict(self.context)
                self.after_send = change
                result = await self.engine.run_result('galaxy_map')
                self.assertEqual('unverified', result.outcome)
                self.status, self.context = original_status, original_context

    async def test_cancellation_and_new_turn_never_retry(self):
        current = True
        def supersede():
            nonlocal current
            current = False
        self.after_send = supersede
        result = await self.engine.run_result('galaxy_map', still_current=lambda: current)
        self.assertEqual('unverified', result.outcome)
        self.after_send = lambda: asyncio.get_running_loop().call_soon(self.engine.cancel)
        with self.assertRaises(asyncio.CancelledError):
            await self.engine.run_result('galaxy_map')
        self.assertEqual(2, self.backend.send.await_count)

    async def test_duplicate_request_does_not_toggle_confirmed_map_closed(self):
        self.after_send = lambda: self.transition(6)
        await self.engine.run_result('galaxy_map', request_id='one')
        result = await self.engine.run_result('galaxy_map', request_id='one')
        self.assertEqual('duplicate', result.outcome)
        self.assertEqual(1, self.backend.send.await_count)

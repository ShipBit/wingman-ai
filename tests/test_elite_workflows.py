"""Synthetic three-run workflow coverage, including interruption; no live acceptance."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock

from skills.elite_dangerous_controls.runtime import ACTIONS, STATE_BITS, ControlEngine
from skills.elite_dangerous_controls.workflows import WORKFLOWS, WorkflowRunner, parse_workflow


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data = {'Flags': 1 << 24, 'Flags2': 0, 'GuiFocus': 0}
        self.context = {'pid': 1, 'started': time.time() - 60}
        self.session, self.revision = 'session', 0
        self.changes = True
        self.events = []
        self.backend = Mock(sent=[], context=Mock(return_value=self.context))
        self.binding = {'revision': 'bindings', 'available': {
            (mode, tag): {'chord': (tag,)} for mode, catalog in ACTIONS.items() for tag in catalog}, 'unavailable': {}}
        self.resolver = Mock(stable=AsyncMock(return_value=self.binding), read=Mock(return_value=self.binding))
        async def observe():
            return {'session': self.session, 'revision': str(self.revision), 'observed': time.time(), 'data': dict(self.data)}
        async def send(chord, check):
            await check()
            self.backend.sent.append({'inserted': 1, 'requested': 1, 'release': False})
            try:
                if self.changes and chord[0] in STATE_BITS:
                    self.data['Flags'] ^= 1 << STATE_BITS[chord[0]]
                self.revision += 1
            finally:
                self.backend.sent.append({'inserted': 1, 'requested': 1, 'release': True})
        self.backend.send = AsyncMock(side_effect=send)
        self.engine = ControlEngine(self.backend, self.resolver, observe, self.events.append, timeout=0.02)
        self.runner = WorkflowRunner(self.engine, self.events.append)
        self.addAsyncCleanup(self.engine.close)
        self.addAsyncCleanup(self.runner.close)

    def mode(self, mode):
        self.data.update(Flags={'ship': 1 << 24, 'srv': 1 << 26, 'on_foot': 0}[mode],
                         Flags2=1 if mode == 'on_foot' else 0, GuiFocus=0)

    async def test_all_twelve_workflows_complete_three_synthetic_runs_with_explicit_checkpoints(self):
        self.assertEqual(12, len(WORKFLOWS))
        for name, workflow in WORKFLOWS.items():
            for run in range(3):
                with self.subTest(workflow=name, run=run):
                    self.mode(workflow.mode)
                    response = await self.runner.handle('start', name, request_id=f'{name}:{run}:start')
                    for index in range(10):
                        if self.runner.state != 'waiting':
                            break
                        self.assertIn('continue workflow', response)
                        response = await self.runner.handle('continue', request_id=f'{name}:{run}:{index}')
                    self.assertEqual('complete', self.runner.state, response)
                    self.assertEqual(workflow.completion, response)
        self.assertEqual(36, sum(e.get('event') == 'workflow_complete' for e in self.events))

    async def test_missing_observation_stops_after_one_press_and_never_replays_it(self):
        self.changes = False
        response = await self.runner.handle('start', 'combat_preparation', request_id='one')
        self.assertEqual('stopped', self.runner.state)
        self.assertIn('Unverified', response)
        self.assertEqual(1, self.backend.send.await_count)
        await self.runner.handle('continue', request_id='two')
        self.assertEqual(1, self.backend.send.await_count)

    async def test_consumables_wait_and_duplicate_or_continue_never_replays(self):
        for name in ('defensive_heat_sink', 'defensive_chaff', 'on_foot_health', 'on_foot_energy'):
            self.mode(WORKFLOWS[name].mode)
            before = self.backend.send.await_count
            await self.runner.handle('start', name, request_id=name)
            self.assertEqual('waiting', self.runner.state)
            await self.runner.handle('start', name, request_id=name)
            await self.runner.handle('start', name, request_id=name + ':extra')
            self.assertEqual(before + 1, self.backend.send.await_count)
            await self.runner.handle('continue', request_id=name + ':continue')
            await self.runner.handle('continue', request_id=name + ':continue')
            self.assertEqual(before + 1, self.backend.send.await_count)

    async def test_focus_session_binding_and_conflicting_state_stop_progression(self):
        for condition in ('focus', 'chat', 'session', 'binding', 'player_state'):
            self.mode('ship')
            self.backend.context.side_effect = None
            await self.runner.handle('start', 'combat_preparation', request_id=condition)
            self.assertEqual('waiting', self.runner.state)
            before = self.backend.send.await_count
            if condition == 'focus':
                self.backend.context.side_effect = ValueError('Elite is not focused')
            elif condition == 'chat':
                self.data['GuiFocus'] = 1
            elif condition == 'session':
                self.session += '-changed'
            elif condition == 'binding':
                self.binding['revision'] += '-changed'
            else:
                self.data['Flags'] ^= 1 << 6
            await self.runner.monitor()
            self.assertEqual('cancelled', self.runner.state)
            await self.runner.handle('continue', request_id=condition + ':continue')
            self.assertEqual(before, self.backend.send.await_count)

    async def test_route_checkpoint_allows_map_but_will_not_press_into_it(self):
        await self.runner.handle('start', 'route_target', request_id='start')
        self.data['GuiFocus'] = 6
        await self.runner.monitor()
        self.assertEqual('waiting', self.runner.state)
        await self.runner.handle('continue', request_id='continue')
        self.assertEqual('stopped', self.runner.state)
        self.backend.send.assert_not_awaited()

    async def test_cancel_during_input_releases_and_requires_fresh_start(self):
        pressed = asyncio.Event()
        async def send(chord, check):
            await check()
            self.backend.sent.append({'inserted': 1, 'requested': 1, 'release': False})
            pressed.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.backend.sent.append({'inserted': 1, 'requested': 1, 'release': True})
        self.backend.send.side_effect = send
        task = asyncio.create_task(self.runner.handle('start', 'combat_preparation', request_id='start'))
        await asyncio.wait_for(pressed.wait(), 2)
        self.runner.cancel()
        await task
        self.assertEqual('cancelled', self.runner.state)
        self.assertTrue(self.backend.sent[-1]['release'])
        await self.runner.handle('continue', request_id='continue')
        self.assertEqual(1, self.backend.send.await_count)

    async def test_wrong_mode_and_newer_request_send_nothing(self):
        response = await self.runner.handle('start', 'srv_configuration', request_id='wrong-mode')
        self.assertEqual('stopped', self.runner.state, response)
        await self.runner.handle('start', 'combat_preparation', request_id='old', still_current=lambda: False)
        self.backend.send.assert_not_awaited()

    def test_only_explicit_workflow_requests_parse(self):
        for name in WORKFLOWS:
            self.assertEqual({'operation': 'start', 'workflow': name}, parse_workflow('start ' + name.replace('_', ' ') + ' workflow'))
        for phrase in ('do not start combat preparation', 'if attacked start defensive chaff',
                       'continue', 'start combat preparation and fire', 'are we ready for combat?'):
            self.assertIsNone(parse_workflow(phrase))


if __name__ == '__main__':
    unittest.main()

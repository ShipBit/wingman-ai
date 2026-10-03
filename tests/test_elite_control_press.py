"""Key-command semantics: synthetic adapter tests, not gameplay acceptance."""
import time
import unittest
from unittest.mock import Mock, AsyncMock

from skills.elite_dangerous_controls.runtime import ControlEngine, parse_turn, InvalidRequest


class KeyCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = {'pid': 1, 'started': time.time() - 60}
        self.backend = Mock(sent=[], context=Mock(return_value=self.context))
        self.binding = {'revision': 'bindings', 'available': {('ship', 'ShipSpotLightToggle'): {'chord': ('Key_Insert',)}}, 'unavailable': {}}
        self.resolver = Mock(stable=AsyncMock(return_value=self.binding), read=Mock(return_value=self.binding))
        self.status = {'session': 'live', 'observed': time.time(), 'revision': 'status',
                       'data': {'Flags': (1 << 24) | (1 << 8), 'GuiFocus': 0}}
        self.observe = AsyncMock(return_value=self.status)
        async def send(chord, check):
            await check()
            self.backend.sent.extend([{'inserted': 1, 'requested': 1, 'release': r} for r in (False, True)])
        self.backend.send = AsyncMock(side_effect=send)
        self.engine = ControlEngine(self.backend, self.resolver, self.observe)
        self.addAsyncCleanup(self.engine.close)

    async def test_repeated_on_and_off_always_press_regardless_of_reported_state(self):
        for index, state in enumerate(['on', 'on', 'off', 'off', 'toggle']):
            result = await self.engine.run_result('lights', state, request_id=str(index), user_text=('toggle lights' if state == 'toggle' else 'turn lights ' + state))
            self.assertEqual('input_sent', result.outcome)
            self.assertEqual('single_press', result.intent['execution'])
            self.assertEqual('Toggling lights, Commander.', result.speech)
            self.assertFalse(result.to_dict()['gameplay_verified'])
            self.assertNotIn('after', result.evidence)
        self.assertEqual(5, self.backend.send.await_count)

    async def test_does_not_read_resulting_state_after_input(self):
        async def send(chord, check):
            await check()
            self.backend.sent.extend([{'inserted': 1, 'requested': 1, 'release': r} for r in (False, True)])
            self.observe.side_effect = ValueError('No post-input observation available')
        self.backend.send.side_effect = send
        result = await self.engine.run_result('lights', 'on')
        self.assertEqual('input_sent', result.outcome)

    async def test_duplicate_call_suppressed_but_deliberate_new_call_presses(self):
        await self.engine.run_result('lights', 'on', request_id='one')
        result = await self.engine.run_result('lights', 'on', request_id='one')
        self.assertEqual('duplicate', result.outcome)
        await self.engine.run_result('lights', 'on', request_id='two')
        self.assertEqual(2, self.backend.send.await_count)

    async def test_context_and_contradiction_checks_still_prevent_input(self):
        result = await self.engine.run_result('lights', 'on', user_text='turn lights off')
        self.assertEqual('invalid', result.outcome)
        self.status['data']['GuiFocus'] = 1
        result = await self.engine.run_result('lights', 'on')
        self.assertEqual('blocked', result.outcome)
        self.backend.send.assert_not_awaited()

    def test_direct_recognition_is_bounded_and_preserves_wording_intent(self):
        for phrase in ['Turn lights on.', 'turn on the lights', 'can you turn lights on']:
            self.assertEqual(('lights', 'on', 'auto'), parse_turn(phrase))
        for phrase in ['are lights on', 'do not turn lights on', 'turn lights on and fire', 'if lights are off turn lights on']:
            with self.assertRaises(InvalidRequest):
                parse_turn(phrase)


if __name__ == '__main__':
    unittest.main()

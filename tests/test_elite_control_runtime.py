"""No game input: verify physical packets, live binding resolution and outcomes."""

import asyncio
from copy import deepcopy
import ctypes
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from skills.elite_dangerous_controls.input import WindowsInput, InputBlocked, key_event, INPUT_LOCK
from skills.elite_dangerous_controls.runtime import (ACTIONS, ACTION_IDS, BindingResolver, ControlEngine,
    InvalidRequest, normalize_request, ptt_keys, resolve_action)


class InterpretationTests(unittest.TestCase):
    def test_catalogue_and_schema_vocabulary_agree(self):
        for mode, catalog in ACTIONS.items():
            for tag, phrase in catalog.items():
                identifier = phrase.removeprefix('toggle ').replace(' ', '_')
                self.assertIn(identifier, ACTION_IDS)
                self.assertEqual(tag, resolve_action(identifier, mode))
                self.assertEqual(tag, resolve_action(tag, mode))

    def test_state_and_mode_are_preserved_from_natural_phrases(self):
        cases = [('turn on ship lights', None, 'auto', ('lights', 'on', 'ship')),
                 ('turn off night vision', None, 'ship', ('night vision', 'off', 'ship')),
                 ('ship toggle lights', 'toggle', 'auto', ('lights', 'toggle', 'ship')),
                 ('switch on the ship headlights', 'on', 'auto', ('lights', 'on', 'ship'))]
        for action, state, mode, expected in cases:
            self.assertEqual(expected, normalize_request(action, state, mode))

    def test_negations_compound_requests_and_conflicts_are_rejected(self):
        cases = [('do not turn on lights', 'toggle', 'ship'),
                 ('turn on lights and night vision', 'toggle', 'ship'),
                 ('turn on lights', 'off', 'ship'), ('srv lights', 'toggle', 'ship'),
                 ('toggle lights', 'on', 'ship'), ('lights; launch', 'toggle', 'ship')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(InvalidRequest):
                normalize_request(*args)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = self.root / "bindings"
        self.presets = self.root / "presets"
        self.bindings.mkdir()
        self.presets.mkdir()
        self.selector = self.bindings / "StartPreset.4.start"
        self.selector.write_text("Custom\n" * 4)
        self.path = self.bindings / "Custom.4.2.binds"
        self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_Insert"/></ShipSpotLightToggle>'
                 '<NightVisionToggle><Primary Device="Keyboard" Key="Key_Numpad_Subtract"/></NightVisionToggle>')
        self.resolver = BindingResolver(self.bindings, self.presets, {"record_key": "end"})

    def xml(self, content):
        self.path.write_text('<Root PresetName="Custom" MajorVersion="4" MinorVersion="2">' + content + '</Root>')


class ResolverTests(Fixture):
    def test_modifier_press_conflicts_with_ui_focus_and_safe_primary_survives(self):
        self.xml('<UIFocus><Primary Device="Keyboard" Key="Key_LeftShift"/></UIFocus>'
                 '<GalaxyMapOpen><Primary Device="{NoDevice}" Key=""/>'
                 '<Secondary Device="Keyboard" Key="Key_F10">'
                 '<Modifier Device="Keyboard" Key="Key_LeftControl"/>'
                 '<Modifier Device="Keyboard" Key="Key_LeftShift"/></Secondary></GalaxyMapOpen>')
        result = self.resolver.read()
        self.assertIn('UIFocus', result['unavailable'][('ship', 'GalaxyMapOpen')])
        self.path.write_text(self.path.read_text().replace(
            '<Primary Device="{NoDevice}" Key=""/>', '<Primary Device="Keyboard" Key="Key_Numpad_Divide"/>'))
        result = self.resolver.read()
        self.assertEqual(('Key_Numpad_Divide',), result['available'][('ship', 'GalaxyMapOpen')]['chord'])

    def test_modifier_conflicts_respect_vehicle_and_ui_context(self):
        self.xml('<HumanoidSprintButton><Primary Device="Keyboard" Key="Key_LeftShift"/></HumanoidSprintButton>'
                 '<UI_Up><Primary Device="Keyboard" Key="Key_RightControl"/></UI_Up>'
                 '<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_L">'
                 '<Modifier Device="Keyboard" Key="Key_LeftShift"/>'
                 '<Modifier Device="Keyboard" Key="Key_RightControl"/></Primary></ShipSpotLightToggle>')
        self.assertIn(('ship', 'ShipSpotLightToggle'), self.resolver.read()['available'])

    def test_unknown_standalone_modifier_control_is_conservatively_blocked(self):
        self.xml('<UnknownControl><Primary Device="Keyboard" Key="Key_LeftControl"/></UnknownControl>'
                 '<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_L">'
                 '<Modifier Device="Keyboard" Key="Key_LeftControl"/></Primary></ShipSpotLightToggle>')
        self.assertIn('UnknownControl', self.resolver.read()['unavailable'][('ship', 'ShipSpotLightToggle')])

    def test_extended_and_keypad_stay_physical(self):
        self.assertEqual({"scan": 82, "flags": 9}, key_event("Key_Insert"))
        self.assertEqual({"scan": 74, "flags": 8}, key_event("Key_Numpad_Subtract"))
        self.assertEqual({"scan": 82, "flags": 11}, key_event("Key_Insert", True))
        self.assertEqual({"scan": 82, "flags": 8}, key_event("Key_Numpad_0"))
        self.assertEqual({"scan": 29, "flags": 9}, key_event("Key_RightControl"))

    def test_preset_switch_and_edit_are_detected(self):
        first = self.resolver.read()
        self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_L"/></ShipSpotLightToggle>')
        second = self.resolver.read()
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(('Key_L',), second['available'][('ship', 'ShipSpotLightToggle')]['chord'])
        (self.presets / 'Pad.binds').write_text('<Root PresetName="Pad"><ShipSpotLightToggle>'
            '<Primary Device="GamePad" Key="Joy_1"/><Secondary Device="Keyboard" Key="Key_K"/>'
            '</ShipSpotLightToggle></Root>')
        self.selector.write_text('Custom\nPad\nCustom\nCustom\n')
        self.assertEqual(('Key_K',), self.resolver.read()['available'][('ship', 'ShipSpotLightToggle')]['chord'])

    def test_partial_write_never_uses_old_mapping(self):
        self.resolver.read()
        self.path.write_text('<Root')
        with self.assertRaises(Exception):
            self.resolver.read()

    def test_controller_primary_retained_and_secondary_chord_selected(self):
        self.xml('<ShipSpotLightToggle><Primary Device="HOTAS" Key="Joy_3"/>'
                 '<Secondary Device="Keyboard" Key="Key_L"><Modifier Device="Keyboard" Key="Key_RightControl"/></Secondary>'
                 '</ShipSpotLightToggle>')
        entry = self.resolver.read()['available'][('ship', 'ShipSpotLightToggle')]
        self.assertEqual(('Key_RightControl', 'Key_L'), entry['chord'])
        self.assertEqual('Secondary', entry['slot'])

    def test_ptt_scan_codes_and_named_modifiers_are_excluded(self):
        self.assertIn('Key_Insert', ptt_keys({'record_key_codes': [82]}))
        self.assertEqual({'Key_LeftControl', 'Key_RightControl', 'Key_End'}, ptt_keys({'record_key':'ctrl+end'}))
        self.assertEqual({'Key_Numpad_Add'}, ptt_keys({'record_key':'num +'}))
        self.assertEqual({'Key_Numpad_1'}, ptt_keys({'record_key':'num 1'}))
        self.resolver.config = {'record_key': 'insert'}
        self.assertNotIn(('ship','ShipSpotLightToggle'), self.resolver.read()['available'])

    def test_ui_reuse_allowed_but_same_context_conflict_blocked(self):
        self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_Insert"/></ShipSpotLightToggle>'
                 '<CyclePreviousPage><Primary Device="Keyboard" Key="Key_Insert"/></CyclePreviousPage>')
        self.assertIn(('ship','ShipSpotLightToggle'), self.resolver.read()['available'])
        self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_Insert"/></ShipSpotLightToggle>'
                 '<DeployHardpointToggle><Primary Device="Keyboard" Key="Key_Insert"/></DeployHardpointToggle>')
        self.assertIn('overlaps', self.resolver.read()['unavailable'][('ship','ShipSpotLightToggle')])


class EngineTests(unittest.IsolatedAsyncioTestCase, Fixture):
    async def asyncSetUp(self):
        self.observation = {'session':'session1', 'observed':time.time(), 'revision':'before',
                            'data':{'Flags':1 << 24, 'Flags2':0, 'GuiFocus':0}}
        self.context = {'pid':1, 'started':time.time() - 20}
        self.backend = Mock(sent=[], context=Mock(side_effect=lambda: self.context))
        async def send(chord, check):
            await check()
            self.backend.sent.append({'inserted':1})
            if self.change:
                self.observation['data']['Flags'] ^= 1 << 8
                self.observation['revision'] = 'after'
        self.backend.send = AsyncMock(side_effect=send)
        self.change = True
        async def observe():
            return deepcopy(self.observation)
        self.audit = []
        # State-aware internal primitive: distinct from spoken single-press commands.
        self.engine = ControlEngine(self.backend, self.resolver, observe, self.audit.append, timeout=0.12, single_press=False)
        self.addAsyncCleanup(self.engine.close)

    async def test_verified_on_and_repeated_on_send_once(self):
        self.assertEqual('Confirmed: lights on.', await self.engine.run('lights','on'))
        self.assertEqual('Already set: lights on.', await self.engine.run('lights','on'))
        self.assertEqual(1, self.backend.send.await_count)
        self.assertIn('after', self.audit[0])

    async def test_historical_conflicting_payload_is_rejected_without_overriding_toggle(self):
        self.assertEqual('Confirmed: lights on.', await self.engine.run('turn on ship lights', 'on', 'ship'))
        self.assertTrue((await self.engine.run('turn on ship lights', 'toggle', 'ship')).startswith('Invalid request:'))
        self.assertEqual(1, self.backend.send.await_count)
        self.assertEqual('ShipSpotLightToggle', self.audit[0]['tag'])
        self.assertFalse(self.audit[1]['input_attempted'])

    async def test_explicit_toggle_inverts_both_states(self):
        first = await self.engine.run_result('lights', 'toggle')
        self.observation['revision'] = 'second-before'
        second = await self.engine.run_result('lights', 'toggle')
        self.assertEqual(['confirmed', 'confirmed'], [first.outcome, second.outcome])
        self.assertEqual(['Confirmed: lights on.', 'Confirmed: lights off.'], [first.speech, second.speech])

    async def test_duplicate_id_no_replay_but_new_request_executes(self):
        first = await self.engine.run_result('lights', 'toggle', request_id='turn1:call1')
        duplicate = await self.engine.run_result('lights', 'toggle', request_id='turn1:call1')
        self.assertEqual('confirmed', first.outcome)
        self.assertEqual('duplicate', duplicate.outcome)
        self.assertFalse(duplicate.input_events)
        self.observation['revision'] = 'second-before'
        await self.engine.run_result('lights', 'toggle', request_id='turn2:call1')
        self.assertEqual(2, self.backend.send.await_count)

    async def test_originating_turn_mismatch_negation_and_stale_turn_send_nothing(self):
        for text, state in [('turn off lights', 'on'), ('do not turn on lights', 'on'),
                            ('lights', 'toggle'), ('turn on lights and night vision', 'on')]:
            result = await self.engine.run_result('lights', state, user_text=text)
            self.assertEqual('invalid', result.outcome)
            self.assertEqual('user_intent', result.first_failing_stage)
        stale = await self.engine.run_result('lights', 'on', user_text='turn on lights', still_current=lambda: False)
        self.assertEqual('invalid', stale.outcome)
        self.backend.send.assert_not_awaited()

    async def test_partial_input_has_attempt_information_and_never_confirms(self):
        async def partial(chord, check):
            self.backend.sent.extend([{'inserted': 1}, {'inserted': 0}])
            raise OSError('second packet failed')
        self.backend.send.side_effect = partial
        result = await self.engine.run_result('lights', 'on')
        self.assertEqual('unverified', result.outcome)
        self.assertEqual('input', result.first_failing_stage)
        self.assertTrue(result.to_dict()['windows_accepted'])
        self.assertFalse(result.to_dict()['gameplay_verified'])

    async def test_local_cancel_records_and_releases_lock(self):
        started = asyncio.Event()
        async def pending(chord, check):
            started.set()
            await asyncio.sleep(30)
        self.backend.send.side_effect = pending
        task = asyncio.create_task(self.engine.run_result('lights', 'on', request_id='cancelled'))
        await started.wait()
        self.engine.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual('cancelled', self.audit[-1]['outcome'])
        self.assertFalse(INPUT_LOCK.locked())
        result = await self.engine.run_result('lights', 'on', request_id='cancelled')
        self.assertEqual('duplicate', result.outcome)

    async def test_invalid_request_has_distinct_result_and_sends_nothing(self):
        self.assertTrue((await self.engine.run('turn on lights', 'off')).startswith('Invalid request:'))
        self.backend.send.assert_not_awaited()
        self.backend.context.assert_not_called()

    async def test_hold_action_does_not_disable_lights(self):
        self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_Insert"/></ShipSpotLightToggle>'
                 '<ToggleDriveAssist><Primary Device="Keyboard" Key="Key_D"/><ToggleOn Value="0"/></ToggleDriveAssist>')
        self.assertEqual('Confirmed: lights on.', await self.engine.run('turn on ship lights'))
        self.assertIn('Configured as hold', self.resolver.read()['unavailable'][('srv', 'ToggleDriveAssist')])

    async def test_unchanged_status_is_unverified_without_retry(self):
        self.change = False
        self.assertTrue((await self.engine.run('lights','on')).startswith('Unverified:'))
        self.assertEqual(1, self.backend.send.await_count)

    async def test_same_timestamp_changed_bytes_can_confirm(self):
        before = self.observation['observed']
        self.assertTrue((await self.engine.run('lights','on')).startswith('Confirmed:'))
        self.assertEqual(before, self.observation['observed'])

    async def test_wrong_mode_menu_old_process_status_and_missing_focus_block(self):
        self.assertTrue((await self.engine.run('lights','on','srv')).startswith('Blocked:'))
        self.observation['data']['GuiFocus']=1
        self.assertTrue((await self.engine.run('lights','on')).startswith('Blocked:'))
        self.observation['data']['GuiFocus']=0
        self.observation['observed']=0
        self.assertTrue((await self.engine.run('lights','on')).startswith('Blocked:'))
        self.backend.context.side_effect=InputBlocked('Focus Elite')
        self.assertTrue((await self.engine.run('lights','on')).startswith('Blocked:'))
        self.backend.send.assert_not_awaited()

    async def test_binding_change_during_execution_does_not_send(self):
        async def send(chord, check):
            self.xml('<ShipSpotLightToggle><Primary Device="Keyboard" Key="Key_L"/></ShipSpotLightToggle>')
            await check()
            self.fail('must not send after binding change')
        self.backend.send.side_effect=send
        self.assertIn('Bindings changed',await self.engine.run('lights','on'))

    async def test_focus_lost_while_observing_sends_no_input(self):
        calls = 0
        async def observe():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.backend.context.side_effect = InputBlocked('Focus Elite')
            return deepcopy(self.observation)
        self.engine.observe = observe
        result = await self.engine.run_result('lights', 'on')
        self.assertEqual('blocked', result.outcome)
        self.assertEqual('prerequisites', result.first_failing_stage)
        self.backend.send.assert_not_awaited()

    async def test_new_turn_while_observing_sends_no_input(self):
        current = True
        calls = 0
        async def observe():
            nonlocal calls, current
            calls += 1
            if calls == 2:
                current = False
            return deepcopy(self.observation)
        self.engine.observe = observe
        result = await self.engine.run_result('lights', 'on', still_current=lambda: current)
        self.assertEqual('blocked', result.outcome)
        self.backend.send.assert_not_awaited()

    async def test_delayed_observation_and_session_change(self):
        self.change=False
        tasks=[]
        async def change():
            await asyncio.sleep(0.03)
            self.observation['data']['Flags'] |= 1 << 8
            self.observation['revision']='late'
        async def delayed_send(chord,check):
            await check()
            self.backend.sent.append({'inserted':1})
            tasks.append(asyncio.create_task(change()))
        self.backend.send.side_effect=delayed_send
        self.engine.timeout=0.4
        self.assertTrue((await self.engine.run('lights','on')).startswith('Confirmed:'))
        await asyncio.gather(*tasks)
        self.observation['data']['Flags'] &= ~(1<<8)
        async def send(chord, check):
            self.backend.sent.append({'inserted':1})
            self.observation['session']='changed'
        self.backend.send.side_effect=send
        self.assertTrue((await self.engine.run('lights','on')).startswith('Unverified:'))

    async def test_concurrent_command_rejected_and_unload_cancels(self):
        started=asyncio.Event()
        async def send(chord, check):
            started.set()
            await asyncio.sleep(20)
        self.backend.send.side_effect=send
        task=asyncio.create_task(self.engine.run('lights','on'))
        await started.wait()
        self.assertIn('in progress',await self.engine.run('lights','on'))
        await self.engine.close()
        self.assertTrue(task.cancelled())
        self.assertFalse(INPUT_LOCK.locked())

    async def test_injection_exception_never_confirms(self):
        self.backend.send.side_effect=OSError('injection failed')
        self.assertNotIn('Confirmed',await self.engine.run('lights','on'))


class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_releases_only_owned_keys_in_reverse(self):
        backend=WindowsInput.__new__(WindowsInput)
        backend.held=Mock(return_value=False)
        backend._send=Mock()
        task=asyncio.create_task(backend.send(('Key_LeftControl','Key_Insert'),AsyncMock()))
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual([(('Key_LeftControl',),{}),(('Key_Insert',),{}),
                          (('Key_Insert',True),{}),(('Key_LeftControl',True),{})],backend._send.call_args_list)

    async def test_failed_keydown_releases_prior_modifier(self):
        backend=WindowsInput.__new__(WindowsInput)
        backend.held=Mock(return_value=False)
        backend._send=Mock(side_effect=[None,OSError('fail'),None])
        with self.assertRaises(OSError):
            await backend.send(('Key_LeftControl','Key_Insert'),AsyncMock())
        self.assertEqual(('Key_LeftControl',True),backend._send.call_args_list[-1].args)

    async def test_physically_held_modifier_prevents_injection(self):
        backend=WindowsInput.__new__(WindowsInput)
        backend.held=Mock(side_effect=lambda key:key=='Key_LeftControl')
        backend._send=Mock()
        with self.assertRaises(InputBlocked): await backend.send(('Key_Insert',),AsyncMock())
        backend._send.assert_not_called()

    @unittest.skipUnless(__import__('platform').system()=='Windows','Windows packet structures')
    async def test_native_packet_abi_and_failed_send(self):
        backend=WindowsInput()
        packets=[]
        def sent(count,pointer,size):
            packet=ctypes.cast(pointer,ctypes.POINTER(backend.Input)).contents
            packets.append((packet.keyboard.vk,packet.keyboard.scan,packet.keyboard.flags,size))
            return 1
        with patch.object(backend.user,'SendInput',side_effect=sent):
            backend._send('Key_Insert')
            backend._send('Key_Numpad_Subtract',True)
        self.assertEqual([(0,82,9,40),(0,74,10,40)],packets)
        with patch.object(backend.user,'SendInput',return_value=0):
            with self.assertRaises(OSError): backend._send('Key_Insert')


if __name__=='__main__':
    unittest.main()

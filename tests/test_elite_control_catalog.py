"""Every catalog action through real Core dispatch/skill/controller; OS/game are doubles.

These are synthetic regressions, not claims of observed gameplay or recognition
by a particular speech-to-text provider.
"""
import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import yaml
from api.interface import SkillConfig
from services.pub_sub import PubSub
from skills.elite_dangerous_controls.catalog import BY_MODE_TAG, CATALOG
from skills.elite_dangerous_controls.main import EliteDangerousControls, runtime, inputs, telemetry
from test_tool_execution_context import method


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.data = {'Flags': 1 << 24, 'Flags2': 0, 'GuiFocus': 0}
        self.context = {'pid': 1, 'started': time.time() - 100}
        self.backend = Mock(sent=[], context=Mock(return_value=self.context))
        self.snapshot = {'revision': 'bindings', 'available': {
            (mode, tag): {'chord': (('Key_Numpad_Divide' if tag.startswith('GalaxyMapOpen') else
                                    'Key_Numpad_Multiply' if tag.startswith('SystemMapOpen') else 'Key_Insert'),)}
            for mode, catalog in runtime.ACTIONS.items() for tag in catalog}, 'unavailable': {}}
        self.resolver = Mock(stable=AsyncMock(return_value=self.snapshot), read=Mock(return_value=self.snapshot))
        async def observe():
            return {'session': 'test', 'revision': str(self.data['GuiFocus']), 'observed': time.time(), 'data': dict(self.data)}
        async def send(chord, check):
            await check()
            self.backend.sent.extend([{'inserted': 1, 'requested': 1, 'release': release} for release in (False, True)])
            focus = {'Key_Numpad_Divide': 6, 'Key_Numpad_Multiply': 7}.get(chord[-1])
            if focus:
                self.data['GuiFocus'] = 0 if self.data['GuiFocus'] == focus else focus
        self.backend.send = AsyncMock(side_effect=send)
        self.engine = runtime.ControlEngine(self.backend, self.resolver, observe, self.events.append)
        self.addAsyncCleanup(self.engine.close)
        self.wingman = SimpleNamespace(name='Test', audio_player=SimpleNamespace(event_loop=asyncio.get_running_loop()),
            messages=[], _cleanup_conversation_history=AsyncMock(), add_assistant_message=AsyncMock(),
            _llm_call=AsyncMock(), _try_instant_activation=AsyncMock(),
            skill_registry=SimpleNamespace(activate_skill=AsyncMock(return_value=(True, 'ready', True))))
        config = SkillConfig.model_validate(yaml.safe_load(Path('skills/elite_dangerous_controls/default_config.yaml').read_text()))
        with patch('skills.skill_base.Printr', return_value=SimpleNamespace(print=Mock(), print_async=AsyncMock())), \
             patch('skills.skill_base.SecretKeeper', return_value=SimpleNamespace(secret_events=PubSub())):
            self.skill = EliteDangerousControls(config, SimpleNamespace(debug_mode=False), self.wingman)
        self.addAsyncCleanup(self.skill.unload)
        self.skill.ensure_activated = AsyncMock(return_value=(True, 'ready'))
        async def execute(action, state, mode, request=None):
            self.engine.requests.clear()  # Production executor keeps duplicate receipts within each turn.
            return await self.engine.run(action, state, mode, **(request or {}))
        self.skill._execute = execute
        self.wingman.skills = [self.skill]
        self.wingman.add_user_message = lambda text: method('add_user_message')(self.wingman, text)
        self.wingman._try_direct_skill_request = lambda text, bench: method('_try_direct_skill_request')(self.wingman, text, bench)

    def mode(self, mode):
        self.data.update(Flags={'ship': 1 << 24, 'srv': 1 << 26, 'on_foot': 0}[mode],
                         Flags2=1 if mode == 'on_foot' else 0)

    async def test_every_catalog_action_routes_twice_through_core_skill_and_controller(self):
        count = 0
        for mode, catalog in runtime.ACTIONS.items():
            self.mode(mode)
            for tag, phrase in catalog.items():
                metadata = BY_MODE_TAG[(mode, tag)]
                self.data["GuiFocus"] = min(metadata.contexts)
                self.data["Flags"] |= (1 << 4) if metadata.supercruise_only else 0
                for spoken in (phrase, 'please ' + mode.replace('_', ' ') + ' ' + phrase):
                    with self.subTest(mode=mode, action=tag, spoken=spoken):
                        previous = self.backend.send.await_count
                        result = await method('_get_response_for_transcript')(self.wingman, spoken, Mock())
                        self.assertEqual(previous + 1, self.backend.send.await_count)
                        is_map = metadata.id in ('galaxy_map', 'system_map')
                        self.assertEqual('confirmed' if is_map else 'input_sent', self.events[-1]['outcome'])
                        self.assertEqual(tag, self.events[-1]['evidence']['tag'])
                        self.assertEqual(mode, self.events[-1]['evidence']['mode'])
                        self.assertEqual(result[0], self.events[-1]['speech'])
                        self.assertEqual(result[0], result[1])
                        self.assertEqual(is_map, 'Confirmed' in result[0])
                        self.assertNotIn('key sent', result[0])
                        self.assertEqual(is_map, self.events[-1]['gameplay_verified'])
                count += 1
        self.assertEqual(len(CATALOG), count)
        self.assertGreater(count, 100)
        self.wingman._llm_call.assert_not_awaited()
        self.wingman._try_instant_activation.assert_not_awaited()

    async def test_all_toggle_wordings_press_each_time_and_only_maps_wait_for_after_state(self):
        for mode, catalog in runtime.ACTIONS.items():
            self.mode(mode)
            for tag, phrase in catalog.items():
                if not phrase.startswith('toggle '):
                    continue
                action = phrase.removeprefix('toggle ')
                self.data["GuiFocus"] = min(BY_MODE_TAG[(mode, tag)].contexts)
                for state in ('on', 'on', 'off', 'off', 'toggle'):
                    spoken = ('toggle ' + action) if state == 'toggle' else ('turn ' + action + ' ' + state)
                    with self.subTest(mode=mode, action=tag, state=state):
                        previous = self.backend.send.await_count
                        result = await self.engine.run_result(action, state, mode, user_text=spoken)
                        is_map = action in ('galaxy map', 'system map')
                        self.assertEqual('confirmed' if is_map else 'input_sent', result.outcome)
                        self.assertEqual(previous + 1, self.backend.send.await_count)
                        self.assertEqual(is_map, 'after' in result.evidence)
                        self.assertEqual(tag, result.evidence['tag'])

    async def test_common_cockpit_phrases_follow_the_same_controller_path(self):
        phrases = {**runtime.SPOKEN_ACTIONS, 'activate night vision': 'turn on night vision',
                   'deactivate lights': 'turn off lights'}
        for spoken, canonical in phrases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(runtime.parse_turn(canonical), runtime.parse_turn(spoken))
                result = await method('_get_response_for_transcript')(self.wingman, spoken, Mock())
                is_map = 'map' in spoken
                self.assertEqual('confirmed' if is_map else 'input_sent', self.events[-1]['outcome'])
                self.assertEqual(result[0], self.events[-1]['speech'])
        self.wingman._llm_call.assert_not_awaited()

    async def test_every_entry_rechecks_binding_cancellation_and_duplicate_delivery(self):
        for entry in CATALOG:
            with self.subTest(vehicle=entry.vehicle, action=entry.id):
                self.engine.requests.clear()
                self.mode(entry.vehicle)
                self.data['GuiFocus'] = min(entry.contexts)
                if entry.supercruise_only:
                    self.data['Flags'] |= 1 << 4
                before = self.backend.send.await_count
                self.resolver.read.return_value = {**self.snapshot, 'revision': 'changed'}
                result = await self.engine.run_result(entry.id, mode=entry.vehicle)
                self.assertEqual('blocked', result.outcome)
                self.resolver.read.return_value = self.snapshot
                result = await self.engine.run_result(entry.id, mode=entry.vehicle, still_current=lambda: False)
                self.assertEqual('invalid', result.outcome)
                self.assertEqual(before, self.backend.send.await_count)
                result = await self.engine.run_result(entry.id, mode=entry.vehicle, request_id='one')
                self.assertEqual('confirmed' if entry.id in ('galaxy_map', 'system_map') else 'input_sent', result.outcome)
                result = await self.engine.run_result(entry.id, mode=entry.vehicle, request_id='one')
                self.assertEqual('duplicate', result.outcome)
                self.assertEqual(before + 1, self.backend.send.await_count)

    async def test_production_executor_finishes_input_before_ai_and_never_retries_on_ai_failure(self):
        self.context['presets'] = 'unused-presets'
        self.wingman.config = SimpleNamespace(model_dump=lambda: {'record_key': 'F10'})
        self.skill._property = lambda name: ''
        self.skill._observe = self.engine.observe
        async def model(messages, tools=None):
            self.assertIsNone(tools)
            self.assertEqual(1, self.backend.send.await_count)
            self.assertTrue(self.backend.sent[-1]['release'])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content='Copy that, Commander.', tool_calls=None))])
        self.skill.llm_call = AsyncMock(side_effect=model)
        with patch.object(inputs, 'WindowsInput', return_value=self.backend), \
             patch.object(runtime, 'BindingResolver', return_value=self.resolver), \
             patch.object(telemetry, 'JournalReader'):
            response = await EliteDangerousControls._execute(self.skill, 'lights', 'on', 'ship')
            self.assertEqual('Copy that, Commander.', response)
            self.skill.llm_call.side_effect = RuntimeError('Provider unavailable')
            response = await EliteDangerousControls._execute(self.skill, 'lights', 'on', 'ship')
            self.assertEqual(2, self.backend.send.await_count)
            self.assertNotIn('key sent', response)
            self.data['GuiFocus'] = 3
            await EliteDangerousControls._execute(self.skill, 'lights', 'on', 'ship')
            self.assertEqual(2, self.backend.send.await_count)
            self.assertEqual(2, self.skill.llm_call.await_count)

    async def test_entire_catalog_blocks_chat_wrong_vehicle_missing_binding_and_negation(self):
        for mode, catalog in runtime.ACTIONS.items():
            self.mode(mode)
            for tag, phrase in catalog.items():
                self.engine.requests.clear()  # Each set models fresh user turns.
                action = phrase.removeprefix('toggle ')
                with self.subTest(mode=mode, action=tag):
                    previous = self.backend.send.await_count
                    self.data['GuiFocus'] = 3
                    result = await self.engine.run_result(action, mode=mode)
                    self.assertEqual('blocked', result.outcome)
                    self.data['GuiFocus'] = 0
                    result = await self.engine.run_result(action, mode='ship' if mode != 'ship' else 'srv')
                    self.assertEqual('blocked', result.outcome)
                    binding = self.snapshot['available'].pop((mode, tag))
                    self.snapshot['unavailable'][(mode, tag)] = 'No suitable binding'
                    result = await self.engine.run_result(action, mode=mode)
                    self.assertEqual('blocked', result.outcome)
                    self.snapshot['available'][(mode, tag)] = binding
                    self.snapshot['unavailable'].pop((mode, tag))
                    result = await self.engine.run_result(action, mode=mode, user_text='do not ' + phrase)
                    self.assertEqual('invalid', result.outcome)
                    self.assertIsNone(self.skill.resolve_direct_request('do not ' + phrase))
                    self.assertEqual(previous, self.backend.send.await_count)


if __name__ == '__main__':
    unittest.main()

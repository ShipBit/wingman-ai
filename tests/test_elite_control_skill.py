"""Real skill schema and lifecycle, with input and game state replaced by doubles."""

import asyncio
from datetime import datetime, timezone
from importlib import util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock, patch
import yaml

from api.interface import SkillConfig
from services.pub_sub import PubSub
from skills.elite_dangerous_controls.main import EliteDangerousControls
from services.tool_execution import begin_turn, tool_call_scope


class SkillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.printr=SimpleNamespace(print=Mock(),print_async=AsyncMock())
        self.wingman=SimpleNamespace(name='Test',audio_player=SimpleNamespace(event_loop=asyncio.get_running_loop()))
        config=SkillConfig.model_validate(yaml.safe_load(Path('skills/elite_dangerous_controls/default_config.yaml').read_text()))
        with patch('skills.skill_base.Printr',return_value=self.printr),patch('skills.skill_base.SecretKeeper',return_value=SimpleNamespace(secret_events=PubSub())):
            self.skill=EliteDangerousControls(config,SimpleNamespace(debug_mode=False),self.wingman)
        self.addAsyncCleanup(self.skill.unload)

    def test_direct_phrase_recognizer_does_not_need_prepared_state(self):
        self.assertFalse(self.skill.is_prepared)
        self.assertEqual(('elite_control', {'action': 'lights', 'state': 'on', 'mode': 'auto'}),
                         self.skill.resolve_direct_request('Turn lights on.'))
        self.assertEqual(('elite_control', {'action': 'night_vision', 'state': 'off', 'mode': 'auto'}),
                         self.skill.resolve_direct_request('turn off night vision'))
        self.assertIsNone(self.skill.resolve_direct_request('Are my lights on?'))
        self.assertIsNone(self.skill.resolve_direct_request('do not turn lights on'))

    async def test_schema_two_progressive_tools_and_native_instant_result(self):
        self.assertFalse(self.skill.config.auto_activate)
        self.assertEqual(['elite_control', 'elite_workflow'],list(self.skill._decorated_tools))
        self.assertFalse(await self.skill.is_summarize_needed('elite_control'))
        schema = self.skill.get_tools()[0][1]['function']['parameters']['properties']
        self.assertEqual('string', schema['action']['type'])
        self.assertNotIn('authorization', schema)
        self.assertNotIn('enum', schema['action'])  # Compact tools; catalog lives only in routing.
        self.assertIn('state', self.skill.get_tools()[0][1]['function']['parameters']['required'])
        begin_turn(self.wingman, 'turn on lights')
        with patch.object(self.skill,'_execute',new=AsyncMock(return_value='Unverified: input sent.')) as execute:
            with tool_call_scope('test-call'):
                result=await asyncio.to_thread(lambda:asyncio.run(self.skill.elite_control('lights','on')))
        self.assertEqual(('Unverified: input sent.','Unverified: input sent.'),result)
        self.assertEqual(('lights', 'on', 'auto'), execute.await_args.args[:3])
        self.assertEqual('turn on lights', execute.await_args.args[3]['user_text'])

    async def test_actual_tool_dispatch_rejects_conflicting_historical_payload(self):
        begin_turn(self.wingman, 'turn on ship lights')
        with patch.object(self.skill, '_execute', new=AsyncMock(return_value='Confirmed: lights on.')) as execute:
            with tool_call_scope('historical'):
                result = await self.skill._decorated_tools['elite_control'].execute(
                    {'action': 'turn on ship lights', 'state': 'toggle', 'mode': 'ship'}, self.skill)
        execute.assert_not_awaited()
        self.assertTrue(result[0].startswith('Invalid request:'))

    async def test_cold_activation_uses_turn_captured_before_skill_hook(self):
        begin_turn(self.wingman, 'turn off night vision')
        # No on_add_user_message hook was delivered to this unprepared skill.
        with patch.object(self.skill, '_execute', new=AsyncMock()) as execute:
            with tool_call_scope('cold'):
                result = await self.skill.elite_control('night_vision', 'on')
        execute.assert_not_awaited()
        self.assertTrue(result[0].startswith('Invalid request:'))

    async def test_missing_provenance_never_executes(self):
        with patch.object(self.skill, '_execute', new=AsyncMock()) as execute:
            result = await self.skill.elite_control('lights', 'on')
        execute.assert_not_awaited()
        self.assertTrue(result[0].startswith('Invalid request:'))

    async def test_escape_before_engine_creation_invalidates_pending_turn(self):
        begin_turn(self.wingman, 'turn on lights')
        self.skill._cancel()
        with patch.object(self.skill, '_execute', new=AsyncMock()) as execute:
            with tool_call_scope('late-after-escape'):
                result = await self.skill.elite_control('lights', 'on')
        execute.assert_not_awaited()
        self.assertEqual(('', ''), result)  # Escape also suppresses a stale reply.

    async def test_prepare_persistent_loop_and_unload(self):
        with patch('keyboard.keyboard.on_press_key', return_value=None):
            await asyncio.to_thread(lambda:asyncio.run(self.skill.prepare()))
        watcher=self.skill._watcher
        self.assertIs(watcher.get_loop(),asyncio.get_running_loop())
        await asyncio.to_thread(lambda:asyncio.run(self.skill.unload()))
        self.assertTrue(watcher.cancelled())

    async def test_observation_rejects_shutdown_partial_and_wrong_session(self):
        now=datetime.now(timezone.utc).isoformat()
        reader=SimpleNamespace(directory=self.root,refresh=Mock(),running=True,catch_up=False,galaxy='live',session_started='2000-01-01T00:00:00Z')
        self.skill._reader=reader
        path=self.root/'Status.json'
        path.write_text(json.dumps({'event':'Status','timestamp':now,'Flags':1<<24,'GuiFocus':0}))
        result=await self.skill._observe()
        self.assertEqual(reader.session_started,result['session'])
        reader.running=False
        with self.assertRaises(ValueError):await self.skill._observe()
        reader.running=True
        reader.session_started='2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):await self.skill._observe()
        path.write_text('{')
        with self.assertRaises(ValueError):await self.skill._observe()

    async def test_non_windows_control_request_is_graceful(self):
        with patch('skills.elite_dangerous_controls.main.platform.system',return_value='Darwin'):
            self.assertIn('require Windows',await self.skill._execute('lights','on','auto'))

    async def test_model_callback_is_resolved_after_core_injects_it(self):
        from skills.elite_dangerous_controls.main import runtime
        self.skill.llm_call = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='Copy that, Commander.', tool_calls=None))]))
        result = runtime.ControlResult('id', {'action': 'lights'}, 'input_sent', 'Lights key sent.')
        self.assertEqual('Copy that, Commander.', await self.skill._speech.acknowledge(result))
        self.skill.llm_call.assert_awaited_once()

    async def test_unload_during_response_generation_suppresses_late_speech(self):
        begin_turn(self.wingman, 'turn on lights')
        async def execute(*args):
            self.skill._stopping = True
            return 'Copy that, Commander.'
        with patch.object(self.skill, '_execute', side_effect=execute):
            with tool_call_scope('pending-speech'):
                result = await self.skill.elite_control('lights', 'on')
        self.assertEqual(('', ''), result)
        self.printr.print_async.assert_not_awaited()

    async def test_workflow_tool_checks_origin_and_cancel_works_without_game_focus(self):
        self.assertEqual(('elite_workflow', {'operation': 'start', 'workflow': 'combat_preparation'}),
                         self.skill.resolve_direct_request('prepare for combat'))
        self.skill._workflow = SimpleNamespace(handle=AsyncMock(return_value='Cancelled, Commander.'), close=AsyncMock())
        begin_turn(self.wingman, 'cancel workflow')
        with tool_call_scope('cancel'):
            result = await self.skill.elite_workflow('cancel')
        self.assertEqual(('Cancelled, Commander.', 'Cancelled, Commander.'), result)
        with tool_call_scope('wrong'):
            result = await self.skill.elite_workflow('start', 'defensive_chaff')
        self.assertIn('No step was started', result[0])
        self.skill._workflow.handle.assert_awaited_once()

    async def test_custom_filename_loader_works(self):
        spec=util.spec_from_file_location('custom_elite_controls',Path('skills/elite_dangerous_controls/main.py'))
        module=util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual('EliteDangerousControls',module.EliteDangerousControls.__name__)


if __name__=='__main__':unittest.main()

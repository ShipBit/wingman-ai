"""Exercise Core's actual user-turn and dispatch methods without provider startup."""

import ast
import asyncio
import json
from pathlib import Path
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from services.tool_execution import begin_turn, current_turn, current_call, tool_call_scope


def method(name):
    tree = ast.parse(Path('wingmen/open_ai_wingman.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OpenAiWingman')
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    scope = dict(begin_turn=begin_turn, tool_call_scope=tool_call_scope, json=json, time=time,
                 Benchmark=object, Skill=object, printr=Mock(), LogType=SimpleNamespace(ERROR='error'), traceback=traceback)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'wingmen/open_ai_wingman.py', 'exec'), scope)
    return scope[name]


class CoreContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_phrase_activates_cold_skill_and_bypasses_model_and_legacy_commands(self):
        skill = SimpleNamespace(name='EliteDangerousControls', is_prepared=False,
                  on_add_user_message=AsyncMock(), resolve_direct_request=lambda text: ('elite_control', {'action': 'lights', 'state': 'on'}),
                  ensure_activated=AsyncMock(return_value=(True, 'ready')))
        seen = []
        async def execute(*args):
            seen.append((current_turn.get(), current_call.get()))
            return 'Toggling lights, Commander.', 'Toggling lights, Commander.'
        skill.execute_tool = AsyncMock(side_effect=execute)
        wingman = SimpleNamespace(skills=[skill], messages=[], _cleanup_conversation_history=AsyncMock(),
            skill_registry=SimpleNamespace(activate_skill=AsyncMock(return_value=(True, 'ready', True))),
            add_assistant_message=AsyncMock(), _llm_call=AsyncMock(), _try_instant_activation=AsyncMock())
        wingman.add_user_message = lambda text: method('add_user_message')(wingman, text)
        wingman._try_direct_skill_request = lambda text, bench: method('_try_direct_skill_request')(wingman, text, bench)
        for _ in range(2):
            result = await method('_get_response_for_transcript')(wingman, 'turn lights on', Mock())
            self.assertEqual(('Toggling lights, Commander.', 'Toggling lights, Commander.', skill, True), result)
        self.assertNotEqual(seen[0][0].id, seen[1][0].id)
        self.assertEqual(['direct', 'direct'], [s[1] for s in seen])
        wingman._llm_call.assert_not_awaited()
        wingman._try_instant_activation.assert_not_awaited()
        self.assertEqual(2, skill.execute_tool.await_count)

    async def test_unrelated_or_unloaded_skill_does_not_claim_direct_request(self):
        skill = SimpleNamespace(resolve_direct_request=lambda text: None)
        self.assertIsNone(await method('_try_direct_skill_request')(SimpleNamespace(skills=[skill]), 'where am I', Mock()))
        skill.is_unloaded = True
        skill.resolve_direct_request = Mock(side_effect=AssertionError('unloaded'))
        self.assertIsNone(await method('_try_direct_skill_request')(SimpleNamespace(skills=[skill]), 'lights', Mock()))

    async def test_activation_failure_or_execution_error_does_not_fall_through(self):
        skill = SimpleNamespace(name='EliteDangerousControls', resolve_direct_request=lambda text: ('elite_control', {}),
                                ensure_activated=AsyncMock(return_value=(False, 'validation failed')),
                                execute_tool=AsyncMock())
        registry = SimpleNamespace(activate_skill=AsyncMock(return_value=(True, 'ready', True)), deactivate_skill=Mock())
        wingman = SimpleNamespace(skills=[skill], skill_registry=registry)
        response, used = await method('_try_direct_skill_request')(wingman, 'turn lights on', Mock())
        self.assertTrue(response.startswith('Blocked:'))
        self.assertIs(skill, used)
        skill.execute_tool.assert_not_awaited()
        registry.deactivate_skill.assert_called_once()
        skill.ensure_activated.return_value = (True, 'ready')
        skill.execute_tool.side_effect = RuntimeError('adapter failure')
        response, used = await method('_try_direct_skill_request')(wingman, 'turn lights on', Mock())
        self.assertTrue(response.startswith('Unverified:'))
        skill.execute_tool.assert_awaited_once()

    async def test_cold_activation_and_real_dispatch_keep_the_initial_turn(self):
        skill = SimpleNamespace(is_prepared=False, on_add_user_message=AsyncMock())
        wingman = SimpleNamespace(skills=[skill], messages=[], _cleanup_conversation_history=AsyncMock(),
                                  _update_tool_response=AsyncMock(), _add_tool_response=lambda *a: None)
        await method('add_user_message')(wingman, 'turn off lights')
        skill.on_add_user_message.assert_not_awaited()
        seen = []
        async def execute(name, args):
            seen.append((name, current_turn.get(), current_call.get()))
            if name == 'activate_capability':
                skill.is_prepared = True
            return 'OK', None, None, None
        wingman.execute_command_by_function_call = execute
        calls = [SimpleNamespace(id='activation', function=SimpleNamespace(name='activate_capability', arguments='{}')),
                 SimpleNamespace(id='control', function=SimpleNamespace(name='elite_control', arguments='{"action":"lights","state":"off"}'))]
        await method('_handle_tool_calls')(wingman, calls)
        self.assertEqual(['activation', 'control'], [item[2] for item in seen])
        self.assertEqual(seen[0][1], seen[1][1])
        self.assertEqual('turn off lights', seen[1][1].text)
        self.assertIsNone(current_call.get())

    async def test_concurrent_new_turn_does_not_reassign_old_tool_origin(self):
        wingman = SimpleNamespace()
        ready, proceed = asyncio.Event(), asyncio.Event()
        async def old_request():
            original = begin_turn(wingman, 'turn on lights')
            ready.set()
            await proceed.wait()
            self.assertEqual(original, current_turn.get())
            self.assertNotEqual(original.id, wingman.latest_user_turn_id)
        task = asyncio.create_task(old_request())
        await ready.wait()
        begin_turn(wingman, 'do not turn on lights')
        proceed.set()
        await task


if __name__ == '__main__':
    unittest.main()

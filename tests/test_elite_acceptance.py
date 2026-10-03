"""Offline acceptance-ledger regressions. These are not gameplay evidence."""

from copy import deepcopy
import asyncio
import json
import os
import time
from pathlib import Path
import tempfile
import unittest

from integrations.elite_dangerous.acceptance import protocol as key_protocol, assess_case, summary, append, physical_result, assigned_events, direct_block
from services.elite_runtime_identity import compare, capture, process_started, write_identity
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock


def protocol():
    # Archived state-setting receipts remain readable after the user's change.
    return key_protocol(single_press=False)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.expected = {"wingman_core.py": {"path": str(Path('wingman_core.py').resolve()), "sha256": "new"}}
        self.record = {"pid": 50, "process_started": 100, "schema_revision": 3, "profile": "_Elite Dangerous",
                       "config_root": str(Path('configs').resolve()), "files": deepcopy(self.expected),
                       "skills": [{"name": "EliteDangerous"}, {"name": "EliteDangerousControls"}]}

    def test_loaded_fingerprint_is_not_recomputed_after_file_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'module.py'
            path.write_text('old')
            first = capture(path)
            path.write_text('new')
            self.assertEqual(first, capture(path))

    def test_native_process_start_is_stable_and_in_the_past(self):
        started = process_started(os.getpid())
        self.assertLess(started, time.time())
        self.assertEqual(started, process_started(os.getpid()))

    def test_identity_writer_runs_without_optional_process_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'configs'
            directory.mkdir()
            tower = SimpleNamespace(wingmen=[], config_dir=SimpleNamespace(directory='_Elite Dangerous'))
            manager = SimpleNamespace(config_dir=str(directory), get_config_dirs=lambda: [])
            with patch.dict('sys.modules', {'psutil': None}):
                record = write_identity(SimpleNamespace(tower=tower, config_manager=manager))
            self.assertEqual(os.getpid(), record['pid'])
            self.assertTrue((Path(temp) / 'elite-runtime.json').is_file())

    def test_stale_code_pid_and_reused_pid_are_detected(self):
        self.assertEqual([], compare(self.record, self.expected, pid=50, process_started=100))
        self.record['files']['wingman_core.py']['sha256'] = 'old'
        issues = compare(self.record, self.expected, pid=51, process_started=101)
        self.assertIn('stale_pid', issues)
        self.assertIn('stale_process_start', issues)
        self.assertIn('stale_or_missing:wingman_core.py', issues)

    def test_profile_missing_skills_packaged_and_conflicts_are_explicit(self):
        self.record.update(frozen=True, skills=[], duplicate_defaults=True, legacy_commands=['ship toggle lights'])
        issues = compare(self.record, self.expected, profile='Other')
        for issue in ['packaged_core', 'wrong_profile', 'missing_skill:EliteDangerousControls',
                      'duplicate_defaults', 'conflicting_legacy_commands']:
            self.assertIn(issue, issues)

    def test_same_version_or_hash_does_not_allow_another_core_location(self):
        self.record['files']['wingman_core.py']['path'] = str(Path('elsewhere/wingman_core.py').resolve())
        self.assertIn('wrong_module_location:wingman_core.py', compare(self.record, self.expected))


class AcceptanceTests(unittest.TestCase):
    def result(self, case, outcome='confirmed'):
        bit = 8 if case['action'] == 'lights' else 28
        flags = (1 << 24) | ((1 << bit) if case['desired'] == 'on' else 0)
        after = {'session': 'live-session', 'observed': 2, 'revision': 'after', 'data': {'Flags': flags}}
        before = deepcopy(after)
        before.update(observed=1, revision='before')
        if outcome in ('confirmed', 'input_sent'):
            before['data']['Flags'] ^= 1 << bit
        return {'outcome': outcome, 'intent': case, 'request_id': 'turn:call',
                'speech': 'Confirmed: lights off.', 'evidence': {'before': before, 'after': after},
                'input_events': [{'inserted': 1, 'requested': 1, 'release': r} for r in (False, True)] if outcome in ('confirmed', 'input_sent') else []}

    def test_current_protocol_repeated_words_toggle_every_time(self):
        plan = key_protocol()
        self.assertEqual(138, len(plan))
        for path in ('direct', 'voice', 'voice_after_restart'):
            for action in ('lights', 'night_vision'):
                cases = [c for c in plan if c['path'] == path and c['action'] == action]
                self.assertEqual(['on', 'on', 'off', 'off'] * 5 + ['toggle', 'toggle'], [c['state'] for c in cases])
                self.assertEqual(['on', 'off'] * 11, [c['desired'] for c in cases])
                self.assertFalse(any(c['already_set'] for c in cases))

    def test_press_receipt_needs_external_game_observation_and_player_confirmation(self):
        case = next(c for c in key_protocol() if c['path'] == 'direct')
        result = self.result(case, 'input_sent')
        result['speech'] = 'Lights key sent.'
        after = result['evidence'].pop('after')
        note = {'visible': 'on'}
        self.assertEqual('game_observation', assess_case(case, [result], note))
        observation = {'event': 'game_observation', 'request_id': result['request_id'],
                       'observation_outcome': 'gameplay_observed', 'after': after}
        self.assertEqual('', assess_case(case, [result, observation], note))
        note['visible'] = 'off'
        self.assertEqual('player_observation', assess_case(case, [result, observation], note))

    def test_generated_speech_is_correlated_without_relabeling_the_input_as_gameplay(self):
        case = next(c for c in key_protocol() if c['path'] == 'voice')
        result = self.result(case, 'input_sent')
        result['speech'] = 'Toggling lights, Commander.'
        observation = {'event': 'game_observation', 'request_id': result['request_id'],
                       'observation_outcome': 'gameplay_observed', 'after': result['evidence'].pop('after')}
        generated = {'event': 'acknowledgment_generated', 'request_id': result['request_id'],
                     'outcome_basis': 'input_sent', 'speech': 'Copy that, Commander.'}
        speech = {'event': 'speech_requested', 'request_id': result['request_id'],
                  'transcript': 'turn on lights', 'speech': generated['speech']}
        note = {'visible': 'on', 'heard': generated['speech']}
        events = [result, observation, generated, speech]
        self.assertEqual('', assess_case(case, events, note))
        self.assertEqual('game_observation', assess_case(case, [result, generated, speech], note))
        generated['speech'] = speech['speech'] = note['heard'] = 'Confirmed, lights are now on.'
        self.assertEqual('speech', assess_case(case, events, note))

    def test_voice_block_preserves_order_speech_association_and_extra_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            append(root / 'blocks', {'path': 'voice', 'cases': [53, 54]})
            for request, stamp in [('second', '2026-01-01T00:00:02'), ('first', '2026-01-01T00:00:01'),
                                   ('extra', '2026-01-01T00:00:03')]:
                append(root / 'events', {'case': 53, 'request_id': request, 'outcome': 'confirmed',
                                        'evidence': {'started_at': stamp}})
                append(root / 'events', {'case': 53, 'request_id': request, 'event': 'speech_requested'})
            events = assigned_events(root)
            for event in events:
                self.assertEqual(53 if event['request_id'] == 'first' else 54, event['case'])
            self.assertEqual(2, sum(e.get('outcome') is not None and e['case'] == 54 for e in events))
            self.assertTrue(all(json.loads(p.read_text())['case'] == 53 for p in (root / 'events').glob('*.json')))

    def test_docked_physical_transition_does_not_meet_undocked_baseline(self):
        case = protocol()[4]
        before = {'context': {'pid': 1}, 'observation': {'session': 'one', 'observed': 1,
                   'revision': 'before', 'data': {'Flags': (1 << 24) | 1}}}
        after = deepcopy(before)
        after['observation'].update(revision='after', observed=2)
        after['observation']['data']['Flags'] |= 1 << 28
        self.assertEqual('unverified', physical_result(case, before, after)['outcome'])

    def test_player_paced_physical_baseline_requires_the_correct_bit_change(self):
        case = protocol()[1]
        before = {'context': {'pid': 1}, 'observation': {'session': 'one', 'observed': 1,
                   'revision': 'before', 'data': {'Flags': 1 << 24}}}
        after = deepcopy(before)
        after['observation'].update(revision='after', observed=2)
        after['observation']['data']['Flags'] |= 1 << 8
        self.assertEqual('physical_observed', physical_result(case, before, after)['outcome'])
        before['observation']['data']['Flags'] |= 1 << 8
        after['observation']['data']['Flags'] |= 1 << 9
        self.assertEqual('unverified', physical_result(case, before, after)['outcome'])
        after['context']['pid'] = 2
        self.assertEqual('unverified', physical_result(case, before, after)['outcome'])

    def test_protocol_requires_five_cycles_and_both_toggle_states_per_path_and_action(self):
        plan = protocol()
        self.assertEqual(144, len(plan))
        for path in ('direct', 'voice', 'voice_after_restart'):
            for action in ('lights', 'night_vision'):
                cases = [c for c in plan if c['path'] == path and c['action'] == action]
                self.assertEqual(['off'] + ['on', 'on', 'off', 'off'] * 5 + ['toggle', 'toggle'], [c['state'] for c in cases])
                self.assertEqual(10, sum(c['already_set'] for c in cases))

    def test_already_set_must_send_no_input(self):
        case = next(c for c in protocol() if c['path'] == 'direct' and c['already_set'])
        result = self.result(case, 'already_set')
        result['input_events'] = [{'inserted': 1}]
        self.assertEqual('unexpected_input', assess_case(case, [result], {'visible': case['desired']}))

    def test_false_success_missing_speech_and_bad_transcription_fail(self):
        case = next(c for c in protocol() if c['path'] == 'voice')
        result = self.result(case)
        note = {'visible': 'on', 'heard': result['speech']}
        self.assertEqual('player_observation', assess_case(case, [result], note))
        note['visible'] = 'off'
        self.assertEqual('speech', assess_case(case, [result], note))
        speech = {'event': 'speech_requested', 'transcript': 'turn on lights', 'request_id': 'turn:call', 'speech': result['speech']}
        self.assertEqual('transcription', assess_case(case, [result, speech], note))

    def test_confirmed_label_without_matching_observation_or_complete_insertion_fails(self):
        case = next(c for c in protocol() if c['path'] == 'direct' and c['state'] == 'on')
        note = {'visible': 'on'}
        result = self.result(case)
        self.assertEqual('', assess_case(case, [result], note))
        for field in ('before', 'after'):
            missing = deepcopy(result)
            del missing['evidence'][field]
            self.assertEqual('game_observation', assess_case(case, [missing], note))
        result['input_events'][1]['inserted'] = 0
        self.assertEqual('input', assess_case(case, [result], note))

    def test_voice_word_order_variants_must_preserve_canonical_intent(self):
        case = next(c for c in protocol() if c['path'] == 'voice' and c['state'] == 'on')
        result = self.result(case)
        result['speech'] = 'Confirmed: lights on.'
        speech = {'event': 'speech_requested', 'request_id': result['request_id'], 'speech': result['speech']}
        note = {'visible': 'on', 'heard': result['speech']}
        for text in ['turn on lights', 'Turn lights on.', 'Please turn the lights on.']:
            speech['transcript'] = text
            self.assertEqual('', assess_case(case, [result, speech], note))
        for text in ['turn lights off', 'toggle lights', 'do not turn lights on']:
            speech['transcript'] = text
            self.assertEqual('transcription', assess_case(case, [result, speech], note))

    def test_missing_observation_and_duplicate_execution_never_pass(self):
        case = next(c for c in protocol() if c['path'] == 'direct')
        result = {'outcome': 'unverified', 'intent': case, 'first_failing_stage': 'game_observation'}
        note = {'visible': 'off'}
        self.assertEqual('game_observation', assess_case(case, [result], note))
        self.assertEqual('duplicate_execution', assess_case(case, [result, result], note))
        self.assertEqual('routing', assess_case(case, [], note))

    def test_failures_are_preserved_and_empty_ledger_is_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = {'protocol': protocol()}
            self.assertFalse(summary(root, session)['basic_controls_passed'])
            append(root / 'checkpoints', {'case': 1, 'visible': 'unknown'})
            append(root / 'checkpoints', {'case': 1, 'visible': 'off'})
            result = summary(root, session)
            self.assertEqual('repeated_trial_start_new_sequence', result['failed_trials'][0]['stage'])
            self.assertEqual('pending', result['acceptance'])

    def test_repeated_checkpoint_of_same_process_is_not_two_restarts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for _ in range(2):
                append(root / 'restarts', {'identity': {'instance': 'one'}, 'dropdown_visible': True})
            self.assertEqual(1, summary(root, {'protocol': protocol()})['distinct_user_restarts'])


class DirectBlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_block_stops_at_uncertain_input_or_unexpected_already_set_press(self):
        cases = [c for c in protocol() if c['path'] == 'direct' and c['already_set']][:2]
        for outcome, events in [('unverified', []), ('already_set', [{'inserted': 1}])]:
            with self.subTest(outcome=outcome), patch('keyboard.keyboard.on_press_key'), patch('keyboard.keyboard.unhook') as unhook:
                runner = AsyncMock(return_value={'outcome': outcome, 'input_events': events, 'speech': 'Unverified.'})
                with patch('integrations.elite_dangerous.acceptance.run_trial', runner):
                    result = await direct_block(Path('.'), {}, cases, 3)
                self.assertEqual([cases[0]['case']], result['attempted_cases'])
                runner.assert_awaited_once()
                unhook.assert_called_once()

    async def test_escape_during_block_delay_cancels_without_starting_next_trial(self):
        cases = [c for c in protocol() if c['path'] == 'direct'][:2]
        entered = asyncio.Event()
        async def wait_in_trial(*args, **kwargs):
            entered.set()
            await asyncio.Future()
        with patch('keyboard.keyboard.on_press_key') as hook, patch('keyboard.keyboard.unhook') as unhook:
            runner = AsyncMock(side_effect=wait_in_trial)
            with patch('integrations.elite_dangerous.acceptance.run_trial', runner):
                task = asyncio.create_task(direct_block(Path('.'), {}, cases, 3))
                await entered.wait()
                hook.call_args.args[1](None)
                with self.assertRaises(asyncio.CancelledError):
                    await task
            runner.assert_awaited_once()
            unhook.assert_called_once()


if __name__ == '__main__':
    unittest.main()

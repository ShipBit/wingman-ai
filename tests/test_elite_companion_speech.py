"""Model-response doubles verify sequencing and limits; no live provider claims."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from skills.elite_dangerous_controls.result import ControlResult
from skills.elite_dangerous_controls.speech import CompanionSpeech, suitable_acknowledgment


def completion(text, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=tool_calls))])


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    def result(self, outcome='input_sent'):
        return ControlResult('turn:call', {'action': 'lights'}, outcome, 'Input receipt.')

    async def test_requests_fresh_brief_model_reply_each_time_and_supplies_recent_history(self):
        model = AsyncMock(side_effect=[completion('Copy that, Commander.'), completion('Aye, toggling lights.')])
        events = []
        speech = CompanionSpeech(model, lambda: 'Dry wit, concise.', events.append)
        self.assertEqual('Copy that, Commander.', await speech.acknowledge(self.result()))
        self.assertEqual('Aye, toggling lights.', await speech.acknowledge(self.result()))
        self.assertEqual(2, model.await_count)
        self.assertIn('Copy that, Commander.', model.await_args.args[0][1]['content'])
        self.assertIsNone(model.await_args.kwargs['tools'])
        self.assertEqual(['model', 'model'], [e['source'] for e in events])

    async def test_unsupported_claim_tool_call_duplicate_or_timeout_uses_varied_fallback_without_retry(self):
        for response in (completion('Confirmed: lights are now on.'), completion('Aye.', ['invented_tool']),
                         completion('x' * 200), None):
            with self.subTest(response=response):
                model = AsyncMock(return_value=response)
                speech = CompanionSpeech(model)
                first = await speech.acknowledge(self.result())
                second = await speech.acknowledge(self.result())
                self.assertNotEqual(first, second)
                self.assertTrue(suitable_acknowledgment(first))
                self.assertEqual(2, model.await_count)  # One attempt per command; never retry.
        model = AsyncMock(return_value=completion('Aye, Commander.'))
        speech = CompanionSpeech(model)
        self.assertNotEqual(await speech.acknowledge(self.result()), await speech.acknowledge(self.result()))
        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
        speech = CompanionSpeech(slow, timeout=0.01)
        self.assertTrue(suitable_acknowledgment(await speech.acknowledge(self.result())))

    async def test_failures_cancellation_and_duplicates_keep_their_factual_reason_without_model_call(self):
        model = AsyncMock()
        speech = CompanionSpeech(model)
        for outcome in ('blocked', 'unverified', 'cancelled', 'duplicate', 'failed'):
            result = self.result(outcome)
            self.assertEqual(result.speech, await speech.acknowledge(result))
        model.assert_not_awaited()

    def test_factual_claims_and_new_instructions_are_rejected(self):
        for text in ('Lights are on, Commander.', 'Copy, shields deployed.', 'Aye, retry again.',
                     'Roger, weapons now ready.', 'Understood, successfully completed.'):
            self.assertFalse(suitable_acknowledgment(text))
        self.assertFalse(suitable_acknowledgment('Toggling shields, Commander.', 'lights'))


if __name__ == '__main__':
    unittest.main()

"""Small, tool-free AI acknowledgments generated only after a control receipt."""
import asyncio
from collections import deque
import json
import re
from .bindings import ACTIONS


def suitable_acknowledgment(text, action=None):
    if not isinstance(text, str) or not 1 <= len(text.split()) <= 18 or len(text) > 160:
        return False
    if any(c in text for c in ('\n', '{', '}', '<', '>')):
        return False
    # Reject state/success claims and instructions, even if a model ignores its
    # narrow task. An acknowledgment is not game observation.
    if re.search(r"\b(confirmed|already|done|complete\w*|success\w*|enabled|disabled|deployed|retracted|activated|deactivated|engaged|disengaged|now|off|ready|failed|cannot|can't|press|retry|again|is|are|was|were|has|have)\b", text, re.I):
        return False
    if re.search(r"\bon\b", re.sub(r"\bon it\b", '', text, flags=re.I), re.I):
        return False
    if action:
        expected = action.replace('_', ' ')
        labels = {phrase.removeprefix('toggle ') for catalog in ACTIONS.values() for phrase in catalog.values()}
        if any(label != expected and re.search(r'\b' + re.escape(label) + r'\b', text, re.I) for label in labels):
            return False
    return bool(re.search(r"\b(aye|roger|copy|understood|acknowledged|acknowledging|toggling|cycling|switching|request received|on it|at your service)\b", text, re.I))


class CompanionSpeech:
    def __init__(self, call_model, persona=lambda: '', log=lambda event: None, timeout=4):
        self.call_model, self.persona, self.log, self.timeout = call_model, persona, log, timeout
        self.recent = deque(maxlen=6)

    async def acknowledge(self, result):
        if result.outcome != 'input_sent':
            return result.speech
        messages = [{"role": "system", "content":
            "You are the commander's Elite Dangerous cockpit companion. Compose ONE fresh, natural acknowledgment, "
            "3 to 12 words, plain spoken text only. Vary cadence and wording; avoid recent replies. Commander is optional. "
            "The requested control was pressed once. On/off wording is a key alias and may invert its current state. "
            "Acknowledge the order (copy, aye, understood, on it) or describe toggling/cycling. Never assert game state, "
            "completion, success, enabled/disabled, ready, or any on/off outcome. Do not give instructions, retry, or call tools. "
            "No technical jargon about keys, APIs or Windows. Persona for tone only: " + self.persona()[:800]},
            {"role": "user", "content": json.dumps({"action": result.intent.get('action'),
                "recent_replies": list(self.recent)}, ensure_ascii=False)}]
        source = 'fallback'
        try:
            completion = await asyncio.wait_for(self.call_model(messages, tools=None), self.timeout)
            message = completion.choices[0].message
            candidate = (message.content or '').strip().strip('"')
            if (not getattr(message, 'tool_calls', None) and suitable_acknowledgment(candidate, result.intent.get('action'))
                    and candidate.casefold() not in {s.casefold() for s in self.recent}):
                text, source = candidate, 'model'
            else:
                text = self._fallback()
        except Exception as exc:
            self.log({'event': 'acknowledgment_unavailable', 'request_id': result.request_id,
                      'error_type': type(exc).__name__})
            text = self._fallback()
        self.recent.append(text)
        self.log({'event': 'acknowledgment_generated', 'request_id': result.request_id,
                  'source': source, 'outcome_basis': result.outcome, 'speech': text})
        return text

    def _fallback(self):
        # Only used if the configured provider fails, times out, repeats itself,
        # or makes an unsupported claim. Never retry the input or the model call.
        return next((s for s in ('Aye, Commander.', 'Copy that.', 'Understood, Commander.',
                    'On it.', 'Roger, Commander.', 'Acknowledged.', 'Copy, Commander.')
                     if s not in self.recent), 'Aye, Commander.')

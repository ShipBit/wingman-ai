"""Proactive Comments: what goes into the prompt and what happens to a line."""

import asyncio
from types import SimpleNamespace

from skills.proactive_comments.main import ProactiveComments


class FakeConversation:
    def __init__(self, history):
        self._history = history
        self.user_busy = False
        self.shown = []
        self.notes = []

    def history(self):
        return list(self._history)

    async def show(self, text, *, skill_name=""):
        self.shown.append(text)

    async def add_note(self, content):
        self.notes.append(content)


def _skill(history, props=None):
    props = {
        "custom_system_prompt": "Keep the chat going.",
        "max_proactive_messages": 3,
        "add_comments_to_history": True,
        **(props or {}),
    }
    skill = object.__new__(ProactiveComments)
    skill.is_running = True
    skill.loaded = True
    skill.run_id = 1
    skill.proactive_message_count = 0
    skill.unnoted = []
    skill.prompts = []
    skill.spoken = []
    skill._prop = props.get
    skill.config = SimpleNamespace(display_name="Proactive Comments")

    async def generate(prompt, *, system="", preset=None):
        skill.prompts.append(prompt)
        return '"Quiet out here, Bob."'

    async def speak(text, *, priority=None):
        skill.spoken.append(text)
        return True

    skill.wingman = SimpleNamespace(
        name="Bob",
        language=SimpleNamespace(name="English"),
        config=SimpleNamespace(prompts=SimpleNamespace(backstory="A pilot.")),
        conversation=FakeConversation(history),
        audio=SimpleNamespace(is_playing_at_least=lambda priority: False),
        local_ai=SimpleNamespace(available=True, generate=generate),
        tts=SimpleNamespace(speak=speak),
    )
    return skill


def test_the_prompt_holds_the_conversation():
    skill = _skill(
        [
            {"role": "system", "content": "secret system prompt"},
            {"role": "user", "content": "We fly to Lorville."},
            {"role": "tool", "content": "raw tool output"},
            {"role": "assistant", "content": "Course set."},
        ]
    )

    asyncio.run(skill._comment(1))

    (prompt,) = skill.prompts
    assert "user: We fly to Lorville." in prompt
    assert "assistant: Course set." in prompt
    assert "raw tool output" not in prompt
    assert "secret system prompt" not in prompt
    assert skill.spoken == ["Quiet out here, Bob."]


def test_no_comment_without_a_conversation_or_narrator_mode():
    skill = _skill([])

    asyncio.run(skill._comment(1))

    assert skill.prompts == []
    assert skill.spoken == []


def test_a_line_written_while_the_user_started_talking_is_dropped():
    skill = _skill([{"role": "user", "content": "Hi"}])
    skill.wingman.conversation.user_busy = True

    asyncio.run(skill._comment(1))

    assert skill.spoken == []
    assert skill.proactive_message_count == 0


def test_the_next_user_message_notes_the_line_and_resets_the_count():
    skill = _skill([{"role": "user", "content": "Hi"}])
    asyncio.run(skill._comment(1))
    assert skill.proactive_message_count == 1

    asyncio.run(skill.on_add_user_message("What did you say?"))

    assert skill.proactive_message_count == 0
    (note,) = skill.wingman.conversation.notes
    assert "Quiet out here, Bob." in note
    asyncio.run(skill.on_add_user_message("And now?"))
    assert len(skill.wingman.conversation.notes) == 1

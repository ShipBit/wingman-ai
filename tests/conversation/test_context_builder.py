"""The system prompt a Wingman sends carries its backstory, its active skills and its memory.

ContextBuilder fills the system prompt template from the config. What must
hold is that the parts the user configured end up in the text, that skills
which are not active add nothing (they cost tokens), that no template
placeholder is left as raw braces for the model to read, and that optional
parts (memory, summary) show up only when there is something to show. The
tests check that parts are present, not the exact wording.
"""

import asyncio
from types import SimpleNamespace

from api.enums import SpokenLanguage, TtsProvider
from services.context_builder import ContextBuilder

TEMPLATE = (
    "SYSTEM-PROMPT-MARKER\n"
    "{user_context}\n{backstory}\n{skills}\n{ttsprompt}\n"
    "{conversation_summary}\n{language_instruction}"
)


class FakeSkill:
    def __init__(self, name, prompt="", tools=""):
        self.name = name
        self._prompt = prompt
        self._tools = tools

    async def get_prompt(self):
        return self._prompt

    def get_tools_description(self):
        return self._tools


class FakeRegistry:
    def __init__(self, *active):
        self.active_skill_names = set(active)


class FakeMemory:
    def __init__(self, block):
        self._block = block

    def memory_block(self):
        return self._block

    def block_stats(self):
        return (2, 1)


def make_config(backstory="Backstory: a grumpy ship AI.", template=TEMPLATE):
    tts = SimpleNamespace(use_tts_prompt=False, tts_prompt="")
    return SimpleNamespace(
        prompts=SimpleNamespace(system_prompt=template, backstory=backstory),
        features=SimpleNamespace(tts_provider=TtsProvider.EDGE_TTS),
        elevenlabs=tts,
        inworld=SimpleNamespace(use_tts_prompt=False, tts_prompt="", model_id=""),
        openai_compatible_tts=tts,
    )


def make_settings(user_name="Commander"):
    return SimpleNamespace(
        spoken_language=SpokenLanguage.DE, other_language=None, user_name=user_name
    )


def build(
    config=None,
    skills=(),
    active=(),
    summary="",
    memory=None,
    settings=None,
    config_dir_name=None,
):
    builder = ContextBuilder(
        config or make_config(), settings or make_settings(), "Computer"
    )
    return asyncio.run(
        builder.build(
            skills=list(skills),
            skill_registry=FakeRegistry(*active),
            conversation_summary=summary,
            persistent_memory_service=memory,
            messages=[],
            config_dir_name=config_dir_name,
        )
    )


# ── what the config contributes ──


def test_the_backstory_and_the_system_prompt_end_up_in_the_context():
    context = build()

    assert "SYSTEM-PROMPT-MARKER" in context
    assert "a grumpy ship AI" in context


def test_no_template_placeholder_is_left_unfilled():
    context = build()

    for name in (
        "user_context",
        "backstory",
        "skills",
        "ttsprompt",
        "conversation_summary",
        "language_instruction",
    ):
        assert "{" + name + "}" not in context


def test_a_prompt_with_raw_braces_still_builds():
    """A user's own system prompt with a JSON example in it used to raise on
    every turn. The placeholders are still filled, the braces stay."""
    template = 'Answer like {"status": 200}.\n{backstory}\n{skills}'

    context = build(config=make_config(template=template))

    assert 'Answer like {"status": 200}.' in context
    assert "a grumpy ship AI" in context
    assert "{backstory}" not in context


def test_the_answer_language_and_the_wingman_name_are_in_the_context():
    context = build(config_dir_name="Star Citizen")

    assert "German" in context
    assert "Computer" in context
    assert "Star Citizen" in context


def test_the_user_name_is_left_out_when_the_backstory_already_names_it():
    named = build(config=make_config(backstory="You serve Commander Shepard."))
    unnamed = build()

    assert "User's name" not in named
    assert "User's name (default): Commander" in unnamed


# ── skills ──


def test_only_active_skills_add_their_prompts():
    skills = [
        FakeSkill("Radio", prompt="RADIO-SKILL-PROMPT"),
        FakeSkill("Quiet", prompt="QUIET-SKILL-PROMPT"),
    ]

    context = build(skills=skills, active=["Radio"])

    assert "RADIO-SKILL-PROMPT" in context
    assert "QUIET-SKILL-PROMPT" not in context


def test_an_active_skill_without_a_prompt_falls_back_to_its_tool_descriptions():
    skills = [FakeSkill("Radio", prompt="", tools="- play_station: tunes a station")]

    context = build(skills=skills, active=["Radio"])

    assert "play_station" in context


# ── optional parts ──


def test_memory_appears_only_when_a_memory_block_exists():
    with_memory = build(memory=FakeMemory("MEMORY-BLOCK-MARKER"))
    empty_memory = build(memory=FakeMemory(""))
    no_service = build(memory=None)

    assert "MEMORY-BLOCK-MARKER" in with_memory
    assert "MEMORY-BLOCK-MARKER" not in empty_memory
    assert "MEMORY-BLOCK-MARKER" not in no_service


def test_the_conversation_summary_is_kept_even_if_the_template_has_no_slot():
    config = make_config(template="SYSTEM-PROMPT-MARKER {backstory}")

    with_summary = build(config=config, summary="We talked about trade routes.")
    without = build(config=config)

    assert "We talked about trade routes." in with_summary
    assert "CONVERSATION SUMMARY" not in without

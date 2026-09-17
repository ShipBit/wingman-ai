"""The two tools every wingman has for the speech vocabulary.

"From now on write it Hurston": the user corrects a spelling, the wingman
stores it, the next transcript has it right. That is friendlier than the list
in Settings, and it works from a VR headset.
"""

from typing import Any

VOCABULARY_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "vocabulary_remember",
            "description": (
                "Teach the speech recognition how a name or special word is really spelled. "
                "Use it when the user says something like 'that's spelled X' or 'from now on "
                "write Y as X', and when you notice the transcript garbled a name you know. "
                "The spelling applies to every future transcript."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "correct": {
                        "type": "string",
                        "description": "The correct spelling, e.g. 'Hurston' or 'Port Olisar'.",
                    },
                    "heard": {
                        "type": "string",
                        "description": (
                            "What the transcript wrote instead, e.g. 'Houston', if you know it. "
                            "That exact form is then replaced; without it anything close to the "
                            "correct spelling is."
                        ),
                    },
                },
                "required": ["correct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vocabulary_forget",
            "description": "Remove a word from the speech vocabulary when the user asks you to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "The word or spelling to remove."},
                },
                "required": ["word"],
            },
        },
    },
]


def run_vocabulary_tool(
    name: str, args: dict[str, Any], settings_service, persistent_memory_service=None
) -> str:
    from services.audio.vocabulary import format_entry

    if name == "vocabulary_remember":
        from services.audio.vocabulary import join_spelled

        # "A T C" spelled out by the user, and passed on as such by the model
        correct = join_spelled(str(args.get("correct") or "").strip())
        heard = str(args.get("heard") or "").strip() or None
        if not correct:
            return "No spelling given."
        # "Heard" equal to "correct" means: keep it as typed, exact only.
        entry = f'"{correct}"' if heard and heard.lower() == correct.lower() else format_entry(correct, heard)
        added = settings_service.add_vocabulary([entry])
        fixed = fix_memories(persistent_memory_service, correct, heard) if heard else 0
        tail = f" {fixed} memories were corrected too." if fixed else ""
        if not added:
            return f"'{correct}' is already in the speech vocabulary.{tail}"
        if heard:
            return f"From now on '{heard}' is written as '{correct}'.{tail}"
        return f"'{correct}' is in the speech vocabulary now."
    if name == "vocabulary_forget":
        word = str(args.get("word") or "").strip()
        if not word:
            return "No word given."
        removed = settings_service.remove_vocabulary([word])
        return f"Removed '{word}' from the speech vocabulary." if removed else f"'{word}' was not in the speech vocabulary."
    return "Unknown vocabulary tool."


def fix_memories(persistent_memory_service, correct: str, heard: str) -> int:
    """Memories were written from transcripts, so they carry the same wrong
    spelling. Once the user says how it is really written, every memory that
    holds the wrong form gets the right one. Returns how many changed."""
    if persistent_memory_service is None or not heard or heard.lower() == correct.lower():
        return 0
    import re

    pattern = re.compile(r"\b" + re.escape(heard) + r"\b", re.IGNORECASE)
    fixed = 0
    try:
        for entry in persistent_memory_service.get_all():
            if not pattern.search(entry.content):
                continue
            persistent_memory_service.update_memory_sync(
                entry.id, pattern.sub(correct, entry.content)
            )
            fixed += 1
    except Exception:
        # A memory that cannot be rewritten is not worth failing the tool call.
        return fixed
    return fixed

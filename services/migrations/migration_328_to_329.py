"""Migration from version 3.2.8 to 3.2.9.

3.2.9 moves the changelog and the feature requests from Canny to our backend;
neither lives in the config.

The system prompt gets two changes from a real session log: the model ran
ship commands when the pilot only said where they were going or what they had
done, promised things it had no tool for, and gave spoken answers of a whole
minute. The changes are put into the user's own prompt rather than replacing
it, so an edited prompt keeps its edits.
"""

from services.migrations.base_migration import BaseMigration

OLD_LENGTH_RULE = "- Keep responses concise (1-3 sentences unless more detail is needed)"
NEW_LENGTH_RULE = (
    "- Keep responses short: 1-3 sentences, the answer first. "
    "Go longer only when the user asks for details"
)
ACTIONS_ANCHOR = "# YOUR CAPABILITIES"
ACTIONS_BLOCK = (
    "# ACTIONS\n"
    "- Run a command only when the user asks for that action now. A plan, a "
    "destination or something the user already did is not a request: \"next stop "
    "is Lorville\" or \"I fitted new guns\" means no command.\n"
    "- Say you did something only when a tool did it in this turn. Do not promise "
    "what you have no tool for.\n"
    "- Do not make up places, ship parts, prices or facts that neither the user "
    "nor a tool gave you.\n"
    "\n"
)


def update_system_prompt(prompt: str) -> str:
    """The prompt with the 3.2.9 rules. A prompt that has them already, or
    has no place for them, comes back as it was."""
    if not isinstance(prompt, str):
        return prompt
    prompt = prompt.replace(OLD_LENGTH_RULE, NEW_LENGTH_RULE)
    if "# ACTIONS" not in prompt and ACTIONS_ANCHOR in prompt:
        prompt = prompt.replace(ACTIONS_ANCHOR, ACTIONS_BLOCK + ACTIONS_ANCHOR, 1)
    return prompt


class Migration328To329(BaseMigration):
    """Migration from 3.2.8 to 3.2.9."""

    old_version = "3_2_8"
    new_version = "3_2_9"

    def _update(self, config: dict, owner: str) -> dict:
        prompts = config.get("prompts")
        if not isinstance(prompts, dict) or "system_prompt" not in prompts:
            return config
        updated = update_system_prompt(prompts["system_prompt"])
        if updated != prompts["system_prompt"]:
            prompts["system_prompt"] = updated
            self.log(f"- {owner}: system prompt got the rules for commands and answer length")
        return config

    def migrate_defaults(self, old: dict) -> dict:
        return self._update(old, "defaults")

    def migrate_wingman(self, old: dict) -> dict:
        return self._update(old, old.get("name", "wingman"))

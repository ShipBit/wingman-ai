"""Migration from version 3.2.7 to 3.2.8.

3.2.7 is out with testers, so the next change to a user's config needs its own
step.

`settings.yaml` gains a `star_citizen` block. The Star Citizen folder moves
there from `sc_gamelog.game_path`: the log reader is the first feature that
reads the game's files, the key bindings come next, and both read the same
folder. Skills see it as `self.wingman.star_citizen`.

`star_citizen.plays` is null for every user, also for one who used Wingman
before. The client asks once after the update whether they play Star Citizen:
the log reader is new in 3.2.x and is on for everyone, and the answer
switches it and the other Star Citizen features on or off in one go.

System One (Jev) is off for everyone. It was on by default since 3.2.4, and
testers did not know it was deciding things for them: what it got wrong looked
like a broken microphone or a Wingman that did not listen. It is optional now,
and whoever wants it switches it on under Settings. Only `enabled` changes;
`commands` keeps what the user chose, so switching System One back on brings
back the setup they had.

Most users come from 2.1.1 and never saw a 3.x default. Their Wingmen keep
everything they made - backstory, voice, commands - but the Wingmen Wingman
ships get the skills and MCP servers their template has and they lack, e.g.
Wingman Web Search on Computer. Only added, never removed: the Star Citizen
question right after the update switches the game's features off for users
who say No. The users' own Wingmen are left alone: the skills that are
discoverable by default there include the Star Citizen ones, and on every
Wingman each game event would be answered many times.

Four command texts on Computer had typos in 2.1.x ("Missle",
"countermeassures"); the template is fixed, the users' copies are fixed where
the text is still exactly the old one.

defaults.yaml: the Inworld model is the current one if it is still the old
default; a user who picked a model keeps it.

The Computer Wingman hung "Pilot" or "Commander" on nearly every reply and made
up ship status ("shields on standby, no warnings") it has no way of knowing.
Its backstory now says how to address the user and that it has no telemetry,
and the system prompt tells every Wingman not to address the user by title or
name in every reply.

- The system prompt is reset to the shipped one, the same way 3.2.3 did it: it
  is not user content, and a per-Wingman override is deleted outright.
- The Computer's backstory IS user content, so it is only replaced when it is
  still the one 3.2.7 shipped. A backstory the user edited is kept.
"""

from os import path
from typing import Optional

from services.migrations.base_migration import BaseMigration
from services.star_citizen.game_folder import DEFAULT_GAME_PATH


# Old text -> fixed text, as the Computer template had and has them.
COMMAND_TEXT_FIXES = {
    "Missle salvo size cycled by +1": "Missile salvo size cycled by +1",
    "Missle salvo size set to one": "Missile salvo size set to one",
    "Decoy count configuration increased for next use of decoy countermeassures": (
        "Decoy count configuration increased for next use of decoy countermeasures"
    ),
    "Decoy count configuration decreased for next use of decoy countermeassures": (
        "Decoy count configuration decreased for next use of decoy countermeasures"
    ),
}

OLD_INWORLD_MODEL = "inworld-tts-1"
INWORLD_MODEL = "inworld-tts-2-flash"

COMPUTER_TEMPLATE = path.join("configs", "Star Citizen", "Computer.template.yaml")

OLD_COMPUTER_BACKSTORY = """Your name is "Computer" and you are the AI board computer of a spacecraft in the Star Citizen universe.

**Communication Style:**
- Speak with technical precision and efficiency
- Use spacecraft terminology naturally
- Provide brief status confirmations after actions
- Sound like an advanced ship AI, not a casual assistant

**Your Role Context:**
- You control all ship systems: navigation, weapons, shields, power
- You execute commands immediately without seeking confirmation
- You treat each request as a fresh directive
- This universe is your reality (never reference "the game")

**Personality:**
- Authoritative and confident
- Efficient and action-oriented
- Technically precise
- Loyal to your pilot
"""


def _same_text(a: str, b: str) -> bool:
    """Equal apart from whitespace: saving through the client reflows the YAML."""
    return a.split() == b.split()


class Migration327To328(BaseMigration):
    """Migration from 3.2.7 to 3.2.8."""

    old_version = "3_2_7"
    new_version = "3_2_8"

    def _template_prompts(self, relative_path: str) -> dict:
        file_path = path.join(self.templates_dir, relative_path)
        if not path.exists(file_path):
            return {}
        template = self.config_manager.read_config(file_path) or {}
        return template.get("prompts") or {}

    def _shipped_system_prompt(self) -> Optional[str]:
        return self._template_prompts(
            path.join("configs", "defaults.yaml")
        ).get("system_prompt")

    def _shipped_computer_backstory(self) -> Optional[str]:
        return self._template_prompts(COMPUTER_TEMPLATE).get("backstory")

    def migrate_defaults(self, old: dict) -> dict:
        inworld = old.get("inworld")
        if isinstance(inworld, dict) and inworld.get("model_id") == OLD_INWORLD_MODEL:
            inworld["model_id"] = INWORLD_MODEL
            self.log(f"- inworld.model_id: {OLD_INWORLD_MODEL} -> {INWORLD_MODEL}")
        self._reset_system_prompt(old)
        return old

    def _reset_system_prompt(self, old: dict) -> None:
        """Put the shipped system prompt back into defaults.yaml."""
        shipped = self._shipped_system_prompt()
        if not shipped:
            self.log_warning(
                "- could not read the shipped system prompt; leaving it alone"
            )
            return

        prompts = old.get("prompts")
        if not isinstance(prompts, dict) or "system_prompt" not in prompts:
            return

        if prompts["system_prompt"] != shipped:
            prompts["system_prompt"] = shipped
            self.log("- defaults: system prompt reset to the shipped one")

    def migrate_wingman(self, old: dict) -> dict:
        self._add_template_extras(old)
        self._fix_prompts(old)
        return old

    def _add_template_extras(self, old: dict) -> None:
        template = self.shipped_template()
        if not template:
            return
        name = old.get("name") or template.get("name")
        for key in ("discoverable_skills", "discoverable_mcps"):
            have = list(old.get(key) or [])
            missing = [item for item in template.get(key) or [] if item not in have]
            if missing:
                old[key] = have + missing
                self.log(f"- {name}: {key} + {', '.join(missing)}")
        for command in old.get("commands") or []:
            if not isinstance(command, dict):
                continue
            fixed = COMMAND_TEXT_FIXES.get(command.get("additional_context"))
            if fixed:
                command["additional_context"] = fixed
                self.log(f"- {name}: fixed the text of command '{command.get('name')}'")

    def _fix_prompts(self, old: dict) -> None:
        prompts = old.get("prompts")
        if not isinstance(prompts, dict):
            return

        if "system_prompt" in prompts:
            prompts.pop("system_prompt")
            self.log(
                f"- {old.get('name', 'wingman')}: removed its own system prompt; "
                "it uses the shipped one now"
            )

        backstory = prompts.get("backstory")
        if isinstance(backstory, str) and _same_text(backstory, OLD_COMPUTER_BACKSTORY):
            shipped = self._shipped_computer_backstory()
            if shipped:
                prompts["backstory"] = shipped
                self.log(
                    f"- {old.get('name', 'wingman')}: backstory updated "
                    "(no more \"Pilot\"/\"Commander\", no made-up ship status)"
                )

        # An empty prompts block is noise in the file.
        if not prompts:
            old.pop("prompts")

    def migrate_settings(self, old: dict) -> dict:
        if "star_citizen" not in old:
            sc_gamelog = old.get("sc_gamelog")
            game_path = None
            if isinstance(sc_gamelog, dict):
                game_path = sc_gamelog.pop("game_path", None)
            game_path = game_path or DEFAULT_GAME_PATH
            old["star_citizen"] = {"plays": None, "game_path": game_path}
            self.log(f"- added star_citizen, game folder {game_path}")

        block = old.get("system_one")
        if not isinstance(block, dict):
            old["system_one"] = {"enabled": False, "commands": True}
        else:
            block["enabled"] = False
            block.setdefault("commands", True)
        self.log("- system_one: off — switch it on under Settings if you want it")
        return old

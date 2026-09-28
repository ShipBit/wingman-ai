"""Migration from version 3.2.4 to 3.2.5.

3.2.5 changes how the client installs an update: a toast with download
progress, and a restart once it is installed. None of that is configured.

It also works out every limit on what Wingman sends from the main model's
context window instead of fixed numbers (services/context_budget.py,
docs/context-and-shortening.md). Four settings made for the old numbers go,
from defaults and every Wingman:

- `features.compress_tool_responses`: a tool response over the limit is now
  always cut, never summarized. On real text the summary kept none of three
  facts and made the pilot wait 25 seconds; the cut kept two.
- `features.skill_max_input_tokens`: the limit is 32,000 tokens, or a quarter
  of a smaller model's window.
- `features.condense_keep_recent_tokens` and `features.condense_max_messages`:
  the history limit decides when and how much is summarized.

`features.condense_conversation` stays, the one switch left.

Core now reads Star Citizen's Game.log itself (services/sc_gamelog), which
the community SC Log Reader skill did before, installed as a custom skill in
custom_skills/sc_log_reader. That skill goes:

- Its folder moves out of custom_skills to custom_skills_replaced, so it can
  never run next to Core's reader and announce everything twice.
- Every Wingman loses its entry and its name in `discoverable_skills`.
- The game folder from its settings becomes `sc_gamelog.game_path`.
- A Wingman that had spoken reactions switched on gets the bundled Star
  Citizen Events skill instead, with the categories the old switches had on.
  2.x called that switch `proactive_notifications`, 0.5 `react_game_events`.

SC Accountant, from the same author, is bundled now under the same folder and
skill name, so Wingmen keep it and its books stay where they are. The custom
copy moves out like the reader, and its two settings for finding the reader's
database go: Core tells it where the log is.
"""

import os
import re
import shutil
from os import path

from services.file import get_custom_skills_dir, get_users_dir
from services.migrations.base_migration import BaseMigration

_REMOVED_FEATURES = (
    "compress_tool_responses",
    "skill_max_input_tokens",
    "condense_keep_recent_tokens",
    "condense_max_messages",
)


DEFAULT_GAME_PATH = "C:\\Program Files\\Roberts Space Industries\\StarCitizen"
_ENVIRONMENTS = {"LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW"}
_OLD_READER_MODULES = {"skills.sc_log_reader.main", "skills.sc_log_reader_2.main"}
_OLD_READER_NAMES = {"SC_LogReader", "SCLogReader", "SCLogReader2"}
_OLD_READER_FOLDERS = ("sc_log_reader", "sc_log_reader_2")
_REPLACED_FOLDERS = _OLD_READER_FOLDERS + ("sc_accountant",)
_ACCOUNTANT_MODULE = "skills.sc_accountant.main"
_ACCOUNTANT_DROPPED = {"reader_database", "auto_sync_interval"}
_NEW_SKILL = "ScGameEvents"
_NEW_SKILL_MODULE = "skills.sc_game_events.main"

# The old skill's `notify_<kind>` switches by the category they belong to now.
# 0.5 also had one master per category, named `notify_<category>`.
_OLD_SWITCHES = {
    "health": (
        "bleeding", "emergency_services", "incapacitated", "injury", "med_bed_heal",
    ),
    "location": (
        "location_arrived", "location_change", "location_departed", "location_updates",
        "qt_arrived", "qt_calibration_complete_group", "quantum_calibration_complete",
        "quantum_calibration_started", "quantum_route_set",
    ),
    "mission": (
        "contract_available", "contract_shared", "mission_accepted", "mission_complete",
        "mission_failed", "mission_objective_new", "mission_withdrawn",
        "objective_complete", "objective_new", "objective_withdrawn",
    ),
    "money": (
        "blueprint_received", "cargo_transfer", "commodity_buy", "commodity_sell",
        "fined", "money_sent", "refinery_complete", "refinery_submitted",
        "reward_earned", "shop_buy", "shop_sell", "transaction_complete",
    ),
    "safety": (
        "armistice_zone", "crimestat_increased", "entered_monitored_space",
        "exited_monitored_space", "jurisdiction_change", "monitored_space",
        "monitored_space_availability", "monitored_space_down",
        "monitored_space_restored", "restricted_area", "zone_entered_armistice",
        "zone_left_armistice",
    ),
    "session": (
        "incoming_call", "join_pu", "journal_entry", "party_invite", "party_left",
        "party_member_joined", "party_membership", "session_start", "user_login",
    ),
    "ship": (
        "fatal_collision", "fuel_low", "hangar_access", "hangar_queue", "hangar_ready",
        "insurance_claim", "insurance_claim_complete", "ship_boarding", "ship_entered",
        "ship_exited", "vehicle_impounded",
    ),
}


def _star_citizen_folder(value) -> str | None:
    """The StarCitizen folder from what users typed: the folder itself, an
    environment inside it, or the Game.log."""
    text = str(value or "").strip().strip('"').rstrip("\\/")
    if not text:
        return None
    parts = re.split(r"[\\/]", text)
    if parts[-1].lower() == "game.log":
        parts = parts[:-1]
    if parts and parts[-1].upper() in _ENVIRONMENTS:
        parts = parts[:-1]
    return ("\\" if "\\" in text else "/").join(parts) or None


def _old_reader_entries(wingman: dict) -> list[dict]:
    return [
        entry
        for entry in wingman.get("skills") or []
        if isinstance(entry, dict) and entry.get("module") in _OLD_READER_MODULES
    ]


def _values(entry: dict) -> dict:
    return {
        prop["id"]: prop.get("value")
        for prop in entry.get("custom_properties") or []
        if isinstance(prop, dict) and "id" in prop
    }


def _categories(values: dict) -> dict[str, bool]:
    """A category is on when its master was not switched off and at least one
    of its switches was left on. Switches never touched were on."""
    return {
        category: values.get(f"notify_{category}", True) is not False
        and any(values.get(f"notify_{kind}", True) is not False for kind in kinds)
        for category, kinds in _OLD_SWITCHES.items()
    }


class Migration324To325(BaseMigration):
    """Migration from 3.2.4 to 3.2.5."""

    old_version = "3_2_4"
    new_version = "3_2_5"

    def _drop_fixed_limits(self, old: dict) -> None:
        features = old.get("features")
        if not isinstance(features, dict):
            return
        for key in _REMOVED_FEATURES:
            if key in features:
                del features[key]
                self.log(f"- removed features.{key} (limits follow the model's window now)")

    def migrate_defaults(self, old: dict) -> dict:
        self._drop_fixed_limits(old)
        return old

    def migrate_settings(self, old: dict) -> dict:
        # settings.yaml is migrated before the Wingmen, so read their old files.
        if "sc_gamelog" not in old:
            game_path = self._old_game_path() or DEFAULT_GAME_PATH
            old["sc_gamelog"] = {"enabled": True, "game_path": game_path}
            self.log(f"- added sc_gamelog, reading {game_path}")
        self._retire_old_reader()
        return old

    def migrate_wingman(self, old: dict) -> dict:
        self._drop_fixed_limits(old)
        self._replace_old_reader(old)
        self._drop_accountant_reader_settings(old)
        return old

    def _drop_accountant_reader_settings(self, wingman: dict) -> None:
        for entry in wingman.get("skills") or []:
            if not isinstance(entry, dict) or entry.get("module") != _ACCOUNTANT_MODULE:
                continue
            props = entry.get("custom_properties") or []
            kept = [p for p in props if not (isinstance(p, dict) and p.get("id") in _ACCOUNTANT_DROPPED)]
            if len(kept) != len(props):
                entry["custom_properties"] = kept
                self.log("- SC Accountant finds the Star Citizen log through Core now")

    def _old_game_path(self) -> str | None:
        configs = path.join(get_users_dir(), self.old_version, "configs")
        for root, _dirs, files in os.walk(configs):
            for filename in sorted(files):
                if not filename.endswith(".yaml") or filename.endswith("template.yaml"):
                    continue
                try:
                    wingman = self.config_manager.read_config(path.join(root, filename))
                except Exception:
                    continue
                if not isinstance(wingman, dict):
                    continue
                for entry in _old_reader_entries(wingman):
                    folder = _star_citizen_folder(_values(entry).get("sc_game_path"))
                    if folder:
                        return folder
        return None

    def _retire_old_reader(self) -> None:
        custom_skills = get_custom_skills_dir()
        for folder in _REPLACED_FOLDERS:
            source = path.join(custom_skills, folder)
            if not path.isdir(source):
                continue
            target = path.join(path.dirname(custom_skills), "custom_skills_replaced", folder)
            if path.exists(target):
                shutil.rmtree(target)
            os.makedirs(path.dirname(target), exist_ok=True)
            shutil.move(source, target)
            self.log(f"- moved the custom skill {folder} to {target}; Core does its job now")

    def _replace_old_reader(self, wingman: dict) -> None:
        entries = _old_reader_entries(wingman)
        names = wingman.get("discoverable_skills") or []
        enabled = any(name in _OLD_READER_NAMES for name in names)
        if not entries and not enabled:
            return
        if entries:
            wingman["skills"] = [e for e in wingman["skills"] if e not in entries]
        wingman["discoverable_skills"] = [n for n in names if n not in _OLD_READER_NAMES]
        self.log("- removed the SC Log Reader skill (Core reads the Star Citizen log now)")

        values = _values(entries[0]) if entries else {}
        reacting = values.get("react_game_events", values.get("proactive_notifications", False))
        if not enabled or reacting is not True:
            return
        categories = _categories(values)
        wingman["skills"] = [
            e for e in wingman.get("skills") or [] if e.get("module") != _NEW_SKILL_MODULE
        ] + [
            {
                "module": _NEW_SKILL_MODULE,
                "custom_properties": [
                    {"id": f"react_{category}", "value": on}
                    for category, on in categories.items()
                ],
            }
        ]
        if _NEW_SKILL not in wingman["discoverable_skills"]:
            wingman["discoverable_skills"].append(_NEW_SKILL)
        switched_on = ", ".join(c for c, on in categories.items() if on) or "none"
        self.log(f"- added Star Citizen Events for its spoken reactions ({switched_on})")

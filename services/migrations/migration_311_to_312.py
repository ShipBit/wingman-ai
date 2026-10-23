"""Migration from version 3.1.1 to 3.1.2.

- Removes the OpenAI TTS option from Wingman Pro subscriptions (→ Azure).
- Converts RadioChatter skill's separate min/max number properties to range_slider.
- Migrates PocketTTS settings (language/high_quality/custom_model_path → model).
- Adds spoken_language setting.
- Resets the system prompt to the shipped default so everyone gets the new
  {language_instruction} placeholder.
- Migrates default TTS provider from wingman_pro to pocket_tts.
"""

from os import path
from typing import Optional

from services.migrations.base_migration import BaseMigration


RANGE_MIGRATIONS = [
    {
        "min_id": "interval_min",
        "max_id": "interval_max",
        "new_id": "interval_range",
        "clamp_min": 60,
        "clamp_max": 600,
        "defaults": [60, 600],
    },
    {
        "min_id": "messages_min",
        "max_id": "messages_max",
        "new_id": "messages_range",
        "clamp_min": 1,
        "clamp_max": 5,
        "defaults": [1, 5],
    },
    {
        "min_id": "participants_min",
        "max_id": "participants_max",
        "new_id": "participants_range",
        "clamp_min": 1,
        "clamp_max": 5,
        "defaults": [2, 3],
    },
]


class Migration311To312(BaseMigration):
    """Migration from 3.1.1 to 3.1.2."""

    old_version = "3_1_1"
    new_version = "3_1_2"

    def _migrate_wingman_pro_tts(self, old: dict) -> dict:
        if "wingman_pro" in old and old["wingman_pro"].get("tts_provider") == "openai":
            old["wingman_pro"]["tts_provider"] = "azure"
            self.log("- migrated wingman_pro.tts_provider from 'openai' to 'azure'")
        return old

    def _migrate_radio_chatter_ranges(self, old: dict) -> dict:
        skills = old.get("skills")
        if not skills:
            return old

        for skill in skills:
            if skill.get("module") != "skills.radio_chatter.main":
                continue

            props = skill.get("custom_properties")
            if not props:
                continue

            prop_map = {p["id"]: p for p in props if "id" in p}

            for rm in RANGE_MIGRATIONS:
                old_min = prop_map.get(rm["min_id"])
                old_max = prop_map.get(rm["max_id"])

                if old_min is None and old_max is None:
                    continue

                lo = rm["defaults"][0]
                hi = rm["defaults"][1]

                if old_min is not None and old_min.get("value") is not None:
                    lo = old_min["value"]
                if old_max is not None and old_max.get("value") is not None:
                    hi = old_max["value"]

                lo = max(rm["clamp_min"], min(int(lo), rm["clamp_max"]))
                hi = max(rm["clamp_min"], min(int(hi), rm["clamp_max"]))
                if hi < lo:
                    hi = lo

                props.append({"id": rm["new_id"], "value": [lo, hi]})
                self.log(
                    f"- RadioChatter: merged {rm['min_id']}+{rm['max_id']} "
                    f"-> {rm['new_id']} = [{lo}, {hi}]"
                )

            # Remove old properties
            old_ids = {
                rm["min_id"] for rm in RANGE_MIGRATIONS
            } | {rm["max_id"] for rm in RANGE_MIGRATIONS}
            skill["custom_properties"] = [
                p for p in props if p.get("id") not in old_ids
            ]

        return old

    def migrate_settings(self, old: dict) -> dict:
        pocket_tts = old.get("pocket_tts", {})
        if pocket_tts:
            if "model" not in pocket_tts:
                language = pocket_tts.pop("language", "english")
                high_quality = pocket_tts.pop("high_quality", False)
                if high_quality and language != "english":
                    pocket_tts["model"] = f"{language}_24l"
                else:
                    pocket_tts["model"] = language
                self.log(f"- migrated pocket_tts.model = '{pocket_tts['model']}'")
            else:
                pocket_tts.pop("language", None)
                pocket_tts.pop("high_quality", None)
            pocket_tts.pop("custom_model_path", None)
            # Upgrade deprecated English model IDs to the canonical pinned one.
            legacy_english = {"english", "english_2026-01"}
            if pocket_tts.get("model") in legacy_english:
                old_model = pocket_tts["model"]
                pocket_tts["model"] = "english_2026-04"
                self.log(
                    f"- upgraded pocket_tts.model '{old_model}' -> 'english_2026-04'"
                )
            if "quantize" not in pocket_tts:
                pocket_tts["quantize"] = True
                self.log("- added pocket_tts.quantize = true")

        if "spoken_language" not in old:
            old["spoken_language"] = "multilingual"
            self.log("- added spoken_language = 'multilingual'")

        return old

    def _migrate_tts_to_pocket_tts(self, old: dict) -> dict:
        features = old.get("features", {})
        if features.get("tts_provider") == "wingman_pro":
            features["tts_provider"] = "pocket_tts"
            pocket_tts = old.setdefault("pocket_tts", {})
            if not pocket_tts.get("voice"):
                pocket_tts["voice"] = "alba"
            self.log("- migrated tts_provider from 'wingman_pro' to 'pocket_tts'")
        return old

    def _load_default_system_prompt(self) -> Optional[str]:
        """Read the shipped default system_prompt from the new templates dir."""
        defaults_path = path.join(self.templates_dir, "configs", "defaults.yaml")
        if not path.exists(defaults_path):
            return None
        template = self.config_manager.read_config(defaults_path)
        if not template:
            return None
        return template.get("prompts", {}).get("system_prompt")

    def _reset_system_prompt(self, old: dict) -> dict:
        """Overwrite prompts.system_prompt with the shipped default.

        Ensures every user — including those with customized prompts — gets
        the new {language_instruction} placeholder.
        """
        default_sp = self._load_default_system_prompt()
        if not default_sp:
            return old

        prompts = old.get("prompts")
        if not prompts or "system_prompt" not in prompts:
            return old

        prompts["system_prompt"] = default_sp
        self.log("- reset system_prompt to shipped default")
        return old

    def migrate_defaults(self, old: dict) -> dict:
        old = self._migrate_wingman_pro_tts(old)
        old = self._migrate_tts_to_pocket_tts(old)
        old = self._reset_system_prompt(old)
        return old

    def migrate_wingman(self, old: dict) -> dict:
        old = self._migrate_wingman_pro_tts(old)
        old = self._migrate_tts_to_pocket_tts(old)
        old = self._migrate_radio_chatter_ranges(old)
        old = self._reset_system_prompt(old)
        return old

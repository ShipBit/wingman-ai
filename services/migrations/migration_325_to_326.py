"""Migration from version 3.2.5 to 3.2.6.

Two hosted MCP servers join `mcp.yaml`. The Elite Dangerous one: star systems
and their stations, services nearby, trade between two stations and engineering
recipes, from EDSM, Spansh and EDCD. The Galactapedia one: Star Citizen lore
from RSI's Galactapedia. `mcp.yaml` belongs to the user once it exists, so a new
template entry never reaches anyone who already has one. Each server is
appended here, unless one of that name is there already: someone may have added
it by hand, and their settings win. Neither is discoverable by default, so no
Wingman uses them until the user switches them on.

Azure voices come back to the subscription, next to Inworld (`wingman_pro.tts_provider`
can be `azure` again). The new `wingman_pro.azure` block is backfilled from the
template (Jenny, streaming on), which gives every Wingman a female voice. So each
Wingman that speaks through the subscription, or inherits its speech output and has
an Inworld voice of its own, gets the Azure voice of its Inworld voice's gender:
Andrew for a male one, Jenny otherwise. It is only used once the Wingman is switched
to Azure, by the user or by Core when the plan has no Inworld. Nobody is switched here.

Pocket TTS stays the default for English only. A user whose spoken language is
another one gets the subscription's Azure instead: the defaults, when they still
speak through Pocket TTS with the template's voice, and every shipped Wingman still
on Pocket TTS with a default voice move to `wingman_pro` / `azure`. A Wingman with a
Pocket voice of its own keeps it (pinned to `pocket_tts` when the defaults move), one
on another provider is left alone, English users are untouched. The rules and the
voice tables are shared with the settings switch (services/wingman_default_voices.py,
templates/pocket_tts and templates/azure, read like any current template). Only the
provider is set for a Wingman: its Azure voice moves to its language at the next
start, in apply_default_voices, which also records it as a default voice.

Nothing else changes.
"""

import copy
import os

from services.file import get_users_dir
from services.migrations.base_migration import BaseMigration
from services.wingman_default_voices import (
    DEFAULTS_FILE,
    TEMPLATE_DEFAULTS_FILE,
    default_voice_for,
    is_default_voice,
    load_default_voices,
    moves_to_azure,
    switch_defaults_to_azure,
    switch_wingman_to_azure,
)

# Kept in step with templates/configs/mcp.template.yaml, like the ElevenLabs
# entry in migration_320_to_321: a migration must produce the same config every
# time, whichever template happens to be installed.
ELITE_SERVER = {
    "name": "wingman_elite_dangerous",
    "display_name": "Elite Dangerous - Systems, Stations, Trade",
    "description": (
        "Elite Dangerous community data. Star systems and their stations, "
        "services nearby like refuel, repair or a material trader, commodity "
        "prices and modules at a station, the best cargo between two stations, "
        "and the materials and engineers for ship engineering. Not for the "
        "pilot's own ship, cargo or missions."
    ),
    "discovery_keywords": [
        "Elite Dangerous",
        "ED",
        "station",
        "nearest",
        "refuel",
        "repair",
        "material trader",
        "commodity prices",
        "trade",
        "engineering",
    ],
    "type": "http",
    "url": "https://wingman-ai-mcp-servers.wingman-ai.workers.dev/elite/mcp",
    "discoverable_by_default": False,
}

GALACTAPEDIA_SERVER = {
    "name": "wingman_galactapedia",
    "display_name": "Galactapedia - Star Citizen Lore",
    "description": (
        "Star Citizen lore from RSI's Galactapedia. People, factions, species, "
        "star systems, planets, ships and events of the Star Citizen universe "
        "and their history. Answers who is and what is questions about the "
        "lore. Not for ship stats, prices or game mechanics, which StarHead "
        "covers. Unofficial fan project, not affiliated with Cloud Imperium."
    ),
    "discovery_keywords": [
        "Star Citizen lore",
        "Galactapedia",
        "Star Citizen history",
        "UEE",
        "Vanduul",
        "Xi'an",
        "Banu",
        "Tevarin",
    ],
    "type": "http",
    "url": "https://wingman-ai-mcp-servers.wingman-ai.workers.dev/galactapedia/mcp",
    "discoverable_by_default": False,
}

NEW_SERVERS = [
    (ELITE_SERVER, "Elite Dangerous"),
    (GALACTAPEDIA_SERVER, "Galactapedia"),
]

# Kept in step with services/wingman_default_voices.py, copied so this
# migration gives the same result whatever that file says later.
AZURE_FEMALE_VOICE = "en-US-JennyMultilingualNeural"
AZURE_MALE_VOICE = "en-US-AndrewMultilingualNeural"
AZURE_VOICES_BY_LANGUAGE = {
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
}

# Male Inworld voices, lowercased. Inworld names carry no gender, so it is
# looked up here; a name not listed counts as female, like the template default.
INWORLD_MALE_VOICES = frozenset(
    {
        "alex", "blake", "carter", "clive", "craig", "dennis", "dominus",
        "edward", "hades", "mark", "ronald", "shaun", "theodore", "timothy",
        "matthias", "alain", "mathieu", "etienne", "diego", "miguel", "rafael",
        "gianni", "dmitry", "nikolai", "heitor", "szymon", "wojciech", "erik",
        "lennart", "yichen", "satoshi", "hyunwoo", "seojun",
        "alvaro",
        "bastian", "borja", "bruno", "cuauhtemoc", "curro", "fabian", "gonzalo",
        "hendrik", "ignacio", "inigo", "joaquin", "josef", "kilian", "mateo",
        "mauricio", "maximiliano", "nacho", "reinhard", "ruben", "salvador", "sergio",
        "tobias", "étienne",
    }
)

# Inworld voices made for one of our main markets, lowercased (live list of
# 2026-10-07). A German Wingman keeps a German voice when it moves to Azure.
INWORLD_VOICES_BY_LANGUAGE = {
    "de": frozenset({
        "annika", "bastian", "birgit", "carina", "fabian", "franziska", "heidi",
        "heike", "hendrik", "johanna", "josef", "kilian", "matthias", "reinhard",
        "sabine", "steffi", "tobias",
    }),
    "fr": frozenset({
        "alain", "hélène", "helene", "mathieu", "étienne", "etienne",
    }),
    "es": frozenset({
        "alvaro", "borja", "bruno", "camila", "citlali", "cuauhtemoc", "curro", "diego",
        "gonzalo", "guadalupe", "ignacio", "inigo", "inmaculada", "itzel", "joaquin",
        "lupita", "marta", "mateo", "mauricio", "maximiliano", "mayte", "mercedes",
        "miguel", "nacho", "paloma", "pilar", "rafael", "rocio", "ruben", "salvador",
        "sergio", "sofia", "ximena", "xochitl",
    }),
}


def azure_voice_for_inworld(voice_id) -> str:
    """The Azure voice closest to the Inworld voice ``voice_id``: same language
    when it is one of our main markets, same gender, Jenny for the unknown."""
    name = str(voice_id).strip().lower() if voice_id else ""
    male = name in INWORLD_MALE_VOICES
    for language, names in INWORLD_VOICES_BY_LANGUAGE.items():
        if name in names:
            female_voice, male_voice = AZURE_VOICES_BY_LANGUAGE[language]
            return male_voice if male else female_voice
    return AZURE_MALE_VOICE if male else AZURE_FEMALE_VOICE


class Migration325To326(BaseMigration):
    """Migration from 3.2.5 to 3.2.6."""

    old_version = "3_2_5"
    new_version = "3_2_6"

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Keep the user's MCP servers and add the Elite Dangerous and Galactapedia ones."""
        if not old:
            # No mcp.yaml before this point, so the template is already right.
            return new
        servers = old.get("servers")
        if not isinstance(servers, list):
            self.log_warning("mcp.yaml has no server list, leaving it alone.")
            return old
        present = {server.get("name") for server in servers if isinstance(server, dict)}
        for server, label in NEW_SERVERS:
            if server["name"] in present:
                continue
            servers.append(dict(server))
            self.log(f"- added the {label} MCP server")
        return old

    def migrate_defaults(self, old: dict) -> dict:
        config = self._set_azure_voice(old, "defaults", is_defaults=True)
        # Wingmen are migrated after the defaults (they sit in subfolders) and
        # inherit from them as they were before the switch.
        self._old_defaults = copy.deepcopy(config)
        self._defaults_on_pocket = (config.get("features") or {}).get("tts_provider") == "pocket_tts"
        self._defaults_switched = False
        language = self._spoken_language()
        if self._defaults_on_pocket and moves_to_azure(language):
            template = self.service.config_manager.read_config(
                os.path.join(self._app_root(), TEMPLATE_DEFAULTS_FILE)
            )
            self._defaults_switched = switch_defaults_to_azure(
                config, template if isinstance(template, dict) else {}, language
            )
            if self._defaults_switched:
                self.log(f"- defaults: Azure voices for spoken language {language}")
        return config

    def migrate_wingman(self, old: dict) -> dict:
        name = old.get("name", "wingman")
        config = self._set_azure_voice(old, name, is_defaults=False)
        language = self._spoken_language()
        if not getattr(self, "_defaults_on_pocket", False) or not moves_to_azure(language):
            return config
        table = self._pocket_table()
        voices = table.get(name)
        default_pocket = bool(voices) and is_default_voice(
            (config.get("pocket_tts") or {}).get("voice"),
            voices,
            # Wingman gave it this voice at every start since 3.2.4.
            default_voice_for(table, name, language),
        )
        result = switch_wingman_to_azure(
            config, self._old_defaults, self._defaults_switched, default_pocket, None
        )
        if result == "switched":
            self.log(f"- {name}: Azure voice for spoken language {language}")
        elif result == "kept":
            self.log(f"- {name}: keeps its own voice")
        return config

    def _spoken_language(self) -> str:
        """settings.spoken_language of the version migrated from, "en" when unset."""
        if not hasattr(self, "_language"):
            language = "en"
            try:
                settings = self.service.config_manager.read_config(
                    os.path.join(get_users_dir(), self.old_version, "configs", "settings.yaml")
                )
                if isinstance(settings, dict) and isinstance(settings.get("spoken_language"), str):
                    language = settings["spoken_language"]
            except Exception as e:
                self.log_warning(f"Could not read the spoken language: {e}")
            self._language = language
        return self._language

    def _app_root(self) -> str:
        return os.path.dirname(os.path.normpath(self.templates_dir))

    def _pocket_table(self) -> dict:
        if not hasattr(self, "_pocket_voices"):
            self._pocket_voices = load_default_voices(self._app_root(), DEFAULTS_FILE)
        return self._pocket_voices

    def _set_azure_voice(self, config: dict, label: str, is_defaults: bool) -> dict:
        """Give the config the Azure voice of its Inworld voice's gender."""
        features = config.get("features") if isinstance(config.get("features"), dict) else {}
        tts = features.get("tts_provider")
        inworld = config.get("inworld") if isinstance(config.get("inworld"), dict) else {}
        voice_id = inworld.get("voice_id")
        if tts is not None and tts != "wingman_pro":
            # Speaks through something else; the template voice is fine.
            return config
        if tts is None and not voice_id and not is_defaults:
            # Inherits both speech output and voice: the defaults' Azure voice fits.
            return config
        wingman_pro = config.get("wingman_pro")
        if wingman_pro is not None and not isinstance(wingman_pro, dict):
            return config
        wingman_pro = dict(wingman_pro or {})
        azure = dict(wingman_pro.get("azure") or {})
        if azure.get("voice"):
            return config
        azure["voice"] = azure_voice_for_inworld(voice_id)
        if is_defaults:
            # A Wingman inherits the streaming switch from the defaults.
            azure.setdefault("output_streaming", True)
        wingman_pro["azure"] = azure
        config["wingman_pro"] = wingman_pro
        self.log(f"- {label}: Azure voice {azure['voice']} (Inworld voice {voice_id or 'default'})")
        return config

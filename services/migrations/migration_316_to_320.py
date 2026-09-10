"""Migration from version 3.1.6 to 3.2.0.

3.2.0 moves Wingman Pro from the Azure backend to the new one
(see docs/backend-migration/plan.md, section 6). Three things change in a
user's config:

* `wingman_pro.base_url` points at api.wingman-ai.com, and `region` disappears —
  the new backend runs in one region, so there is nothing to choose.
* `wingman_pro.stt_provider`: `whisper` and `azure_speech` both become `cloud`.
  The backend decides which model transcribes, the client no longer does.
* `wingman_pro.tts_provider`: `azure` becomes `openai`. Azure Speech is gone, so
  an Azure voice name has to become an OpenAI one — the mapping below picks a
  voice of the same gender, and users who had a specific favourite will want to
  pick again.
* `wingman_pro.conversation_deployment` holds an alias now — `default` or
  `fast` — instead of a raw model name like `gpt-4.1-mini`. The backend owns
  the routing table, so a stored model name no longer matches anything the
  model list offers and the picker would come up empty.
"""

from services.migrations.base_migration import BaseMigration

NEW_BASE_URL = "https://api.wingman-ai.com"

# The aliases /api/v1/models serves. Anything else in a config is a model name
# from the Azure era.
DEFAULT_DEPLOYMENT = "default"
KNOWN_ALIASES = ("default", "fast")

# Azure voice names carry the gender in the name itself, e.g.
# "de-DE-KatjaNeural". Anything unknown lands on "nova", a neutral default.
FEMALE_OPENAI_VOICE = "nova"
MALE_OPENAI_VOICE = "onyx"
DEFAULT_OPENAI_VOICE = "nova"

# The female Azure voices Wingman shipped with, lowercased for matching.
KNOWN_FEMALE = (
    "katja", "amala", "elke", "gisela", "klarissa", "louisa", "maja", "tanja",
    "jenny", "aria", "ana", "michelle", "sara", "nancy", "amber", "ashley",
    "cora", "elizabeth", "jane", "monica", "denise", "eloise", "brigitte",
    "isabelle", "sofia", "elvira", "irene", "clara", "natasha", "libby",
)
KNOWN_MALE = (
    "conrad", "bernd", "christoph", "kasper", "killian", "klaus", "ralf",
    "guy", "davis", "tony", "jason", "brandon", "christopher", "eric",
    "jacob", "brian", "henri", "claude", "alvaro", "ryan", "william",
)


def azure_voice_to_openai(voice: str | None) -> str:
    if not voice:
        return DEFAULT_OPENAI_VOICE
    name = str(voice).lower()
    if any(part in name for part in KNOWN_FEMALE):
        return FEMALE_OPENAI_VOICE
    if any(part in name for part in KNOWN_MALE):
        return MALE_OPENAI_VOICE
    return DEFAULT_OPENAI_VOICE


class Migration316To320(BaseMigration):
    """Migration from 3.1.6 to 3.2.0."""

    old_version = "3_1_6"
    new_version = "3_2_0"

    def migrate_settings(self, old: dict) -> dict:
        new = dict(old)
        pro = dict(new.get("wingman_pro") or {})
        if pro:
            pro["base_url"] = NEW_BASE_URL
            pro.pop("region", None)
            new["wingman_pro"] = pro
            self.log("Wingman Pro points at the new backend, region setting removed")
        return new

    def migrate_defaults(self, old: dict) -> dict:
        return self._migrate_wingman_pro_section(dict(old), "defaults")

    def migrate_wingman(self, old: dict) -> dict:
        return self._migrate_wingman_pro_section(dict(old), old.get("name", "wingman"))

    def _migrate_wingman_pro_section(self, config: dict, label: str) -> dict:
        pro = config.get("wingman_pro")
        if not isinstance(pro, dict):
            return config

        pro = dict(pro)

        stt = pro.get("stt_provider")
        if stt in ("whisper", "azure_speech"):
            pro["stt_provider"] = "cloud"
            self.log(f"{label}: speech recognition '{stt}' -> 'cloud'")

        tts = pro.get("tts_provider")
        if tts == "azure":
            pro["tts_provider"] = "openai"
            azure = config.get("azure")
            old_voice = None
            if isinstance(azure, dict) and isinstance(azure.get("tts"), dict):
                old_voice = azure["tts"].get("voice")
            new_voice = azure_voice_to_openai(old_voice)

            openai_section = dict(config.get("openai") or {})
            openai_section["tts_voice"] = new_voice
            config["openai"] = openai_section
            self.log(f"{label}: speech output 'azure' -> 'openai', voice {old_voice or '—'} -> {new_voice}")

        deployment = pro.get("conversation_deployment")
        if deployment not in KNOWN_ALIASES:
            pro["conversation_deployment"] = DEFAULT_DEPLOYMENT
            self.log(
                f"{label}: conversation model '{deployment or '—'}' -> '{DEFAULT_DEPLOYMENT}'"
            )

        config["wingman_pro"] = pro
        return config

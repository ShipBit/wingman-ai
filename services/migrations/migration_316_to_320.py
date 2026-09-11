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
* Azure is gone as a provider of any kind, including for people who brought
  their own Azure account (docs/backend-migration/azure-ausbau.md). Anything
  pointing at it is rewritten to a provider that still exists, and the whole
  `azure:` block is dropped.
* `voice_activation.azure.languages` becomes `voice_activation.languages`. The
  list only ever sat under `azure` because that provider came first; the
  Wingman backend uses it to narrow its auto-detection.

The Azure names stay in this file on purpose: it is the only place that still
has to recognise them, because it is what reads the old configs.
"""

from services.migrations.base_migration import BaseMigration

NEW_BASE_URL = "https://api.wingman-ai.com"

# The aliases /api/v1/models serves. Anything else in a config is a model name
# from the Azure era.
DEFAULT_DEPLOYMENT = "default"
KNOWN_ALIASES = ("default", "fast")

# Where an Azure setting lands. Someone who paid for their own Azure account
# gets OpenAI, the closest equivalent they can point at their own key; local
# speech recognition goes to Parakeet, which is the default anyway.
AZURE_TTS_REPLACEMENT = "openai"
AZURE_LLM_REPLACEMENT = "openai"
AZURE_STT_REPLACEMENT = "parakeet"

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

        va = dict(new.get("voice_activation") or {})
        if va:
            azure = va.pop("azure", None)
            # The language list lived under `azure` and is still needed; the
            # region next to it is not.
            if isinstance(azure, dict) and azure.get("languages"):
                va["languages"] = azure["languages"]
                self.log(
                    f"voice activation languages moved out of the azure section: "
                    f"{', '.join(azure['languages'])}"
                )
            va.setdefault("languages", ["en-US"])

            if va.get("stt_provider") in ("azure", "azure_speech"):
                self.log(
                    f"voice activation '{va['stt_provider']}' -> "
                    f"'{AZURE_STT_REPLACEMENT}' (Azure Speech is gone, this one "
                    f"runs on your machine)"
                )
                va["stt_provider"] = AZURE_STT_REPLACEMENT
            new["voice_activation"] = va

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

        # Anything pointing at Azure, including a user's own Azure account.
        features = dict(config.get("features") or {})
        if features:
            if features.get("tts_provider") == "azure":
                features["tts_provider"] = AZURE_TTS_REPLACEMENT
                self.log(f"{label}: speech output 'azure' -> '{AZURE_TTS_REPLACEMENT}'")
            if features.get("stt_provider") in ("azure", "azure_speech"):
                was = features["stt_provider"]
                features["stt_provider"] = AZURE_STT_REPLACEMENT
                self.log(f"{label}: speech recognition '{was}' -> '{AZURE_STT_REPLACEMENT}'")
            if features.get("conversation_provider") == "azure":
                features["conversation_provider"] = AZURE_LLM_REPLACEMENT
                self.log(f"{label}: conversation 'azure' -> '{AZURE_LLM_REPLACEMENT}'")
            config["features"] = features

        # The transcription language list sat under azure.stt; it belongs to the
        # Wingman Pro section now, which is the thing that uses it.
        azure_cfg = config.get("azure")
        if isinstance(azure_cfg, dict) and isinstance(azure_cfg.get("stt"), dict):
            langs = azure_cfg["stt"].get("languages")
            if langs:
                pro["languages"] = langs
                self.log(f"{label}: transcription languages kept: {', '.join(langs)}")
        pro.setdefault("languages", ["en-US"])

        deployment = pro.get("conversation_deployment")
        if deployment not in KNOWN_ALIASES:
            pro["conversation_deployment"] = DEFAULT_DEPLOYMENT
            self.log(
                f"{label}: conversation model '{deployment or '—'}' -> '{DEFAULT_DEPLOYMENT}'"
            )

        # The azure section itself goes last, so the voice mapping above can
        # still read the old voice out of it.
        if config.pop("azure", None) is not None:
            self.log(f"{label}: azure settings removed, the provider no longer exists")

        config["wingman_pro"] = pro
        return config

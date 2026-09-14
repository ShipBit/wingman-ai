"""Migration from version 3.1.6 to 3.2.0.

3.2.0 moves Wingman Pro from the Azure backend to the new one. Three things
change in a user's config:

* `wingman_pro.base_url` points at api.wingman-ai.com, and `region` disappears —
  the new backend runs in one region, so there is nothing to choose.
* `wingman_pro.stt_provider`: `whisper` and `azure_speech` both become `cloud`.
  The backend decides which model transcribes, the client no longer does.
* `wingman_pro.tts_provider`: `azure` and `openai` both become `inworld`, the
  only speech provider the subscription still has. The mapping below keeps
  gender and, for Azure names, language; someone who had a specific favourite
  will want to pick again.
* `wingman_pro.conversation_deployment` holds a gateway model id now, not an
  Azure deployment name like `gpt-4.1-mini` and not the 3.1 aliases. A stored
  name that the plan does not offer is answered with the plan default rather
  than an error, so this only has to be plausible.
* Azure is gone as a provider of any kind, including for people who brought
  their own Azure account. Anything
  pointing at it is rewritten to a provider that still exists, and the whole
  `azure:` block is dropped.
* `voice_activation.azure.languages` becomes `voice_activation.languages`. The
  list only ever sat under `azure` because that provider came first; the
  Wingman backend uses it to narrow its auto-detection.
* `llama_cpp.run_locally` becomes `llama_cpp.mode`, and everyone lands on
  `cloud`. The support model behind memory and summarisation used to be a 2 GB
  llama.cpp process on the user's machine; it now runs on the backend, scores
  better in our own eval suite (0,98 against 0,89) and costs no hardware. The
  embedding model stays local either way — the vectors already in the database
  were computed by it.

The Azure names stay in this file on purpose: it is the only place that still
has to recognise them, because it is what reads the old configs.
"""

from services.migrations.base_migration import BaseMigration

NEW_BASE_URL = "https://api.wingman-ai.com"

# What goes into `conversation_deployment`. Since 2026-09-11 the backend serves
# real gateway ids instead of the aliases `default` and `fast`, so this is a
# model name, not a role.
#
# It going stale is harmless by design: a model the plan does not offer is
# answered with the plan default (`x-wingman-substituted`), and the client
# rewrites the config the next time the settings are opened. Naming the current
# default here only saves that one round.
FOLLOW_PLAN_DEFAULT = ""
"""What `conversation_deployment` holds when the plan decides.

Not a model name. The backend resolves an empty value to whatever its own plan
default currently is, so we can change that in /admin without shipping a Wingman
release and without a migration. Writing a concrete id here instead would pin
every upgrading user to the model that happened to be the default on the day
this file was written.
"""

# Where an Azure setting lands. Someone who paid for their own Azure account
# gets OpenAI, the closest equivalent they can point at their own key; local
# speech recognition goes to Parakeet, which is the default anyway.
AZURE_TTS_REPLACEMENT = "openai"
AZURE_LLM_REPLACEMENT = "openai"
AZURE_STT_REPLACEMENT = "parakeet"

# Inworld voices, picked from the live catalogue on 2026-09-11. The subscription
# has no other speech provider since OpenAI's voices were dropped: they cost
# three times as much, and the reason to keep them — Inworld having two poor
# German voices — ended when Inworld shipped 17 of them.
#
# An Azure voice name carries both language and gender: "de-DE-KatjaNeural".
# Both are worth keeping, so a German speaker stays German.
FEMALE_INWORLD_VOICE = "Ashley"
MALE_INWORLD_VOICE = "Edward"
FEMALE_INWORLD_VOICE_DE = "Johanna"
MALE_INWORLD_VOICE_DE = "Matthias"
DEFAULT_INWORLD_VOICE = FEMALE_INWORLD_VOICE

# The OpenAI voices a 3.1.6 config can hold, by gender, so someone who already
# moved off Azure keeps a voice of the same kind.
OPENAI_FEMALE = ("nova", "shimmer", "alloy", "coral", "sage")
OPENAI_MALE = ("onyx", "echo", "fable", "ash", "ballad", "verse")

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
    # Andrew was the Clippy template's voice, one of the three Azure voices
    # 3.1.6 shipped. Without it Clippy users come out with a female default.
    "andrew",
)


def voice_to_inworld(voice: str | None) -> str:
    """An Azure or OpenAI voice name to the closest Inworld one.

    Gender first, because that is what a user notices immediately, then
    language: an Azure name starting with `de-` keeps a German voice.
    """
    if not voice:
        return DEFAULT_INWORLD_VOICE
    name = str(voice).lower()
    german = name.startswith("de-") or name.startswith("de_")

    if any(part in name for part in KNOWN_FEMALE) or name in OPENAI_FEMALE:
        return FEMALE_INWORLD_VOICE_DE if german else FEMALE_INWORLD_VOICE
    if any(part in name for part in KNOWN_MALE) or name in OPENAI_MALE:
        return MALE_INWORLD_VOICE_DE if german else MALE_INWORLD_VOICE
    return FEMALE_INWORLD_VOICE_DE if german else DEFAULT_INWORLD_VOICE


class Migration316To320(BaseMigration):
    """Migration from 3.1.6 to 3.2.0."""

    old_version = "3_1_6"
    new_version = "3_2_0"

    def migrate_settings(self, old: dict) -> dict:
        new = dict(old)

        llama = dict(new.get("llama_cpp") or {})
        if llama:
            # `run_locally` said local or remote; `mode` says cloud, local or
            # server. Everyone moves to cloud, including someone who had a remote
            # llama-server: the old host and port stay in the config, so
            # switching back is one click and no retyping.
            ran_remotely = llama.pop("run_locally", None) is False
            llama["mode"] = "cloud"
            llama.setdefault("support_cloud_model", "")
            new["llama_cpp"] = llama
            self.log(
                "support model moved to the cloud"
                + (
                    " (your own llama-server stays configured under 'Own server')"
                    if ran_remotely
                    else ""
                )
            )

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

    def migrate_secrets(self, old: dict) -> dict:
        """Drop the Azure B2C token that 3.1.6 stored as `wingman_pro`.

        Until the client hands Core a device token, Core sends whatever sits in
        this key as a bearer to api.wingman-ai.com. After the migration that is
        the old Azure access token — a credential issued for a different
        service, now travelling to ours. The new backend answers 401, so nothing
        works differently; the token just leaves the group of people it was
        issued for, and it sits in plain text in secrets.yaml until the user
        signs in again.

        Device tokens start with `wgd_`. Anything else in this key is from the
        Azure era and has no purpose in 3.2.
        """
        new = dict(old)
        token = new.get("wingman_pro")
        if isinstance(token, str) and token and not token.startswith("wgd_"):
            self.log_highlight(
                "Removed the old Wingman Pro token — sign in again in the client "
                "to get a device token for the new backend."
            )
            new.pop("wingman_pro", None)
        return new

    def migrate_defaults(self, old: dict) -> dict:
        return self._migrate_wingman_pro_section(dict(old), "defaults")

    def migrate_wingman(self, old: dict) -> dict:
        return self._migrate_wingman_pro_section(dict(old), old.get("name", "wingman"))

    # What 3.1.6 shipped as the default, and what it becomes. Only a config
    # still sitting on the old value is touched — anyone who set their own number
    # keeps it.
    CONDENSE_DEFAULTS = {
        "condense_max_messages": (50, 150),
        "condense_keep_recent": (6, 12),
    }

    def _migrate_condense_defaults(self, features: dict, label: str) -> None:
        """Move the condensation thresholds to the new defaults.

        Two numbers decide when the conversation gets summarised: a token ceiling
        (in ``conversation_condenser``) and this message count. The token ceiling
        rises from 16,000 to 40,000 in 3.2.0, because the provider now caches the
        history after the prompt was restructured, which makes a longer
        conversation barely more expensive. If ``condense_max_messages`` stayed at
        50, the old number would keep firing first and none of the new ceiling
        would reach the user.

        ``condense_keep_recent`` from 6 to 12: six messages are three exchanges,
        and after that the wingman sounds like it briefly blacked out.
        """
        for key, (was, becomes) in self.CONDENSE_DEFAULTS.items():
            if features.get(key) == was:
                features[key] = becomes
                self.log(f"{label}: {key} {was} -> {becomes}")

    def _migrate_wingman_pro_section(self, config: dict, label: str) -> dict:
        # A per-wingman YAML only overrides the keys that differ from the
        # defaults, so most of them have no `wingman_pro` block at all. Bailing
        # out here — which this used to do — left `features.conversation_provider:
        # azure` untouched in exactly those files.
        existing_pro = config.get("wingman_pro")
        has_pro = isinstance(existing_pro, dict)
        pro = dict(existing_pro) if has_pro else {}

        stt = pro.get("stt_provider")
        if stt in ("whisper", "azure_speech"):
            pro["stt_provider"] = "cloud"
            self.log(f"{label}: speech recognition '{stt}' -> 'cloud'")

        # Both of the old values lead to Inworld now. `azure` kept its voice in
        # its own section, `openai` in `openai.tts_voice`.
        tts = pro.get("tts_provider")
        if tts in ("azure", "openai"):
            pro["tts_provider"] = "inworld"
            old_voice = None
            if tts == "azure":
                azure = config.get("azure")
                if isinstance(azure, dict) and isinstance(azure.get("tts"), dict):
                    old_voice = azure["tts"].get("voice")
            else:
                openai_section = config.get("openai")
                if isinstance(openai_section, dict):
                    old_voice = openai_section.get("tts_voice")

            # Only touch the shared `inworld` section when this config actually
            # speaks through Wingman Pro. `tts_provider: azure` was the shipped
            # 3.1.6 default, so it is set in nearly every file — including those
            # of people who drive Inworld with their own key and picked a voice
            # there. Overwriting that would silently replace their choice with
            # one mapped from an Azure voice they never used.
            #
            # A per-wingman file without `features.tts_provider` inherits from
            # defaults.yaml, which is migrated in the same run, so skipping it
            # here loses nothing.
            features_now = config.get("features")
            uses_pro_tts = (
                isinstance(features_now, dict)
                and features_now.get("tts_provider") == "wingman_pro"
            )
            if uses_pro_tts:
                new_voice = voice_to_inworld(old_voice)
                inworld_section = dict(config.get("inworld") or {})
                inworld_section["voice_id"] = new_voice
                config["inworld"] = inworld_section
                self.log(
                    f"{label}: speech output '{tts}' -> 'inworld', "
                    f"voice {old_voice or '—'} -> {new_voice}"
                )
            else:
                self.log(
                    f"{label}: Wingman Pro speech output '{tts}' -> 'inworld'; "
                    f"the inworld voice is left as it is, this config does not "
                    f"speak through Wingman Pro"
                )

        # Anything pointing at Azure, including a user's own Azure account.
        features = dict(config.get("features") or {})
        if features:
            self._migrate_condense_defaults(features, label)
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
        # No default here on purpose. WingmanProConfig.languages already defaults
        # to ["en-US"], and writing it into a per-wingman file would pin that
        # wingman: the config diff keeps any list that differs from the default
        # file, so a German user whose defaults say [de-DE, en-US] would end up
        # with one wingman stuck on English.

        # Everything a config can hold here is wrong now: Azure deployment names
        # ("gpt-4o-mini"), the 3.1 aliases ("default", "fast") and anything
        # hand-typed. A gateway id always has the shape provider/model, so that
        # is the test — it lets a model we add later pass without a code change.
        #
        # Anything that fails it becomes the empty value, which means "whatever
        # the plan offers as its default". A name that still parses is kept: that
        # is a deliberate pick, and if the plan drops it later the backend serves
        # its default anyway.
        if has_pro:
            deployment = pro.get("conversation_deployment")
            if not isinstance(deployment, str) or "/" not in deployment:
                pro["conversation_deployment"] = FOLLOW_PLAN_DEFAULT
                self.log(
                    f"{label}: conversation model '{deployment or '—'}' -> "
                    f"the plan default"
                )

        # The azure section itself goes last, so the voice mapping above can
        # still read the old voice out of it.
        if config.pop("azure", None) is not None:
            self.log(f"{label}: azure settings removed, the provider no longer exists")

        # Only write the block back if the file had one. Creating an empty
        # `wingman_pro:` in a wingman that never had it would fail validation —
        # its two provider fields are required — and it would also stop the
        # wingman inheriting the defaults.
        if has_pro:
            config["wingman_pro"] = pro
        return config

"""Migration from version 3.2.3 to 3.2.4.

3.2.4 adds a System One model: a decision layer in front of the main model.
It answers Wingman's typed questions — which command was asked for, which
skills a turn needs, whether the microphone heard a request at all, whether a
word the speech model wrote is a game name or the everyday word it looks like
— in about 300 ms, where a chat model takes over a second.

Two things follow for a config written by 3.2.3.

`settings.yaml` gains a `system_one` block, both switches on. The second one,
`commands`, is separate because it is the only decision that runs on spec:
every other use waits until there is something to resolve. Measured
2026-09-21 against gpt-4.1-mini on the shipped Star Citizen config, it puts
the keypress at 0.48 s instead of 1.13 s and the spoken confirmation at
1.49 s instead of 2.13 s; a request that is not a command costs 0.46 s and
changes nothing.

Commands gain a `description`, and the ones that came from a shipped template
get theirs filled in. It is what tells two commands apart that read alike —
"Autoland", "Autodock", "Toggle Landing System" and "Landing Sequence" all
mean "land the ship" to a reader who only has the names. Measured 2026-09-20
on 152 spoken transcripts: the chat model went from 0.884 to 0.952 with them
and the System One model from 0.863 to 0.973.

Only commands that still carry the shipped name and have no description are
touched. A command the user wrote, renamed or already described is left
alone, and the field stays optional: most commands never need one.

On by default because there is nothing to weigh up. The model behind it is a
fixed role of every plan, like transcription and speech, so it costs the user
nothing extra; and every decision it takes has the old path behind it, so a
plan without access or a backend that is down costs latency and changes no
answer. A user who turns it off gets exactly 3.2.3's behaviour.

The field is required on `SystemOneSettings`, so a settings.yaml without the
block would not load at all. It is still added here rather than left to the
repair that fills a stale settings.yaml from the template on load: the repair
is a safety net for files that skipped a migration, and a value the user is
meant to own belongs in the chain where the log says it was set.

`settings.yaml` also gains `show_token_count`, off. It decides whether the
client shows token counts on Wingman messages and in the status bar; those
counts are now what the provider reported for the whole turn, not an estimate
of the message text.

`settings.yaml` also gains `filler_responses`, on. While a slow tool runs and
the Wingman has said nothing yet, the support model writes one short line in
the user's language and the Wingman speaks it. It replaces the per-Wingman
`features.use_generic_instant_responses`, which is removed from defaults and
every Wingman: that switch was forced off in 2.0 and had no toggle since, and
the phrases it made were English whatever the user spoke (issue #391).

`settings.yaml` also gets one language for everything. `spoken_language` is
now one of en, de, fr, es, it, pt - the languages Parakeet v3, Pocket TTS and
Inworld all speak - and "multilingual" is gone. It was the default, and it
loaded the English Pocket TTS model: a German answer was read by an English
voice. The Pocket TTS model, the transcription hint and the Inworld language
are derived from `spoken_language` now, so `pocket_tts.model`,
`stt.languages` and `stt.parakeet.language` are removed; `pocket_tts` keeps
the size the user picked as `quality` and a custom YAML config as
`custom_model`. The language of a "multilingual" file is taken from what the
user had set up: the Pocket TTS model if it was not English, else English -
the client asks again whoever picked "multilingual" in it.
`stt.parakeet.model_variant` is removed too: Parakeet is always v3. v2 only
transcribed English and was only marginally better at it.

`pocket_tts.quantize` is switched off. With the torch Wingman ships, torchao
has no native kernels, and measured 2026-09-23 on an M2 Pro the quantized
model made audio only 1.05x faster than real time instead of 5.6x. The text
prompt at every sentence boundary then took up to 1.9 s, and playback ran dry
at the first one - the click a few seconds into every longer answer.
"""

import os
from os import path

import yaml

from services.migrations.base_migration import BaseMigration


SPOKEN_LANGUAGES = ("en", "de", "fr", "es", "it", "pt")

POCKET_TTS_MODEL_LANGUAGES = {
    "english": "en",
    "english_2026-01": "en",
    "english_2026-04": "en",
    "german": "de",
    "german_24l": "de",
    "french_24l": "fr",
    "spanish": "es",
    "spanish_24l": "es",
    "italian": "it",
    "italian_24l": "it",
    "portuguese": "pt",
    "portuguese_24l": "pt",
}
"""Pocket TTS model IDs up to 3.2.3 and the language each one speaks."""


class Migration323To324(BaseMigration):
    """Migration from 3.2.3 to 3.2.4."""

    old_version = "3_2_3"
    new_version = "3_2_4"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._descriptions: dict[str, str] | None = None

    def _shipped_descriptions(self) -> dict[str, str]:
        """Command name to description, from every template this build ships.

        Read from the templates rather than pasted in here because there are
        67 of them and two copies would drift. The risk that usually argues
        against this — a migration whose result depends on the installed
        files — does not apply: the templates ship with the build that runs
        the migration.
        """
        if self._descriptions is not None:
            return self._descriptions

        self._descriptions = {}
        configs = path.join(self.templates_dir, "configs")
        for root, _dirs, files in os.walk(configs):
            for file_name in files:
                if not file_name.endswith(".template.yaml"):
                    continue
                try:
                    with open(path.join(root, file_name), encoding="utf-8") as f:
                        template = yaml.safe_load(f) or {}
                except Exception as e:
                    self.log_warning(f"- could not read {file_name}: {e}")
                    continue
                for command in template.get("commands") or []:
                    name, text = command.get("name"), command.get("description")
                    if name and text:
                        self._descriptions[name] = text
        return self._descriptions

    def _drop_generic_instant_responses(self, old: dict) -> None:
        features = old.get("features")
        if isinstance(features, dict) and "use_generic_instant_responses" in features:
            del features["use_generic_instant_responses"]
            self.log("- removed features.use_generic_instant_responses (now settings.filler_responses)")

    def migrate_defaults(self, old: dict) -> dict:
        self._drop_generic_instant_responses(old)
        return old

    def migrate_wingman(self, old: dict) -> dict:
        """Fill in the descriptions for commands that came from a template."""
        self._drop_generic_instant_responses(old)
        commands = old.get("commands")
        if not isinstance(commands, list):
            return old

        shipped = self._shipped_descriptions()
        if not shipped:
            self.log_warning("- no command descriptions found in the templates; skipping")
            return old

        filled = 0
        for command in commands:
            if not isinstance(command, dict) or command.get("description"):
                continue
            text = shipped.get(command.get("name"))
            if text:
                command["description"] = text
                filled += 1

        if filled:
            self.log(
                f"- {filled} command(s) got the description the template ships, "
                "which is what tells two commands that read alike apart"
            )
        return old

    def _one_language(self, old: dict) -> None:
        """Replace the per-provider language settings by `spoken_language`."""
        pocket = old.get("pocket_tts") if isinstance(old.get("pocket_tts"), dict) else {}
        stt = old.get("stt") if isinstance(old.get("stt"), dict) else {}
        parakeet = stt.get("parakeet") if isinstance(stt.get("parakeet"), dict) else {}

        model = str(pocket.pop("model", "") or "")
        is_custom = model.lower().endswith((".yaml", ".yml"))
        model_language = POCKET_TTS_MODEL_LANGUAGES.get(model)

        spoken = old.get("spoken_language")
        if spoken not in SPOKEN_LANGUAGES:
            # "multilingual" read everything with the model's voice; a model
            # the user switched away from English says which language they
            # meant. The English default says nothing, so English it is.
            spoken = model_language or "en"
            self.log(f"- spoken_language: {spoken} (was '{old.get('spoken_language')}')")
        old["spoken_language"] = spoken

        if "quality" not in pocket:
            # french_24l is the only French model, so it is not a choice.
            high = model.endswith("_24l") and model != "french_24l"
            pocket["quality"] = "high" if high else "standard"
        if "custom_model" not in pocket:
            pocket["custom_model"] = model if is_custom else None
        if model:
            self.log(
                f"- pocket_tts: model '{model}' becomes quality '{pocket['quality']}'"
                + (f", custom_model '{model}'" if is_custom else "")
                + f"; the model now follows spoken_language ({spoken})"
            )
        if pocket.get("quantize"):
            pocket["quantize"] = False
            self.log("- pocket_tts.quantize: off — the quantized model was 5x slower and clicked")

        if stt.pop("languages", None) is not None:
            self.log("- removed stt.languages (now follows spoken_language)")
        if "language" in parakeet:
            del parakeet["language"]
            self.log("- removed stt.parakeet.language (Parakeet detects the language itself)")
        variant = parakeet.pop("model_variant", None)
        if variant == "v2":
            self.log(
                "- stt.parakeet.model_variant removed: Parakeet is always v3 now, "
                "v2 only transcribed English. v3 is downloaded on the next start; "
                "the v2 files in models/parakeet can be deleted."
            )
        elif variant is not None:
            self.log("- stt.parakeet.model_variant removed: Parakeet is always v3 now")

        if pocket:
            old["pocket_tts"] = pocket

    def migrate_settings(self, old: dict) -> dict:
        """Add the token count switch, off, and the System One block, on,
        unless the user already has them. Replace the per-provider language
        settings by the one `spoken_language`."""
        self._one_language(old)

        if "show_token_count" not in old:
            # Off: the counts on each message were an estimate of the message
            # text alone, which read like a cost and was not one. The real
            # counts are there for whoever wants them, behind a switch.
            old["show_token_count"] = False
            self.log("- show_token_count: off — token counts are hidden unless switched on")

        if "filler_responses" not in old:
            old["filler_responses"] = True
            self.log("- filler_responses: on — a short line in your language while a slow tool runs")

        block = old.get("system_one")
        if isinstance(block, dict):
            # Written by the load-time repair before this ran. Whatever it
            # says is the user's now — overwriting it here would switch the
            # feature back on for someone who had already turned it off. Only
            # a key that is missing outright is filled in, so the file still
            # satisfies a model where both fields are required.
            if "enabled" not in block:
                block["enabled"] = True
            if "commands" not in block:
                block["commands"] = True
            return old

        old["system_one"] = {"enabled": True, "commands": True}
        self.log(
            "- system_one: on — misheard names, stray noise and which command "
            "a request means are decided by a System One model first"
        )
        return old

"""One place that turns a recording into text.

Push-to-talk and voice activation both land here, so what the user said is
transcribed by the provider chosen in Settings, whichever way the recording
was started. Before 3.2.2 push-to-talk read a per-wingman provider and voice
activation a global one; the same audio could take two different engines.

The provider objects are the shared singletons WingmanCore owns. Calls are
synchronous: every provider blocks on a model or an HTTP request, and both
callers already run on a worker thread.
"""

import traceback
from typing import TYPE_CHECKING, Callable, Optional

from api.enums import LogType, SttProvider
from services.audio.vocabulary import Vocabulary, apply_override, load_preset
from services.jev_gate import JevGate
from services.printr import Printr

if TYPE_CHECKING:
    from providers.parakeet import Parakeet
    from services.secret_keeper import SecretKeeper
    from services.settings_service import SettingsService


class SttService:
    def __init__(
        self,
        settings_service: "SettingsService",
        secret_keeper: "SecretKeeper",
        parakeet: "Parakeet",
        get_hotwords: Optional[Callable[[], list[str]]] = None,
        app_root_path: str = ".",
    ):
        self.settings_service = settings_service
        self.app_root_path = app_root_path
        self.secret_keeper = secret_keeper
        self.parakeet = parakeet
        # Names the decoder should recognise, read fresh on every call so a
        # config switch (other wingmen, other names) is picked up without a
        # restart. WingmanCore hands in the names of the active wingmen.
        self.get_hotwords = get_hotwords or (lambda: [])
        self.printr = Printr()
        self._preset_cache: dict[str, list[str]] = {}
        # Prototype, off unless WINGMAN_JEV is set. See services/jev_gate.py.
        self.jev = JevGate(wingman_name="STT")

    @property
    def provider(self) -> SttProvider:
        return self.settings_service.settings.stt.provider

    def transcribe(self, filename: str) -> str | None:
        """Text for the recording, or None when there was nothing to hear or
        the provider failed. Failures are reported to the user here; callers
        only need to handle the None."""
        provider = self.provider
        try:
            text = self._transcribe(provider, filename)
        except Exception as e:
            self.printr.print(
                f"Error during transcription using '{provider.value}': {str(e)}",
                color=LogType.ERROR,
            )
            self.printr.print(
                traceback.format_exc(), color=LogType.ERROR, server_only=True
            )
            return None

        text = (text or "").strip()
        if not text:
            self.printr.print(
                "ignored empty transcription - probably just noise.",
                server_only=True,
            )
            return None
        corrected = self._correct(text)
        if corrected != text:
            self.printr.print(
                f"Vocabulary: '{text}' -> '{corrected}'", server_only=True, color=LogType.INFO
            )
        return corrected

    def _correct(self, text: str) -> str:
        """The transcript with the misheard names put right.

        Without the gate this is the fuzzy matcher on its own, which decides
        by letters and a blocklist of everyday words. Both of its mistakes
        are silent: "radar" becomes the outpost "Yadar" because radar is not
        on the blocklist, and "station" can never become "Stanton" because
        it is. Whether a word is the name or the everyday word is in the
        sentence around it, which is what the gate asks about.

        Every way this can fail — gate off, no key, gateway down, Jev unsure
        — ends in the matcher's own answer, which is today's behaviour.
        """
        vocabulary = self.vocabulary()
        if not self.jev.active:
            return vocabulary.correct(text)

        proposals = vocabulary.proposals(text)
        if not proposals:
            return text
        confirmed = self.jev.confirm_vocabulary(text, proposals)
        if confirmed is None:
            return vocabulary.correct(text)

        corrected = text
        for index in sorted(confirmed):
            heard, entry, _blocked = proposals[index]
            corrected = corrected.replace(heard, entry, 1)
        return corrected

    def vocabulary(self) -> Vocabulary:
        """The user's list plus the names of the active wingmen and whatever
        their skills added. Built per call; the lists are short and may
        change between two utterances."""
        stt = self.settings_service.settings.stt
        words = list(stt.vocabulary or []) + self.get_hotwords()
        for preset_id in stt.presets or []:
            if preset_id not in self._preset_cache:
                self._preset_cache[preset_id] = load_preset(self.app_root_path, preset_id)
            words += apply_override(
                self._preset_cache[preset_id], (stt.preset_overrides or {}).get(preset_id)
            )
        return Vocabulary(words)

    def _transcribe(self, provider: SttProvider, filename: str) -> str | None:
        stt = self.settings_service.settings.stt

        if provider == SttProvider.PARAKEET:
            result = self.parakeet.transcribe(
                config=stt.parakeet_config, filename=filename
            )
            return result.text if result else None

        if provider == SttProvider.WINGMAN_PRO:
            from providers.wingman_subscription import WingmanSubscription

            subscription = WingmanSubscription(
                wingman_name="system",
                settings=self.settings_service.settings.wingman_pro,
            )
            result = subscription.transcribe(
                filename=filename, languages=stt.languages
            )
            return result.text if result else None

        self.printr.toast_error(f"Unknown speech-to-text provider '{provider}'.")
        return None

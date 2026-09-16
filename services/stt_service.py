"""One place that turns a recording into text.

Push-to-talk and voice activation both land here, so what the user said is
transcribed by the provider chosen in Settings, whichever way the recording
was started. Before 3.2.2 push-to-talk read a per-wingman provider and voice
activation a global one; the same audio could take two different engines.

The provider objects are the shared singletons WingmanCore owns. Calls are
synchronous: every provider blocks on a model or an HTTP request, and both
callers already run on a worker thread.
"""

import re
import traceback
from typing import TYPE_CHECKING, Callable, Optional

from api.enums import LogType, SttProvider
from services.audio.vocabulary import Vocabulary
from services.printr import Printr

if TYPE_CHECKING:
    from providers.faster_whisper import FasterWhisper
    from providers.parakeet import Parakeet
    from providers.whispercpp import Whispercpp
    from services.secret_keeper import SecretKeeper
    from services.settings_service import SettingsService

# whisper.cpp likes to describe the room: "(wind blowing)", "[music]", "*sighs*".
_NOISE_PATTERN = re.compile(r"(\(.*?\))|(\[.*?\])|(\*.*?\*)")
_WHITESPACE_PATTERN = re.compile(r"[\s,]+")


class SttService:
    def __init__(
        self,
        settings_service: "SettingsService",
        secret_keeper: "SecretKeeper",
        whispercpp: "Whispercpp",
        fasterwhisper: "FasterWhisper",
        parakeet: "Parakeet",
        get_hotwords: Optional[Callable[[], list[str]]] = None,
    ):
        self.settings_service = settings_service
        self.secret_keeper = secret_keeper
        self.whispercpp = whispercpp
        self.fasterwhisper = fasterwhisper
        self.parakeet = parakeet
        # Names the decoder should recognise, read fresh on every call so a
        # config switch (other wingmen, other names) is picked up without a
        # restart. WingmanCore hands in the names of the active wingmen.
        self.get_hotwords = get_hotwords or (lambda: [])
        self.printr = Printr()

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
        corrected = self.vocabulary().correct(text)
        if corrected != text:
            self.printr.print(
                f"Vocabulary: '{text}' -> '{corrected}'", server_only=True, color=LogType.INFO
            )
        return corrected

    def vocabulary(self) -> Vocabulary:
        """The user's list plus the names of the active wingmen and whatever
        their skills added. Built per call; the lists are short and may
        change between two utterances."""
        stt = self.settings_service.settings.stt
        return Vocabulary(list(stt.vocabulary or []) + self.get_hotwords())

    def _transcribe(self, provider: SttProvider, filename: str) -> str | None:
        stt = self.settings_service.settings.stt

        if provider == SttProvider.PARAKEET:
            result = self.parakeet.transcribe(
                config=stt.parakeet_config, filename=filename
            )
            return result.text if result else None

        if provider == SttProvider.FASTER_WHISPER:
            result = self.fasterwhisper.transcribe(
                config=stt.fasterwhisper_config,
                filename=filename,
                hotwords=self.vocabulary().entries,
            )
            return result.text if result else None

        if provider == SttProvider.WHISPERCPP:
            result = self.whispercpp.transcribe(
                filename=filename, config=stt.whispercpp_config
            )
            if not result:
                return None
            cleaned = _WHITESPACE_PATTERN.sub(
                " ", _NOISE_PATTERN.sub("", result.text)
            ).strip()
            if cleaned != result.text:
                self.printr.print(
                    f"Cleaned original transcription: {result.text}",
                    server_only=True,
                    color=LogType.SYSTEM,
                )
            return cleaned

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

        if provider == SttProvider.OPENAI:
            from providers.open_ai import OpenAi

            # Secrets are loaded at startup and refreshed on save; the sync
            # retrieve path is not available on this thread.
            api_key = self.secret_keeper.secrets.get("openai")
            if not api_key:
                self.printr.toast_error(
                    "OpenAI is the speech-to-text provider but no OpenAI API key is set."
                )
                return None
            result = OpenAi(api_key=api_key).transcribe(filename=filename)
            return result.text if result else None

        if provider == SttProvider.GROQ:
            from providers.open_ai import OpenAi

            api_key = self.secret_keeper.secrets.get("groq")
            if not api_key:
                self.printr.toast_error(
                    "Groq is the speech-to-text provider but no Groq API key is set."
                )
                return None
            groq = OpenAi(api_key=api_key, base_url="https://api.groq.com/openai/v1/")
            result = groq.transcribe(filename=filename, model="whisper-large-v3-turbo")
            return result.text if result else None

        self.printr.toast_error(f"Unknown speech-to-text provider '{provider}'.")
        return None

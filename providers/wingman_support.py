from typing import Optional

import requests

from api.enums import CommandTag, LogType
from api.interface import LlamaCppSettings, WingmanProSettings
from providers.llama_cpp_provider import SupportResult
from services.printr import Printr
from services.secret_keeper import SecretKeeper

printr = Printr()


class WingmanSupport:
    """The support model, run on our backend instead of on the user's machine.

    Same job as ``LlamaCppProvider.support()`` — summarise, extract, compress —
    and the same ``SupportResult`` back, so ``LocalAiService`` can swap one for
    the other without any caller noticing.

    Every call goes to ``/api/v1/support/completions``, which resolves the model
    from the plan's support lane. Core sends the id it has, and a plan that no
    longer offers it gets the plan default instead of an error.

    Failures never raise. A summary that did not happen costs the user a slightly
    longer conversation history; an exception out of a background task would cost
    them the task itself, and these calls run inside ``run_in_executor`` where
    nobody is watching for one.
    """

    def __init__(self, subscription: WingmanProSettings, settings: LlamaCppSettings):
        self.subscription = subscription
        self.settings = settings
        self.secret_keeper = SecretKeeper()
        self.timeout = 180
        """Long on purpose: squeezing a 78k-token tool response takes about five
        seconds on gemini-2.5-flash-lite and seventeen on qwen3.7-flash."""
        self._reported_status: Optional[int] = None
        """The refusal we already told the user about.

        One turn makes several support calls — memory extraction, condensation,
        tool-response compression. Without this, a used-up allowance fires a
        toast on each of them, several times per turn, for the rest of the
        month. Cleared on the next answer that works, so a genuinely new problem
        is reported again."""

    def update_settings(self, new_settings: LlamaCppSettings):
        self.settings = new_settings

    def update_subscription(self, subscription: WingmanProSettings):
        self.subscription = subscription

    def is_ready(self) -> bool:
        """Whether we have something to authenticate with.

        Whether the plan actually includes a support model is the backend's
        answer, not ours, and asking it here would mean a network round trip on
        every readiness check — several per conversation turn.
        """
        return bool(self.secret_keeper.secrets.get("wingman_pro", ""))

    def support(
        self,
        text: str,
        system_prompt: str = "",
        max_tokens: int = 512,
        temperature: float = 1.0,
        top_p: float = 1.0,
        top_k: int = 20,
        presence_penalty: float = 2.0,
        reasoning: bool | None = None,
    ) -> SupportResult:
        """Run one support call on the backend.

        ``top_k`` and ``reasoning`` are accepted and not sent. ``top_k`` is a
        llama.cpp parameter that hosted models answer 400 for, and the backend
        turns reasoning off for every support call — measured 2026-09-12, the
        prompts score the same without it and answer in a fraction of the time.
        """
        if not system_prompt:
            from services.file import get_prompt

            system_prompt = get_prompt("support-default")

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
        }
        chosen = (self.settings.support_cloud_model or "").strip()
        if chosen:
            payload["model"] = chosen

        try:
            response = requests.post(
                url=f"{self.subscription.base_url}/api/v1/support/completions",
                headers={
                    "Authorization": f"Bearer {self.secret_keeper.secrets.get('wingman_pro', '')}"
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            printr.print(
                f"[Support] Could not reach the Wingman backend: {error}",
                color=LogType.WARNING,
                server_only=True,
            )
            return SupportResult(text=None)

        if response.status_code == 403:
            # Signed in, but this plan has no support lane. Sending them to the
            # login screen would be a dead end — say what is missing instead.
            if self._reported_status == 403:
                return SupportResult(text=None)
            self._reported_status = 403
            message = ""
            try:
                message = (response.json().get("message") or "").strip()
            except Exception:
                pass
            printr.print(
                text=(message or "Your plan has no support model.")
                + " Switch the support model to Local in Settings to keep memory "
                "and summaries working.",
                color=LogType.ERROR,
                server_only=True,
            )
            return SupportResult(text=None)

        if response.status_code == 401:
            printr.print(
                text="Unauthorized",
                command_tag=CommandTag.UNAUTHORIZED,
                color=LogType.ERROR,
            )
            return SupportResult(text=None)

        if response.status_code == 429:
            # The backend's sentence knows the plan; ours only knows there is a
            # limit. Either way, say what still works: the local model does.
            if self._reported_status == 429:
                return SupportResult(text=None)
            self._reported_status = 429
            message = ""
            try:
                message = (response.json().get("message") or "").strip()
            except Exception:
                pass
            printr.toast_error(
                (message or "The monthly allowance is used up.")
                + " Memory and summaries pause until it resets, or switch the "
                "support model to Local in Settings."
            )
            return SupportResult(text=None)

        if not response.ok:
            printr.print(
                f"[Support] The backend answered {response.status_code}.",
                color=LogType.WARNING,
                server_only=True,
            )
            return SupportResult(text=None)

        self._reported_status = None
        try:
            body = response.json()
            choice = body["choices"][0]
            content: Optional[str] = choice["message"].get("content") or None
            usage = body.get("usage") or {}
            return SupportResult(
                text=content,
                prompt_tokens=usage.get("prompt_tokens") or 0,
                completion_tokens=usage.get("completion_tokens") or 0,
                truncated=choice.get("finish_reason") == "length",
            )
        except (KeyError, IndexError, ValueError) as error:
            printr.print(
                f"[Support] Could not read the backend's answer: {error}",
                color=LogType.WARNING,
                server_only=True,
            )
            return SupportResult(text=None)

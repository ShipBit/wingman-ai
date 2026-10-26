"""
Proactive comments skill.

After a random stretch of silence (interval_range) the Wingman says something
on its own: about the conversation so far or, with vision_enabled, about the
screen. It says at most max_proactive_messages lines until the user talks
again. With allow_comments_without_history it also talks when there is no
conversation yet (narrator mode, needs vision).

The skill is auto-activated, so prepare() runs when the Wingman loads and
auto_start can start the comments right away.
"""

import asyncio
import random
import time
from typing import TYPE_CHECKING, Optional

from api.enums import SpeechPriority
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.image_generation import vision_base64
from services.skill_local_ai import SamplingPreset
from skills.skill_base import Skill, command_action, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

# How often the background loop looks at the clock.
TICK_SECONDS = 2
# Messages from the history that go into the prompt, and their length each.
HISTORY_MESSAGES = 10
HISTORY_CHARS = 500
# Longest line the skill says.
COMMENT_CHARS = 400


class ProactiveComments(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.is_running = False
        self.loaded = False
        # A new run id ends the loop of the old one.
        self.run_id = 0
        self.last_activity = time.monotonic()
        self.silence_target = 0
        # Lines said since the user last talked.
        self.proactive_message_count = 0
        # Lines said but not yet noted in the history.
        self.unnoted: list[str] = []

    # --- custom properties, read fresh every time ---------------------------------

    def _prop(self, property_id: str):
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value(property_id, errors)

    def _interval(self) -> tuple[int, int]:
        value = self._prop("interval_range") or [60, 180]
        low, high = int(value[0]), int(value[1])
        return max(10, low), max(10, low, high)

    def _max_messages(self) -> int:
        return max(1, int(self._prop("max_proactive_messages") or 3))

    def _vision_enabled(self) -> bool:
        return bool(self._prop("vision_enabled"))

    def _display(self) -> int:
        try:
            return max(1, int(self._prop("display") or 1))
        except (TypeError, ValueError):
            return 1

    def _add_to_history(self) -> bool:
        return bool(self._prop("add_comments_to_history"))

    def _narrator_mode(self) -> bool:
        return bool(self._prop("allow_comments_without_history"))

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        for property_id in (
            "interval_range",
            "max_proactive_messages",
            "vision_enabled",
            "display",
            "add_comments_to_history",
            "auto_start",
            "allow_comments_without_history",
        ):
            self.retrieve_custom_property_value(property_id, errors)
        prompt = self.retrieve_custom_property_value("custom_system_prompt", errors)
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Proactive Comments: the System Prompt is empty.",
                )
            )
        return errors

    # --- lifecycle ------------------------------------------------------------------

    async def prepare(self) -> None:
        await super().prepare()
        self.loaded = True
        if self._prop("auto_start") and not self.is_running:
            self._start()

    async def unload(self) -> None:
        self.loaded = False
        self.is_running = False
        self.run_id += 1
        await super().unload()

    async def on_add_user_message(self, message: str) -> None:
        self.last_activity = time.monotonic()
        self.proactive_message_count = 0
        # Runs before the user's message is added, so the note lands in front
        # of it. A line added with add_assistant comes back appended to the
        # Wingman's next answers.
        lines, self.unnoted = self.unnoted, []
        if lines and self._add_to_history():
            await self.wingman.conversation.add_note(
                "while the user was quiet you said this on your own, "
                "do not say it again: " + " / ".join(lines)
            )

    async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
        self.last_activity = time.monotonic()

    # --- background loop ------------------------------------------------------------

    def _start(self) -> None:
        self.is_running = True
        self.run_id += 1
        self.last_activity = time.monotonic()
        self.proactive_message_count = 0
        self._new_silence_target()
        self.wingman.run_in_thread(self._loop, self.run_id)

    def _is_active(self, run_id: int) -> bool:
        return run_id == self.run_id and self.is_running and self.loaded

    def _new_silence_target(self) -> None:
        low, high = self._interval()
        self.silence_target = random.randint(low, high)

    def _should_wait(self) -> bool:
        """The user talks to a wingman or a voice plays. Radio chatter does not
        count: a comment talks over it."""
        return (
            self.wingman.conversation.user_busy
            or self.wingman.audio.is_playing_at_least(SpeechPriority.EVENT)
        )

    async def _loop(self, run_id: int) -> None:
        """Runs on its own thread and event loop until the run id changes."""
        while self._is_active(run_id):
            await asyncio.sleep(TICK_SECONDS)
            if not self._is_active(run_id):
                return
            try:
                if self._should_wait():
                    # Silence starts when the user and the Wingman are done.
                    self.last_activity = time.monotonic()
                    continue
                if time.monotonic() - self.last_activity < self.silence_target:
                    continue
                if self.proactive_message_count >= self._max_messages():
                    continue
                await self._comment(run_id)
                self.last_activity = time.monotonic()
                self._new_silence_target()
            except Exception as e:
                self.log.error(f"Proactive Comments: {e}", server_only=True)
                self.last_activity = time.monotonic()

    # --- the comment ----------------------------------------------------------------

    def _history_text(self) -> str:
        lines = []
        for message in self.wingman.conversation.history():
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            content = message.get("content")
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if isinstance(content, str) and content.strip():
                lines.append(f"{role}: {content.strip()[:HISTORY_CHARS]}")
        return "\n".join(lines[-HISTORY_MESSAGES:])

    async def _capture_screen(self) -> Optional[str]:
        """The configured display as base64 JPEG, or None."""
        if not await self.wingman.ai.sees_images():
            self.log.warning(
                "Proactive Comments: the main model does not take images, vision is skipped.",
                server_only=True,
            )
            return None
        try:
            image = await self.wingman.screen.capture(self._display())
        except RuntimeError as e:
            self.log.warning(f"Proactive Comments: could not capture the screen: {e}")
            return None
        return await asyncio.to_thread(vision_base64, image)

    async def _comment(self, run_id: int) -> None:
        history_text = self._history_text()
        screenshot = await self._capture_screen() if self._vision_enabled() else None
        if not history_text and not (screenshot and self._narrator_mode()):
            return

        language = self.wingman.language.name
        system = (
            f"{self._prop('custom_system_prompt')}\n\n"
            f"You are {self.wingman.name}. Stay IN CHARACTER:\n"
            f"{self.wingman.config.prompts.backstory or ''}\n\n"
            f"Rules:\n"
            f"- One or two short sentences, spoken aloud.\n"
            f"- Do NOT use markdown, lists or emojis.\n"
            f"- Write in {language}."
        )
        parts = [
            "Recent conversation:\n" + (history_text or "(no conversation yet)"),
            f"This is comment {self.proactive_message_count + 1} of at most "
            f"{self._max_messages()} since the user last spoke.",
        ]
        if screenshot:
            parts.append("The attached screenshot shows what the user sees right now.")
        prompt = "\n\n".join(parts) + f"\n\nYour comment, in {language}:"

        if screenshot:
            line = await self.wingman.ai.generate(
                prompt, system=system, image=f"data:image/jpeg;base64,{screenshot}"
            )
        elif self.wingman.local_ai.available:
            line = await self.wingman.local_ai.generate(
                prompt, system=system, preset=SamplingPreset.CREATIVE
            )
        else:
            line = await self.wingman.ai.generate(prompt, system=system)
        line = line.strip().strip('"').strip()[:COMMENT_CHARS]
        if len(line) < 5:
            return
        if not self._is_active(run_id) or self._should_wait():
            # Turned off, or the user started talking while the line was written.
            return

        self.proactive_message_count += 1
        self.unnoted.append(line)
        await self.wingman.conversation.show(line, skill_name=self.config.display_name)
        await self.wingman.tts.speak(line, priority=SpeechPriority.EVENT)

    # --- tools ----------------------------------------------------------------------

    @tool(
        name="turn_on_proactive_comments",
        description="Turn on proactive comments: you speak up on your own when it is quiet for a while.",
    )
    @command_action(
        label="Turn proactive comments on",
        description="The Wingman speaks up on its own when it is quiet for a while.",
        respond="speak",
    )
    def turn_on_proactive_comments(self) -> str:
        if self.is_running:
            return "Proactive comments were already on."
        self._start()
        return "Proactive comments are now on."

    @tool(
        name="turn_off_proactive_comments",
        description="Turn off proactive comments.",
    )
    @command_action(
        label="Turn proactive comments off",
        description="The Wingman only talks when spoken to.",
        respond="speak",
    )
    def turn_off_proactive_comments(self) -> str:
        if not self.is_running:
            return "Proactive comments were already off."
        self.is_running = False
        self.run_id += 1
        return "Proactive comments are now off."

"""
Proactive comments skill.

Comments based on the ongoing conversation with the user or, optionally, via vision (vision_enabled).
In optional narrator mode (allow_comments_without_history), will comment up to a set number of times (max_proactive_messages) without further user input.
The user can customize the minimum (min_silence_threshold_seconds) and maximum (max_silence_threshold_seconds) intervals for comments to generate.
The exact comment time will be randomly set within that range each cycle.
The skill must be set in default_config.yaml to autostart, else the loop does not run.
"""

import asyncio
import time
import random
from typing import TYPE_CHECKING, Optional

from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.image_generation import vision_base64
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class ProactiveComments(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        # Configurable properties (defaults; overridden in validate())
        self.min_silence_threshold_seconds: int = 60
        self.max_silence_threshold_seconds: int = 180
        self.max_proactive_messages: int = 3
        self.vision_enabled: bool = False
        self.add_comments_to_history: bool = True
        self.custom_system_prompt: Optional[str] = None
        self.auto_start: bool = False
        self.allow_comments_without_history: bool = False

        # Internal state
        self.last_message_time: float = time.time()
        self.proactive_message_count: int = 0
        self.last_known_message_count: int = 0
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.current_silence_target: float = 0

    def _get_display(self) -> int:
        """Retrieve the display number fresh at runtime."""
        errors: list[WingmanInitializationError] = []
        display = self.retrieve_custom_property_value("display", errors)
        try:
            return max(1, int(display)) if display is not None else 1
        except (TypeError, ValueError):
            return 1

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        min_silence = self.retrieve_custom_property_value(
            "min_silence_threshold_seconds", errors
        )
        if min_silence is not None:
            self.min_silence_threshold_seconds = min_silence

        max_silence = self.retrieve_custom_property_value(
            "max_silence_threshold_seconds", errors
        )
        if max_silence is not None:
            self.max_silence_threshold_seconds = max_silence

        max_messages = self.retrieve_custom_property_value(
            "max_proactive_messages", errors
        )
        if max_messages is not None:
            self.max_proactive_messages = max_messages

        vision_enabled = self.retrieve_custom_property_value("vision_enabled", errors)
        if vision_enabled is not None:
            self.vision_enabled = vision_enabled

        # Validate display property exists (value retrieved fresh at runtime)
        self.retrieve_custom_property_value("display", errors)

        add_history = self.retrieve_custom_property_value(
            "add_comments_to_history", errors
        )
        if add_history is not None:
            self.add_comments_to_history = add_history

        custom_prompt = self.retrieve_custom_property_value(
            "custom_system_prompt", errors
        )
        if custom_prompt is None:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="System Prompt is missing or not configured in the skill settings.",
                )
            )
        elif not isinstance(custom_prompt, str):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="System Prompt must be a string.",
                )
            )
        elif not custom_prompt.strip():
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="System Prompt cannot be empty.",
                )
            )
        else:
            self.custom_system_prompt = custom_prompt

        auto_start = self.retrieve_custom_property_value("auto_start", errors)
        if auto_start is not None:
            self.auto_start = auto_start
        if not isinstance(self.auto_start, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Start Automatically must be a boolean.",
                )
            )

        narrator_mode = self.retrieve_custom_property_value(
            "allow_comments_without_history", errors
        )
        if narrator_mode is not None:
            self.allow_comments_without_history = narrator_mode
        if not isinstance(self.allow_comments_without_history, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Allow Comments Without History must be a boolean.",
                )
            )

        # Range validations
        if (
            not isinstance(self.min_silence_threshold_seconds, int)
            or self.min_silence_threshold_seconds <= 0
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Min Silence Threshold must be a positive integer.",
                )
            )
        if (
            not isinstance(self.max_silence_threshold_seconds, int)
            or self.max_silence_threshold_seconds <= 0
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Max Silence Threshold must be a positive integer.",
                )
            )
        if (
            isinstance(self.min_silence_threshold_seconds, int)
            and isinstance(self.max_silence_threshold_seconds, int)
            and self.min_silence_threshold_seconds > self.max_silence_threshold_seconds
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Min Silence Threshold cannot be greater than Max Silence Threshold.",
                )
            )
        if (
            not isinstance(self.max_proactive_messages, int)
            or self.max_proactive_messages <= 0
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Max Proactive Messages must be a positive integer.",
                )
            )
        if not isinstance(self.vision_enabled, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Enable Vision must be a boolean.",
                )
            )
        if not isinstance(self.add_comments_to_history, bool):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Add Comments to History must be a boolean.",
                )
            )

        return errors

    async def prepare(self) -> None:
        """Initialize state and start the background monitoring task."""
        self.last_message_time = time.time()
        self.proactive_message_count = 0
        self.last_known_message_count = 0
        await self._set_new_silence_target()

        self.is_running = self.auto_start

        if not self._task or self._task.done():
            self._task = asyncio.ensure_future(
                self._monitor_silence_and_comments()
            )

        if self.is_running:
            self.log.info("Proactive Comments: monitoring auto-started.")

    async def unload(self) -> None:
        """Stop the background monitoring task and clean up."""
        await self._stop_monitoring()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except asyncio.CancelledError:
                self.log.info(
                    "Proactive Comments: monitoring task cancelled during unload."
                )
            except asyncio.TimeoutError:
                self.log.warning(
                    "Proactive Comments: monitoring task did not cancel within timeout."
                )
            except Exception as e:
                self.log.warning(
                    f"Proactive Comments: error awaiting task cancellation: {e}"
                )
        self._task = None

    # Monitoring helpers
    async def _start_monitoring(self) -> bool:
        """Activate monitoring and reset state. Returns True if newly started."""
        if not self.is_running:
            self.is_running = True
            self.last_message_time = time.time()
            self.proactive_message_count = 0
            try:
                self.last_known_message_count = len(
                    self.wingman.conversation.history()
                )
            except AttributeError:
                self.last_known_message_count = 0
            await self._set_new_silence_target()
            self.log.info("Proactive Comments: STARTED monitoring.")
            return True
        self.log.info("Proactive Comments: already running.")
        return False

    async def _stop_monitoring(self) -> bool:
        """Deactivate monitoring. Returns True if was running."""
        if self.is_running:
            self.is_running = False
            self.log.info("Proactive Comments: STOPPED monitoring.")
            return True
        return False

    async def _set_new_silence_target(self) -> None:
        """Pick a new random silence wait time between min and max."""
        try:
            min_wait = max(1, self.min_silence_threshold_seconds)
            max_wait = max(min_wait, self.max_silence_threshold_seconds)
            self.current_silence_target = random.randint(min_wait, max_wait)
            if self.settings.debug_mode:
                self.log.info(
                    f"Proactive Comments: new silence target {self.current_silence_target}s "
                    f"(min={min_wait}, max={max_wait})"
                )
        except Exception as e:
            self.current_silence_target = self.min_silence_threshold_seconds
            self.log.warning(
                f"Proactive Comments: error setting silence target ({e}), "
                f"falling back to min={self.current_silence_target}s"
            )
            
    # Core monitoring loop
    async def _monitor_silence_and_comments(self) -> None:
        """Background task: watch for silence, then fire a proactive comment."""
        while True:
            try:
                if not self.is_running:
                    await asyncio.sleep(1)
                    continue

                now = time.time()
                new_message_detected = False

                # ---- Detect new messages in conversation history ---- #
                try:
                    messages = self.wingman.conversation.history()
                    current_count = len(messages)

                    if current_count > self.last_known_message_count:
                        new_message_detected = True
                        num_new = current_count - self.last_known_message_count
                        new_msgs = messages[-num_new:]

                        user_found = any(
                            (
                                msg.get("role") == "user"
                                if isinstance(msg, dict)
                                else getattr(msg, "role", None) == "user"
                            )
                            for msg in new_msgs
                        )

                        self.last_message_time = time.time()
                        await self._set_new_silence_target()

                        if user_found and self.proactive_message_count != 0:
                            if self.settings.debug_mode:
                                self.log.info(
                                    "Proactive Comments: user message detected — resetting count."
                                )
                            self.proactive_message_count = 0

                        self.last_known_message_count = current_count

                except AttributeError:
                    pass
                except Exception as msg_err:
                    self.log.warning(
                        f"Proactive Comments: error checking message history: {msg_err}"
                    )

                time_since_last = now - self.last_message_time

                if self.settings.debug_mode:
                    self.log.info(
                        f"Proactive Comments loop: silence={time_since_last:.1f}s / "
                        f"target={self.current_silence_target:.1f}s, "
                        f"count={self.proactive_message_count}/{self.max_proactive_messages}, "
                        f"newMsg={new_message_detected}"
                    )

                # Fire if silence threshold reached
                if (
                    time_since_last >= self.current_silence_target
                    and self.proactive_message_count < self.max_proactive_messages
                    and not new_message_detected
                ):
                    screenshot_base64: Optional[str] = None
                    if self.vision_enabled:
                        screenshot_base64 = await self._capture_screen()

                    await self._generate_proactive_comment(screenshot_base64)

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"Proactive Comments: error in monitoring loop: {e}")
                await asyncio.sleep(30)

    # Optional screenshot capture                                                 #
    async def _capture_screen(self) -> Optional[str]:
        """Capture the configured display and return a base64 JPEG string, or None."""
        display = self._get_display()
        try:
            image = await self.wingman.screen.capture(display)
        except RuntimeError as e:
            self.log.warning(f"Proactive Comments: could not capture screen: {e}")
            return None
        except Exception as e:
            self.log.warning(f"Proactive Comments: unexpected capture error: {e}")
            return None

        jpeg_base64 = await asyncio.to_thread(vision_base64, image)
        return jpeg_base64

    # Comment generation
    async def _generate_proactive_comment(
        self, screenshot_base64: Optional[str]
    ) -> None:
        """Generate and speak a proactive comment, optionally with a screenshot."""
        try:
            # Gather conversation history
            history: list = []
            try:
                history = self.wingman.conversation.history()[-10:]
            except AttributeError:
                pass
            except Exception as hist_err:
                self.log.warning(
                    f"Proactive Comments: error getting conversation history: {hist_err}"
                )
                return

            # Enforce narrator-mode gate
            if not history and not self.allow_comments_without_history:
                if self.settings.debug_mode:
                    self.log.info(
                        "Proactive Comments: no history and narrator mode OFF — skipping."
                    )
                return

            if not history:
                history_text = "(No previous conversation history)"
                if self.settings.debug_mode:
                    self.log.info(
                        "Proactive Comments: no history — proceeding (narrator mode ON)."
                    )
            else:
                history_text = "\n".join(
                    f"{getattr(msg, 'role', 'unknown')}: {getattr(msg, 'content', '')}"
                    for msg in history
                    if isinstance(getattr(msg, "content", None), str)
                )

            system_prompt = self.custom_system_prompt or ""

            task_description = (
                f"## Proactive Comment Context:\n"
                f"This will be proactive comment number {self.proactive_message_count + 1} "
                f"(out of {self.max_proactive_messages}) since the last user interaction.\n\n"
                f"## Your Task:\n"
                f"Based on the context (history or lack thereof, comment number, and the "
                f"potentially relevant screenshot below if provided), please provide a short, "
                f"natural comment to break the silence, following the system prompt instructions."
            )

            user_text = f"## Recent Conversation History:\n{history_text}\n\n{task_description}"

            use_screenshot = self.vision_enabled and screenshot_base64

            if use_screenshot:
                user_text += " Here is a screenshot of what the user is currently seeing:"

            # Build prompt and image data-URL for the main model
            image_url: Optional[str] = None
            if use_screenshot:
                image_url = f"data:image/jpeg;base64,{screenshot_base64}"

            if self.settings.debug_mode:
                self.log.info("Proactive Comments: generating proactive comment…")

            comment_text = await self.wingman.ai.generate(
                user_text,
                system=system_prompt,
                image=image_url,
            )

            if not comment_text or len(comment_text.strip()) < 5:
                self.log.warning(
                    "Proactive Comments: LLM returned an empty or too-short response."
                )
                return

            comment_text = comment_text.strip()

            # Speak the comment
            self.wingman.run_in_thread(self.wingman.tts.speak, comment_text)

            # Print to the UI
            await self.printr.print_async(
                comment_text,
                color=LogType.INFO,
                source=LogSource.WINGMAN,
                source_name=self.wingman.name,
                skill_name=self.name,
            )

            # Optionally add to conversation history
            if self.add_comments_to_history:
                try:
                    await self.wingman.conversation.add_assistant(comment_text)
                except AttributeError:
                    self.log.warning(
                        "Proactive Comments: wingman does not support conversation.add_assistant."
                    )
                except Exception as add_err:
                    self.log.warning(
                        f"Proactive Comments: error adding comment to history: {add_err}"
                    )

            self.proactive_message_count += 1
            self.last_message_time = time.time()
            await self._set_new_silence_target()

        except Exception as e:
            self.log.error(f"Proactive Comments: error generating comment: {e}")


    # Tools
    @tool(
        name="proactive_comment_status",
        description=(
            "Check the status of the Proactive Comments skill "
            "(running/stopped, silence timer, message count)."
        ),
        summarize=False,
    )
    async def proactive_comment_status(self) -> str:
        """Check the status of the Proactive Comments skill."""
        now = time.time()
        time_since_last = (now - self.last_message_time) if self.is_running else -1
        status_text = "ACTIVE (Monitoring)" if self.is_running else "INACTIVE (Stopped)"
        target_info = (
            f" Target silence: {self.current_silence_target:.1f}s"
            if self.is_running
            else ""
        )
        silence_str = f"{time_since_last:.1f}s" if time_since_last >= 0 else "N/A"
        return (
            f"Proactive Comments Status: {status_text}. "
            f"Silence since last message: {silence_str}.{target_info} "
            f"Proactive Count: {self.proactive_message_count}/{self.max_proactive_messages}."
        )

    @tool(
        name="force_proactive_comment",
        description="Force the Proactive Comments skill to make a comment immediately (if running).",
        wait_response=True,
    )
    async def force_proactive_comment(self) -> str:
        """Force the Proactive Comments skill to make a comment right now."""
        if not self.is_running:
            return "Proactive Comments skill is not running. Cannot force a comment."

        self.log.info("Proactive Comments: force comment requested.")
        screenshot_base64: Optional[str] = None
        if self.vision_enabled:
            screenshot_base64 = await self._capture_screen()

        await self._generate_proactive_comment(screenshot_base64)
        return "Attempting to generate a proactive comment. Listen for audio output or check the chat."

    @tool(
        name="turn_on_proactive_comments",
        description="Turn on the Proactive Comments skill to allow proactive comments.",
    )
    async def turn_on_proactive_comments(self) -> str:
        """Turn on the Proactive Comments skill."""
        started = await self._start_monitoring()
        return (
            "Proactive Comments are now enabled."
            if started
            else "Proactive Comments were already enabled."
        )

    @tool(
        name="turn_off_proactive_comments",
        description="Turn off the Proactive Comments skill to prevent proactive comments.",
    )
    async def turn_off_proactive_comments(self) -> str:
        """Turn off the Proactive Comments skill."""
        stopped = await self._stop_monitoring()
        return (
            "Proactive Comments are now disabled."
            if stopped
            else "Proactive Comments were already disabled."
        )

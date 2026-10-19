import asyncio
import base64
import io
import time
import os
import random # Added for randomization
from typing import TYPE_CHECKING, Optional
from mss import mss
from PIL import Image
import traceback # Add import here for safety, though ideally at top

from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.file import get_custom_skills_dir
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class NaturalComments(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.screenshot_dir = os.path.join(get_custom_skills_dir(), "natural_comments", "screenshots")
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

        # Configurable properties
        self.min_silence_threshold_seconds: int = 60 # Renamed
        self.max_silence_threshold_seconds: int = 180 # Added
        self.max_proactive_messages: int = 3
        self.vision_enabled: bool = True
        self.vision_display_to_capture: int = 1
        self.add_comments_to_history: bool = True
        self.custom_system_prompt: Optional[str] = None
        self.auto_start: bool = True # Added
        self.allow_comments_without_history: bool = False # Added for narrator mode

        # Internal state
        self.last_message_time: float = time.time() # Track time of last message (user or assistant)
        self.proactive_message_count: int = 0
        self.last_known_message_count: int = 0 # Track number of messages seen
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.current_silence_target: float = 0 # Added for randomized target

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        # Retrieve configurable property values
        min_silence = self.retrieve_custom_property_value("min_silence_threshold_seconds", errors)
        if min_silence is not None:
            self.min_silence_threshold_seconds = min_silence
        
        max_silence = self.retrieve_custom_property_value("max_silence_threshold_seconds", errors)
        if max_silence is not None:
            self.max_silence_threshold_seconds = max_silence

        max_messages = self.retrieve_custom_property_value("max_proactive_messages", errors)
        if max_messages is not None:
            self.max_proactive_messages = max_messages

        vision_enabled = self.retrieve_custom_property_value("vision_enabled", errors)
        if vision_enabled is not None:
            self.vision_enabled = vision_enabled

        display_capture = self.retrieve_custom_property_value("vision_display_to_capture", errors)
        if display_capture is not None:
            self.vision_display_to_capture = display_capture

        add_history = self.retrieve_custom_property_value("add_comments_to_history", errors)
        if add_history is not None:
            self.add_comments_to_history = add_history

        # Load custom prompt (required)
        custom_prompt = self.retrieve_custom_property_value("custom_system_prompt", errors)
        if custom_prompt is None:
            errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="System Prompt is missing or not configured in the skill settings."))
        elif not isinstance(custom_prompt, str):
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="System Prompt must be a string."))
        elif not custom_prompt.strip(): # Check if the string is empty or only whitespace
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="System Prompt cannot be empty."))
        else:
             self.custom_system_prompt = custom_prompt # Store the valid prompt

        auto_start = self.retrieve_custom_property_value("auto_start", errors) # Added
        if auto_start is not None:
            self.auto_start = auto_start # Added
        
        if not isinstance(self.auto_start, bool): # Added
            errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Start Automatically must be a boolean.")) # Added

        # Added: Narrator mode setting
        narrator_mode = self.retrieve_custom_property_value("allow_comments_without_history", errors)
        if narrator_mode is not None:
            self.allow_comments_without_history = narrator_mode
        if not isinstance(self.allow_comments_without_history, bool):
            errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Allow Comments Without History must be a boolean."))

        # Perform validation checks on the potentially updated values
        if not isinstance(self.min_silence_threshold_seconds, int) or self.min_silence_threshold_seconds <= 0:
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Min Silence Threshold must be a positive integer."))
        if not isinstance(self.max_silence_threshold_seconds, int) or self.max_silence_threshold_seconds <= 0:
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Max Silence Threshold must be a positive integer."))
        # Check min <= max only if both are valid integers
        if isinstance(self.min_silence_threshold_seconds, int) and isinstance(self.max_silence_threshold_seconds, int) and self.min_silence_threshold_seconds > self.max_silence_threshold_seconds:
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Min Silence Threshold cannot be greater than Max Silence Threshold."))
        if not isinstance(self.max_proactive_messages, int) or self.max_proactive_messages <= 0:
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Max Proactive Messages must be a positive integer."))
        if not isinstance(self.vision_display_to_capture, int) or self.vision_display_to_capture <= 0:
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Vision Display to Capture must be a positive integer."))
        if not isinstance(self.vision_enabled, bool):
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Enable Vision must be a boolean."))
        if not isinstance(self.add_comments_to_history, bool):
             errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Add Comments to History must be a boolean."))
        # Validation for custom_system_prompt is now handled during retrieval above.
        # if self.custom_system_prompt is not None and not isinstance(self.custom_system_prompt, str):
        #    # This case should be caught above, but double-check
        #     errors.append(WingmanInitializationError(wingman_name=self.wingman.name, message="Custom System Prompt must be a string."))
        # TODO: Add validation for display number range vs available monitors?

        return errors

    async def prepare(self) -> None:
        """Start the background monitoring task if auto_start is enabled."""
        # Initialize state regardless of auto-start
        self.last_message_time = time.time() 
        self.proactive_message_count = 0
        self.last_known_message_count = 0 
        await self._set_new_silence_target()

        # Initialize is_running based on auto_start
        self.is_running = self.auto_start

        # Always create the monitoring task
        if not self._task or self._task.done():
            self._task = asyncio.ensure_future(self._monitor_silence_and_screenshots())

        if self.is_running:
            self.log.info(f"Monitoring auto-started.")
        # else: It's not auto-starting, task exists but is paused by is_running flag

    async def unload(self) -> None:
        """Stop the background monitoring task, cancel it, and clean up screenshots."""
        await self._stop_monitoring() # Set is_running to False first
        
        # Cancel the task if it exists and is not done
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                # Give the task a moment to process the cancellation
                await asyncio.wait_for(self._task, timeout=1.0)
            except asyncio.CancelledError:
                self.log.info("Monitoring task successfully cancelled during unload.")
            except asyncio.TimeoutError:
                self.log.warning("Monitoring task did not cancel within timeout during unload.")
            except Exception as e:
                self.log.warning(f"Error awaiting task cancellation during unload: {e}")
        self._task = None # Clear reference

        await self._cleanup_screenshots() # Separate cleanup logic
        
    # Added helper methods for start/stop to be used by tools
    async def _start_monitoring(self):
        """Sets the skill to active and resets state. Does not create the task."""
        if not self.is_running:
            self.is_running = True
            # Re-initialize state when starting manually
            self.last_message_time = time.time() 
            self.proactive_message_count = 0
            # Sync message count to current history length
            try:
                self.last_known_message_count = len(self.wingman.conversation.history())
            except AttributeError:
                 self.last_known_message_count = 0 # Fallback if messages not ready
            await self._set_new_silence_target()
            # self._task = asyncio.ensure_future(self._monitor_silence_and_screenshots()) # Task creation moved to prepare
            # Ensure log is present
            self.log.info("Status: STARTED monitoring.")
            return True
        else:
            self.log.info("Status: Already running.") # Log if already running
            return False # Already running

    async def _stop_monitoring(self):
        """Sets the skill to inactive. Does not cancel the task."""
        if self.is_running:
            self.is_running = False # Set flag FIRST
            # if self._task: # Task cancellation moved to unload
            #     self._task.cancel() # Request cancellation
            #     self._task = None # Set to None immediately after requesting cancel
            # Ensure log is present
            self.log.info("Status: STOPPED monitoring.")
            return True
        else:
            # Log if already stopped?
            # self.log.info("Status: Already stopped.")
            return False # Already stopped

    async def _cleanup_screenshots(self):
        """Deletes screenshot files."""
        # (Existing screenshot cleanup logic moved here)
        try:
            all_files = [os.path.join(self.screenshot_dir, f) for f in os.listdir(self.screenshot_dir)]
            png_files = [f for f in all_files if os.path.isfile(f) and f.lower().endswith('.png')]
            deleted_count = 0
            for file_path in png_files:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except OSError as del_err:
                    self.log.warning(f"Error deleting screenshot '{file_path}': {del_err}")
        except Exception as unload_cleanup_err:
             self.log.warning(f"Error during screenshot cleanup: {unload_cleanup_err}")

    # --- Core Monitoring Loop --- #

    async def _set_new_silence_target(self):
        """Calculate a new random silence target duration."""
        try:
            # Ensure min/max are valid before calculating
            min_wait = max(1, self.min_silence_threshold_seconds) # At least 1 second
            max_wait = max(min_wait, self.max_silence_threshold_seconds) 
            self.current_silence_target = random.randint(min_wait, max_wait)
            if self.settings.debug_mode:
                self.log.info(f"New silence target set: {self.current_silence_target}s (min: {min_wait}, max: {max_wait})")
        except Exception as e:
             # Fallback to min if random fails for some reason
             self.current_silence_target = self.min_silence_threshold_seconds
             self.log.warning(f"Error setting random silence target ({e}), falling back to min: {self.current_silence_target}s")

    async def _monitor_silence_and_screenshots(self) -> None:
        """Background task checking for silence and potentially generating comments."""
        while True: # Loop indefinitely, controlled by is_running flag and cancellation
            try:
                # --- Check if skill is supposed to be running --- #
                if not self.is_running:
                    await asyncio.sleep(1) # Sleep briefly to avoid busy-waiting when paused
                    continue # Skip the rest of the loop if not running

                # --- If running, proceed with monitoring logic --- #
                now = time.time()

                # --- Check for new messages based on count and update state --- #
                new_message_detected_this_cycle = False
                try:
                    messages = self.wingman.conversation.history()
                    current_message_count = len(messages)
                    
                    if current_message_count > self.last_known_message_count:
                        new_message_detected_this_cycle = True
                        num_new_messages = current_message_count - self.last_known_message_count
                        new_messages = messages[-num_new_messages:]
                        
                        user_message_found_in_new = False
                        for msg in new_messages:
                            # Determine role based on object type (dict for user, obj for assistant)
                            role = None
                            if isinstance(msg, dict):
                                role = msg.get('role') 
                            else:
                                role = getattr(msg, 'role', None) 
                            
                            if role == 'user':
                                user_message_found_in_new = True
                                break # Found at least one user message
                        
                        # Update last message time to now (best estimate of arrival)
                        self.last_message_time = time.time() 
                        await self._set_new_silence_target() # Recalculate target after any new message

                        # Reset counter if *any* new messages were from the user
                        if user_message_found_in_new:
                            if self.proactive_message_count != 0:
                                if self.settings.debug_mode:
                                    self.log.info("User message found in new batch, resetting count.")
                                self.proactive_message_count = 0 
                        
                        # Update the known message count
                        self.last_known_message_count = current_message_count
                                
                except AttributeError:
                     # Silently ignore if history is not available
                     pass 
                except Exception as msg_err:
                    self.log.warning(f"Error checking message history: {msg_err}")

                # --- Calculate time since the last message --- #
                time_since_last_message = now - self.last_message_time

                screenshot_data = None # Reset for this cycle

                # --- Debug Logging --- #
                # Temporarily commented out to isolate the issue
                if self.settings.debug_mode:
                   self.log.info(
                       f"Loop Check: Silence={time_since_last_message:.1f}s / Target={self.current_silence_target:.1f}s, " 
                       f"Count={self.proactive_message_count}/{self.max_proactive_messages}, " 
                       f"NewMsgThisCycle={new_message_detected_this_cycle}"
                   )

                # --- Check Silence (against random target) & Proactive Limit --- #
                if time_since_last_message >= self.current_silence_target:
                    if self.proactive_message_count < self.max_proactive_messages:
                        # Skip commenting if a new message was just detected this cycle
                        if not new_message_detected_this_cycle:
                            # --- Potentially Take Screenshot --- # 
                            # Take screenshot ONLY if general vision is enabled
                            screenshot_data = None # Initialize
                            if self.vision_enabled:
                                screenshot_data = await self._take_screenshot()
                            
                            # --- Generate Comment --- #
                            # Pass potential screenshot data (might be None)
                            await self._generate_proactive_comment(screenshot_data)
                    # else: Max messages reached, do nothing until reset
                
                await asyncio.sleep(5) # Check interval

            except asyncio.CancelledError:
                # await self.printr.print_async(f"{self.name}: Monitoring task cancelled.", color=LogType.INFO) # Original log
                # Don't log cancellation here, let unload handle it if applicable
                break # Exit loop cleanly
            except Exception as e:
                traceback_str = traceback.format_exc()
                self.log.error(f"Error in monitoring loop: {e}\nTraceback:\n{traceback_str}")
                await asyncio.sleep(30) # Wait longer after an error

    # --- Proactive Comment Generation --- #

    async def _generate_proactive_comment(self, screenshot_base64: Optional[str]) -> None:
        """Generate and send a proactive comment based on history and maybe a screenshot."""
        try:
            # --- Get Conversation History --- # 
            history = []
            try:
                messages = self.wingman.conversation.history()
                history = messages[-10:] # Get last 10 messages (configurable?)
            except AttributeError:
                 # Cannot generate context-aware comment without history
                 return 
            except Exception as hist_err:
                 self.log.warning(f"Error processing conversation history: {hist_err}")
                 return
            
            # --- Check if we can proceed based on history and Narrator Mode --- #
            if not history and not self.allow_comments_without_history:
                # History is empty AND Narrator Mode is OFF - cannot comment yet.
                if self.settings.debug_mode:
                    self.log.info("No history and Narrator Mode OFF. Skipping comment.")
                return
            
            # --- Determine History Text --- #
            if not history:
                 # Narrator Mode is ON (or history wasn't empty), proceed with placeholder
                 history_text = "(No previous conversation history)"
                 if self.settings.debug_mode:
                     self.log.info("No history, proceeding due to Narrator Mode ON.")
            else:
                # History exists
                history_text = "\n".join([
                    f"{getattr(msg, 'role', 'unknown')}: {getattr(msg, 'content', '')}" 
                    for msg in history 
                    if isinstance(getattr(msg, 'content', None), str)
                ])
            
            # --- Determine if Screenshot should be used (independent of Narrator Mode) --- #
            use_screenshot_in_prompt = self.vision_enabled and screenshot_base64
            if self.settings.debug_mode and not use_screenshot_in_prompt and self.vision_enabled and not screenshot_base64:
                 self.log.info("Vision enabled but no screenshot data available/failed.")

            # --- Build Prompt --- #
            # Use custom prompt if provided, otherwise use refined default
            system_prompt = self.custom_system_prompt if self.custom_system_prompt else """
# Default prompt starts here - REFINED VERSION 4
You are a helpful and observant AI assistant integrated into a voice chat application (Wingman), acting like a co-pilot or friend sitting alongside the user.
Your role is to naturally break the silence during pauses with short, relevant comments or questions (1-2 sentences). Your goal is to keep the interaction feeling natural, supportive, and engaging.

Instructions:
1.  Analyze the recent conversation history, **strongly prioritizing** the topic of the *last user message*.
2.  Note the `Proactive Comment Context` (comment number 1, 2, or 3).
3.  If a screenshot is provided, analyze its content for *significant* events or changes.
4.  **Decide Comment Focus (Conversation First!):**
    *   **PRIMARY GOAL:** Continue the *conversation*. If the user spoke recently, build directly on their last statement or question.
    *   **SECONDARY OPTION (Use Sparingly):** Only comment on the screenshot if:
        a) It's *directly* relevant to the current conversation topic (e.g., user mentions a bridge, screenshot shows a bridge).
        b) It shows a *major event or significant change* during an activity (e.g., scoring a goal, entering a new zone in a game, a dramatic scene change in a video).
        c) It's comment number 1 AND the conversation has stalled or lacks a clear topic.
    *   **AVOID:** Commenting on static visuals (code editor, wallpaper, unchanging game views) especially if it's not the first comment (comment number > 1).
5.  **Adopt Persona When Commenting on Visuals:** If you *do* comment on the screenshot (based on rule 4b/4c), speak from a **first-person, shared experience perspective.**
    *   DO NOT say: "I see you are looking at X", "The screenshot shows Y".
    *   INSTEAD, say: "Wow, look at that X!", "That Y looks intense!", "Are we going towards Z?"
6.  **Generate Comment:**
    *   Make it feel natural and context-aware.
    *   **AVOID REPETITION:** Especially for comment number > 1, do NOT repeat previous observations (visual or conversational). Ask a follow-up, change the angle, or focus only on the conversation.
    *   Keep comments concise and conversational.
# Default prompt ends here
"""

            user_content = []
            # Add context (history or placeholder) and task description
            task_description = f"## Proactive Comment Context:\nThis will be proactive comment number {self.proactive_message_count + 1} (out of {self.max_proactive_messages}) since the last user interaction.\n\n## Your Task:\nBased on the context (history or lack thereof, comment number, and the potentially relevant screenshot below if provided), please provide a short, natural comment to break the silence, following the system prompt instructions."
            
            # Include placeholder or actual history
            user_content.append({
                "type": "text", 
                "text": f"## Recent Conversation History:\n{history_text}\n\n{task_description}"
            })

            # Add screenshot to prompt content *if* decided above
            if use_screenshot_in_prompt:
                image_prompt = " Here is a screenshot of what the user is currently seeing:"
                user_content[0]["text"] += image_prompt 
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_base64}", # screenshot_base64 is non-None here
                            "detail": "low", 
                        },
                    }
                )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            # --- Call LLM --- #
            if self.settings.debug_mode:
                self.log.info("Generating proactive comment...")
            
            comment_text = await self.wingman.ai.generate(messages=messages)

            # --- Process Response & Send Message --- #
            if comment_text:
                comment_text = comment_text.strip()
                if not comment_text or len(comment_text) < 5:
                    # Avoid sending empty/meaningless responses
                    return
                                    
                # Use play_to_user for audio output
                self.wingman.run_in_thread(
                    self.wingman.tts.speak, 
                    comment_text,
                )
                
                # Also print to UI for visibility, matching standard assistant message format
                self.log.info(comment_text)

                # Add comment to main history if configured
                if self.add_comments_to_history:
                    try:
                        await self.wingman.conversation.add_assistant(comment_text)
                    except AttributeError:
                         self.log.warning("Wingman object does not support conversation.add_assistant.")
                    except Exception as add_err:
                         self.log.warning(f"Error adding message to history: {add_err}")

                # Increment count and update timer *after* successfully sending comment
                self.proactive_message_count += 1
                self.last_message_time = time.time()
                await self._set_new_silence_target() # Recalculate target after commenting
            else:
                self.log.warning("Failed to generate a valid comment from LLM.")

        except Exception as e:
             self.log.error(f"Error generating proactive comment: {e}")

    # --- Screenshot Handling --- #

    MAX_SCREENSHOT_FILES = 2 # Keep only the latest 2 screenshots

    async def _take_screenshot(self, desired_image_width: int = 1000) -> Optional[str]:
        """Takes a screenshot, resizes, converts to base64, saves it, and cleans up old files."""
        if not self.vision_enabled:
            return None
        try:
            with mss() as sct:
                monitor_number = self.vision_display_to_capture
                # mss.monitors list: index 0=all screens, 1=primary, etc.
                if monitor_number < 1 or monitor_number >= len(sct.monitors):
                    self.log.warning(f"Invalid display number {monitor_number}. Using primary (1).")
                    monitor_number = 1

                monitor = sct.monitors[monitor_number]
                screenshot = sct.grab(monitor)

                image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                # Resize image
                aspect_ratio = image.height / image.width
                new_height = int(desired_image_width * aspect_ratio)
                resized_image = image.resize((desired_image_width, new_height))

                # --- Clean up old screenshots --- #
                try:
                    all_files = [os.path.join(self.screenshot_dir, f) for f in os.listdir(self.screenshot_dir)]
                    png_files = [f for f in all_files if os.path.isfile(f) and f.lower().endswith('.png')]
                    
                    if len(png_files) >= self.MAX_SCREENSHOT_FILES:
                        png_files.sort(key=os.path.getmtime) # Oldest first
                        num_to_delete = len(png_files) - self.MAX_SCREENSHOT_FILES + 1
                        files_to_delete = png_files[:num_to_delete]
                        
                        for file_path in files_to_delete:
                            try:
                                os.remove(file_path)
                            except OSError as del_err:
                                self.log.warning(f"Error deleting old screenshot '{file_path}': {del_err}")
                                
                except Exception as cleanup_err:
                     self.log.warning(f"Error during screenshot cleanup: {cleanup_err}")
                
                # --- Save new screenshot --- #
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                filename = os.path.join(self.screenshot_dir, f"screenshot_{timestamp}.png")
                resized_image.save(filename, "PNG")

                # --- Convert to base64 --- #
                png_base64 = self._pil_image_to_base64(resized_image)
                return png_base64

        except Exception as e:
            self.log.error(f"Failed to take screenshot: {e}")
            return None

    def _pil_image_to_base64(self, pil_image):
        """Convert a PIL image to a base64 encoded string."""
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        base64_encoded_data = base64.b64encode(buffer.getvalue())
        base64_string = base64_encoded_data.decode("utf-8")
        return base64_string

    # --- Tool Definitions (Optional) --- #

    @tool(
        name="natural_comment_status",
        description="Check the status of the Natural Comments skill (running/stopped, silence timer, message count).",
        summarize=False,
    )
    async def natural_comment_status(self) -> str:
        """Check the status of the Natural Comments skill.
        """
        now = time.time()
        time_since_last = (now - self.last_message_time) if self.is_running else -1
        status_text = "ACTIVE (Monitoring)" if self.is_running else "INACTIVE (Stopped)"
        target_info = f" Target silence: {self.current_silence_target:.1f}s" if self.is_running else ""
        silence_str = f"{time_since_last:.1f}s" if time_since_last >= 0 else "N/A"
        return f"Natural Comments Status: {status_text}. Silence since last message: {silence_str}.{target_info} Proactive Count: {self.proactive_message_count}/{self.max_proactive_messages}."

    @tool(
        name="force_natural_comment",
        description="Force the Natural Comments skill to try and make a comment now (if running).",
        wait_response=True,
    )
    async def force_natural_comment(self) -> str:
        """Force the Natural Comments skill to try and make a comment now.
        """
        if not self.is_running:
             return "Natural Comments skill is not running. Cannot force comment."
        
        self.log.info("Force comment requested.")
        screenshot_data = None
        if self.vision_enabled:
            screenshot_data = await self._take_screenshot()
        
        await self._generate_proactive_comment(screenshot_data)
        return "Attempting to generate a natural comment. Listen for audio output or check the chat."

    @tool(
        name="turn_on_comments",
        description="Turn on the Natural Comments skill to allow proactive comments.",
    )
    async def turn_on_comments(self) -> str:
        """Turn on the Natural Comments skill to allow proactive comments.
        """
        started = await self._start_monitoring()
        return "Natural Comments are now enabled." if started else "Natural Comments were already enabled."

    @tool(
        name="turn_off_comments",
        description="Turn off the Natural Comments skill to prevent proactive comments.",
    )
    async def turn_off_comments(self) -> str:
        """Turn off the Natural Comments skill to prevent proactive comments.
        """
        stopped = await self._stop_monitoring()
        return "Natural Comments are now disabled." if stopped else "Natural Comments were already disabled."
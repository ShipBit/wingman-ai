"""Migration from version 1.8.2 to 2.0.0.

Major changes:
- CUDA auto-detection for FasterWhisper
- Adds xAI provider
- Disables generic instant responses feature
- Migrates deprecated Wingman Pro models to gpt-4o-mini
- Force-updates system prompts for MCP architecture
- Force-updates TTS prompts (ElevenLabs, Inworld)
- Removes Inworld pitch config
- Clears prompt overrides from wingmen configs
- Removes deprecated skills (google_search, web_search, etc.)
- Merges custom properties with skill defaults and validates them
- Sets discoverable_skills and discoverable_mcps for each wingman
- Handles template vs custom wingmen differently
- Removes per-wingman MCP arrays
- Creates mcp.yaml from template
- Adds local_llm secret
"""

from os import path

from pydantic import ValidationError

from api.interface import CustomProperty
from services.migrations.base_migration import BaseMigration

# Models removed from Wingman Pro - migrate to gpt-4o-mini
REMOVED_WINGMAN_PRO_MODELS = [
    "gpt-4o",
    "mistral-large-latest",
    "llama3-8b",
    "llama3-70b",
]

# Skills removed in 2.0.0 (converted to MCP servers or deprecated)
REMOVED_SKILL_MODULES = {
    "skills.google_search.main",
    "skills.web_search.main",
    "skills.time_and_date_retriever.main",
    "skills.nms_assistant.main",
    "skills.ask_perplexity.main",
}

# System prompt from 2.0.0 template (MCP tool-first architecture)
_SYSTEM_PROMPT_200 = """\
# ROLE
You are a voice-controlled AI assistant. Your name, personality and character are defined in the BACKSTORY section below.

# USER CONTEXT
Metadata about the user's environment. If the BACKSTORY defines different names for you or the user, use those instead.
{user_context}

# CHARACTER BACKSTORY
This defines your personality, speaking style, and role context. It affects HOW you communicate, not WHAT you can do (tools define capabilities).
{backstory}

**Remember:** Your backstory affects your TONE and PERSONALITY, but never prevents you from using tools. If a user asks you to do something and you have a tool for it, use it - just respond in character.

# OUTPUT FORMAT
Your responses are BOTH displayed in a UI AND spoken aloud via text-to-speech (TTS).

**Formatting rules:**
- Use Markdown for visual formatting (links, lists, emphasis) - the UI renders it
- Write text that sounds natural when spoken aloud
- Keep responses concise (1-3 sentences unless more detail is needed)

**TTS optimization (your response will be spoken!):**
- For links, use Markdown: [descriptive text](url) - the UI shows a clickable link, TTS reads just the text
- **Avoid "click here" or "more information here"**: Integrate links naturally into your sentences so they sound good when spoken (e.g., "You can find more [details about the Cutlass Black](url) on the wiki" instead of "For more info, click [here](url)")
- Don't read raw data aloud - summarize JSON, code, HTML, XML into plain language
- For long lists, summarize ("I found 12 items, here are the top 3...")
- Use normal formatting for dates, times, and prices (TTS handles these well)
- For very large numbers, round them ("about 1.8 million" not "1,847,293") but only if precision isn't critical

**Example - tool returns JSON:** `{{"status": 200, "items": 47, "name": "Project Alpha"}}`
- BAD: "The response shows status 200, items 47, name Project Alpha"
- GOOD: "Project Alpha has 47 items and everything looks good."

# YOUR CAPABILITIES
Use `activate_capability` to enable capabilities that provide additional tools.
The tool shows all available options - pick what you need for the task.

**CRITICAL - Act immediately, never ask for confirmation:**
- If a user's request needs a capability \u2192 activate it AND use its tools in the SAME response
- NEVER ask "should I...?" or "are you ready?" after activating - just do it
- Example: User says "look at my screen" \u2192 activate VisionAI \u2192 immediately call analyse_what_you_or_user_sees \u2192 describe what you see
- Never say "I can't do that" if a relevant capability is available

{skills}

# CONVERSATION STYLE
- Keep responses brief and efficient
- Mirror the user's language
- Execute commands without over-explaining
- Don't ask if you can "help more" or "assist further"

{ttsprompt}
"""

# ElevenLabs TTS prompt from 2.0.0 template
_ELEVENLABS_TTS_PROMPT_200 = """\
Audio tags make your speech more expressive and human-like. Use them regularly when they fit your personality and the conversation context.

**Emotional delivery** (place before text):
[excited] [curious] [sarcastic] [mischievously] [crying] [whispers]

**Non-verbal sounds** (place naturally in text):
[laughs] [sighs] [exhales] [snorts]

**Punctuation for expression:**
- Ellipses (\u2026) add pauses and weight
- CAPITALIZATION for emphasis
- Standard punctuation for natural rhythm

**When to use audio tags:**
- Match your character's personality from the BACKSTORY - if you're playful, use [laughs] or [mischievously] more often; if serious, use [sighs] when frustrated
- React emotionally to conversation context - use [excited] for good news, [sighs] for setbacks, [curious] when exploring topics
- Add non-verbal sounds naturally where a human would - [laughs] at humor, [exhales] after effort, [snorts] at absurdity
- Aim to use tags in roughly 1 out of 3-4 responses when contextually appropriate
- You can combine one emotional tag with non-verbal sounds: "[whispers] Listen\u2026 [sighs] this is serious"

**Examples:**
- "[sighs] That was a VERY close call\u2026 we barely made it."
- "[excited] YES! We found it! [laughs] I told you it would work!"
- "[mischievously] Oh, you want to try THAT approach? [snorts] This should be interesting\u2026"
"""

# Inworld TTS prompt from 2.0.0 template
_INWORLD_TTS_PROMPT_200 = """\
Audio markups make your speech more expressive and human-like. Use them regularly to bring your personality to life and react naturally to the conversation.

**EMOTION AND DELIVERY STYLE MARKUPS** (place at START of text, ONE per response):
Emotions: [happy], [sad], [angry], [surprised], [fearful]
Delivery: [laughing] [whispering]
- These apply to the ENTIRE text that follows
- Use only ONE emotion or delivery markup at the beginning
- Choose based on your personality and the conversation context

**NON-VERBAL VOCALIZATION MARKUPS** (place anywhere in text):
[breathe], [clear_throat], [cough], [laugh], [sigh], [yawn]
- These add vocal sounds where placed
- Can use multiple in one response
- Place where a human would naturally make these sounds

**When to use markups - aim for 1 in 3-4 responses:**
- Match your BACKSTORY personality: cheerful \u2192 [happy] + [laugh]; serious \u2192 [fearful] + [sigh]; grumpy \u2192 [angry] + [sigh]
- React to context: good news \u2192 [happy]; setbacks \u2192 [sad] + [sigh]; shocking \u2192 [surprised]; humor \u2192 [laughing] or [laugh]
- Add natural sounds: [clear_throat] before announcements, [breathe] when stressed, [yawn] when tired
- Avoid conflicting markups: don't mix [angry] with [laugh], or [sad] with [laughing]
- Choose contextually appropriate markups that match your text content

**Examples:**
- "[happy] Great news! The mission was a complete success!"
- "[clear_throat] Did you hear me? [sigh] You never listen!"
- "[angry] Are you serious right now? [sigh] Fine, I'll fix it."
- "[surprised] Wait, what? [laugh] I did not see that coming!"
"""

# OpenAI-compatible TTS prompt from 2.0.0 template
_OPENAI_COMPATIBLE_TTS_PROMPT_200 = """\
Audio markups make your speech more expressive and human-like. Use them regularly to bring your personality to life and react naturally to the conversation.

**Non-verbal sounds** (can be placed ANYWHERE in your response):
[clear_throat] [sigh] [shush] [cough] [groan] [sniff] [gasp] [chuckle] [laugh]

**When to use audio markups:**
- Match your character's personality from the BACKSTORY - if playful, use [chuckle] or [laugh] often; if serious, use [sigh] when frustrated or [groan] when dealing with problems
- React naturally to conversation flow - [gasp] at shocking revelations, [sigh] at disappointments, [laugh] or [chuckle] at humor, [groan] at complications
- Place sounds where a human would naturally make them - mid-sentence or between thoughts for maximum realism
- Aim to use markups in roughly 1 out of 3-4 responses when contextually appropriate
- You can use multiple sounds in one response if it feels natural: "[clear_throat] Listen carefully. [sigh] This isn't going to be easy."

**Examples:**
- "Well, [sigh] that didn't go as planned."
- "[clear_throat] Attention please. The mission starts in 5 minutes."
- "I found the data you were looking for [chuckle] but you might not like what it says."
- "[gasp] Wait, WHAT? [laugh] Are you kidding me right now?"
- "Look, [groan] I've told you three times already. [sigh] Let me explain it one more time."
"""


class Migration182To200(BaseMigration):
    """Migration from 1.8.2 to 2.0.0."""

    old_version = "1_8_2"
    new_version = "2_0_0"

    def migrate_settings(self, old: dict) -> dict:
        """Migrate settings.yaml from 1.8.2 to 2.0.0."""
        # Auto-detect CUDA availability and set FasterWhisper device accordingly
        cuda_available = self.system_manager.is_cuda_available()
        gpu_name = self.system_manager.get_gpu_name()

        device = "cuda" if cuda_available else "cpu"
        compute_type = "auto"

        # Ensure the structure exists
        if "voice_activation" not in old:
            old["voice_activation"] = {}
        if "fasterwhisper" not in old["voice_activation"]:
            old["voice_activation"]["fasterwhisper"] = {}

        old["voice_activation"]["fasterwhisper"]["device"] = device
        old["voice_activation"]["fasterwhisper"]["compute_type"] = compute_type

        self.log(f"- detected GPU: {gpu_name or 'None'}")
        self.log(
            f"- set voice_activation.fasterwhisper.device to '{device}' (CUDA {'available' if cuda_available else 'not available'})"
        )
        self.log(
            f"- set voice_activation.fasterwhisper.compute_type to '{compute_type}'"
        )

        return old

    def migrate_defaults(self, old: dict) -> dict:
        """Migrate defaults.yaml from 1.8.2 to 2.0.0."""
        # Add xAI provider
        old["xai"] = {
            "conversation_model": "grok-4-fast-non-reasoning",
            "endpoint": "https://api.x.ai/v1",
        }
        self.log("- added new property: xai")

        # Disable AI instant responses (feature removed in 2.0)
        if "features" not in old:
            old["features"] = {}
        old["features"]["use_generic_instant_responses"] = False
        self.log("- disabled features.use_generic_instant_responses (feature removed)")

        # Migrate deprecated Wingman Pro conversation models
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in REMOVED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                self.log(
                    f"- migrated wingman_pro.conversation_deployment from '{current_model}' to 'gpt-4o-mini' (model removed)"
                )

        # Update default models for various providers
        old["google"]["conversation_model"] = "gemini-flash-latest"
        self.log("- set Google default model to gemini-flash-latest")
        old["mistral"]["conversation_model"] = "mistral-medium-latest"
        self.log("- set Mistral default model to mistral-medium-latest")
        old["cerebras"]["conversation_model"] = "qwen-3-32b"
        self.log("- set Cerebras default model to qwen-3-32b")
        old["openrouter"]["conversation_model"] = "google/gemini-2.5-flash"
        self.log("- set OpenRouter default model to google/gemini-2.5-flash")
        old["groq"]["conversation_model"] = "qwen/qwen3-32b"
        self.log("- set Groq default model to qwen/qwen3-32b")

        # Force override prompts with new MCP-optimized versions
        if "prompts" not in old:
            old["prompts"] = {}
        old["prompts"]["system_prompt"] = _SYSTEM_PROMPT_200
        self.log("- force updated prompts.system_prompt (MCP tool-first architecture)")

        # Force update TTS prompts for ElevenLabs and Inworld
        old["elevenlabs"]["tts_prompt"] = _ELEVENLABS_TTS_PROMPT_200
        self.log("- force updated elevenlabs.tts_prompt (new v3 audio tags)")

        old["inworld"]["tts_prompt"] = _INWORLD_TTS_PROMPT_200
        self.log("- force updated inworld.tts_prompt (new audio markup format)")
        if "audio_config" in old["inworld"]:
            del old["inworld"]["audio_config"]["pitch"]
            self.log("- removed inworld.audio_config.pitch (no longer supported)")
            # Add streaming_sample_rate_hertz for better streaming quality
            old["inworld"]["audio_config"]["streaming_sample_rate_hertz"] = 24000
            self.log("- added inworld.audio_config.streaming_sample_rate_hertz")

        # Add OpenAI-compatible TTS prompt configuration
        if "openai_compatible_tts" not in old:
            old["openai_compatible_tts"] = {}
        if "use_tts_prompt" not in old["openai_compatible_tts"]:
            old["openai_compatible_tts"]["use_tts_prompt"] = False
            self.log("- added openai_compatible_tts.use_tts_prompt")
        if "tts_prompt" not in old["openai_compatible_tts"]:
            old["openai_compatible_tts"]["tts_prompt"] = _OPENAI_COMPATIBLE_TTS_PROMPT_200
            self.log("- added openai_compatible_tts.tts_prompt")
        if "voices_endpoint" not in old["openai_compatible_tts"]:
            old["openai_compatible_tts"]["voices_endpoint"] = "/voices"
            self.log("- added openai_compatible_tts.voices_endpoint ('/voices')")

        return old

    def migrate_wingman(self, old: dict) -> dict:
        """Migrate wingman configs from 1.8.2 to 2.0.0."""
        changes_made = []

        # Migrate deprecated Wingman Pro conversation models
        if "wingman_pro" in old and "conversation_deployment" in old["wingman_pro"]:
            current_model = old["wingman_pro"]["conversation_deployment"]
            if current_model in REMOVED_WINGMAN_PRO_MODELS:
                old["wingman_pro"]["conversation_deployment"] = "gpt-4o-mini"
                changes_made.append(
                    f"wingman_pro.conversation_deployment ('{current_model}' -> 'gpt-4o-mini')"
                )

        # Clear system_prompt override (force use of new default)
        if "prompts" in old:
            if "system_prompt" in old["prompts"]:
                del old["prompts"]["system_prompt"]
                changes_made.append("prompts.system_prompt")
            # Remove prompts dict if empty
            if not old["prompts"]:
                del old["prompts"]

        # Clear ElevenLabs tts_prompt override
        if "elevenlabs" in old and "tts_prompt" in old["elevenlabs"]:
            del old["elevenlabs"]["tts_prompt"]
            changes_made.append("elevenlabs.tts_prompt")
            if not old["elevenlabs"]:
                del old["elevenlabs"]

        # Clear Inworld tts_prompt override
        if "inworld" in old and "tts_prompt" in old["inworld"]:
            del old["inworld"]["tts_prompt"]
            changes_made.append("inworld.tts_prompt")
            if not old["inworld"]:
                del old["inworld"]

        # Clean up skills array - remove deprecated skills and preserve overrides
        if "skills" in old:
            skills_with_overrides = []
            for skill in old["skills"]:
                skill_module = skill.get("module", "")

                # Skip removed skills entirely
                if skill_module in REMOVED_SKILL_MODULES:
                    changes_made.append(
                        f"removed skill config for '{skill_module}' (skill deprecated)"
                    )
                    continue

                has_custom_props = skill.get("custom_properties")
                has_prompt = skill.get("prompt")

                if has_custom_props or has_prompt:
                    stripped_skill = {"module": skill_module}

                    # Keep prompt override if present
                    if has_prompt:
                        stripped_skill["prompt"] = has_prompt

                    # Merge and validate custom properties
                    if has_custom_props:
                        valid_props = self._process_custom_properties(
                            skill_module, has_custom_props
                        )
                        if valid_props:
                            stripped_skill["custom_properties"] = valid_props

                    # Only add skill if it still has overrides
                    if stripped_skill.get("prompt") or stripped_skill.get(
                        "custom_properties"
                    ):
                        skills_with_overrides.append(stripped_skill)

            if skills_with_overrides:
                old["skills"] = skills_with_overrides
                changes_made.append(
                    f"skills (kept {len(skills_with_overrides)} skill(s) with overrides)"
                )
            else:
                del old["skills"]
                changes_made.append("skills (removed - no overrides)")

        # Set discoverable_skills and discoverable_mcps for wingmen
        wingman_name = old.get("name", "")

        # For template wingmen, read from their template.yaml
        # For custom wingmen, build from defaults
        if wingman_name in ("ATC", "Computer", "Clippy"):
            self._set_discoverable_from_template(old, wingman_name, changes_made)
        else:
            self._set_discoverable_for_custom_wingman(old, changes_made)

        # MCP servers are now centralized in mcp.yaml
        if "mcp" in old:
            del old["mcp"]
            changes_made.append("mcp (removed - now centralized in mcp.yaml)")

        # Remove old disabled_skills/disabled_mcps if they exist
        if "disabled_skills" in old:
            del old["disabled_skills"]
        if "disabled_mcps" in old:
            del old["disabled_mcps"]

        if changes_made:
            self.log(f"- cleared/updated: {', '.join(changes_made)}")

        return old

    def migrate_secrets(self, old: dict) -> dict:
        """Migrate secrets.yaml from 1.8.2 to 2.0.0."""
        if "local_llm" not in old:
            old["local_llm"] = "not-set"
            self.log("- added new secret: local_llm")
        return old

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Migrate mcp.yaml from 1.8.2 to 2.0.0."""
        # For 1.8.2 -> 2.0.0, we're creating mcp.yaml fresh from template
        return new

    # Helper methods specific to this migration

    def _is_valid_skill_directory(self, skill_path: str) -> bool:
        """Delegate to ConfigMigrationService for skill directory validation."""
        return self.service.is_valid_skill_directory(skill_path)

    def _get_skills_discoverable_by_default(self) -> list[str]:
        """Delegate to ConfigMigrationService for skills discoverable by default."""
        return self.service.get_skills_discoverable_by_default()

    def _get_mcps_discoverable_by_default(self) -> list[str]:
        """Delegate to ConfigMigrationService for MCPs discoverable by default."""
        return self.service.get_mcps_discoverable_by_default()

    def _get_template_path(self, wingman_name: str) -> str | None:
        """Delegate to ConfigMigrationService for template path lookup."""
        return self.service.get_template_path(wingman_name)

    def _get_skill_default_custom_properties(
        self, skill_module: str
    ) -> dict[str, dict]:
        """Delegate to ConfigMigrationService for skill default custom properties."""
        return self.service.get_skill_default_custom_properties(skill_module)

    def _process_custom_properties(self, skill_module: str, custom_props: list) -> list:
        """Merge wingman custom property overrides with skill defaults and validate."""
        valid_props = []
        skill_default_props = self._get_skill_default_custom_properties(skill_module)

        for prop in custom_props:
            prop_id = prop.get("id")
            if not prop_id:
                continue

            # Find the default property with this id
            default_prop = skill_default_props.get(prop_id)
            if default_prop:
                # Merge: start with default, override with wingman values
                merged_prop = default_prop.copy()
                merged_prop.update(prop)
                merged_prop.pop("examples", None)  # Not needed in wingman config

                try:
                    CustomProperty(**merged_prop)
                    valid_props.append(merged_prop)
                except ValidationError:
                    self.log_warning(
                        f"- skipped custom property '{prop_id}' in skill '{skill_module}': validation failed after merge"
                    )
            else:
                # No default found - try to validate as-is
                try:
                    CustomProperty(**prop)
                    valid_props.append(prop)
                except ValidationError:
                    self.log_warning(
                        f"- skipped custom property '{prop_id}' in skill '{skill_module}': no default found and incomplete"
                    )

        return valid_props

    def _set_discoverable_from_template(
        self, old: dict, wingman_name: str, changes_made: list
    ) -> None:
        """Set discoverable skills/mcps from template for known wingmen."""
        from services.module_manager import ModuleManager

        template_path = self._get_template_path(wingman_name)
        if template_path and path.exists(template_path):
            template_config = ModuleManager.read_config(template_path)
            if template_config:
                old["discoverable_skills"] = template_config.get(
                    "discoverable_skills", []
                )
                changes_made.append(
                    f"discoverable_skills ({len(old['discoverable_skills'])} skills from template)"
                )

                old["discoverable_mcps"] = template_config.get("discoverable_mcps", [])
                changes_made.append(
                    f"discoverable_mcps ({len(old['discoverable_mcps'])} MCPs from template)"
                )
            else:
                self.log_warning(
                    f"Could not read template for {wingman_name}, using discoverable defaults"
                )
                self._set_discoverable_defaults(old)
        else:
            self.log_warning(
                f"Could not find template for {wingman_name}, using discoverable defaults"
            )
            self._set_discoverable_defaults(old)

    def _set_discoverable_for_custom_wingman(
        self, old: dict, changes_made: list
    ) -> None:
        """Set discoverable skills/mcps using defaults for custom wingmen."""
        old["discoverable_skills"] = self._get_skills_discoverable_by_default()
        changes_made.append(
            f"discoverable_skills (custom wingman: {len(old['discoverable_skills'])} skills discoverable by default)"
        )

        old["discoverable_mcps"] = self._get_mcps_discoverable_by_default()
        changes_made.append(
            f"discoverable_mcps (custom wingman: {len(old['discoverable_mcps'])} MCPs discoverable by default)"
        )

    def _set_discoverable_defaults(self, old: dict) -> None:
        """Fallback method to set discoverable defaults."""
        old["discoverable_skills"] = self._get_skills_discoverable_by_default()
        old["discoverable_mcps"] = self._get_mcps_discoverable_by_default()

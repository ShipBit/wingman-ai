# Wingman AI Skills Developer Documentation

This guide explains how skills work in Wingman AI and how to create your own custom skills.

## Table of Contents

- [What is a Skill?](#what-is-a-skill)
- [Setting Up Your Dev Environment](#setting-up-your-dev-environment)
- [How Skills are Discovered](#how-skills-are-discovered)
  - [Progressive Tool Disclosure](#progressive-tool-disclosure)
  - [The Capability Registry](#the-capability-registry)
  - [The SkillManifest](#the-skillmanifest)
  - [Writing Good Discovery Metadata](#writing-good-discovery-metadata-critical)
  - [Auto-Activation](#auto-activation)
- [Skill vs MCP: Decision Guide](#skill-vs-mcp-decision-guide)
- [Skill Types](#skill-types)
  - [Hook-Based Skills](#hook-based-skills)
  - [Tool-Based Skills](#tool-based-skills)
  - [Combining Hooks and Tools](#combining-hooks-and-tools)
- [Skill Structure](#skill-structure)
  - [Required Files](#required-files)
  - [default_config.yaml - Skill Metadata](#default_configyaml---skill-metadata)
  - [Custom Properties — Available Types](#custom-properties---available-types)
  - [Accessing Custom Properties](#accessing-custom-properties-in-your-skill)
- [Creating a Skill](#creating-a-skill)
- [Bundling Dependencies](#bundling-dependencies)
- [Skill Directory Structure](#skill-directory-structure)
- [AI Agent Bootstrap Checklist](#ai-agent-bootstrap-checklist)
- [Local AI API](#local-ai-api-selflocal_ai)
  - [Overview](#overview)
  - [Checking Availability](#checking-availability)
  - [Support Model](#support-model)
  - [Summarizing Large Text](#summarizing-large-text)
  - [Embeddings](#embeddings)
  - [Persistent Memory](#persistent-memory)
  - [Token Budget (Advanced)](#token-budget-advanced)
  - [Complete API Reference](#complete-api-reference)
  - [Full Example: Game Stats Tracker](#full-example-game-stats-tracker)
- [Additional Resources](#additional-resources)
  - [Example Skills to Study](#example-skills-to-study)
  - [Key APIs](#key-apis)
  - [Best Practices](#best-practices)

---

## What is a Skill?

Skills are Python modules that extend Wingman AI's functionality. All skills inherit from the `Skill` base class defined in [skill_base.py](skill_base.py).

A skill can:

- Hook into Wingman's lifecycle events (e.g., before TTS playback, after user message)
- Provide tools that the AI can call to perform actions
- Access Wingman's runtime configuration, services, and state
- Store persistent data in dedicated directories
- Bundle custom dependencies for distribution

---

## Setting Up Your Dev Environment

Before developing skills, you need a working Wingman AI Core dev environment:

- **macOS**: Follow [Developing on macOS](../docs/develop-macos.md)
- **Windows**: Follow [Developing on Windows](../docs/develop-windows.md)

These guides walk you through Python setup, virtual environment creation, dependency installation, and Visual Studio Code configuration. Once your dev environment is running (press `F5` to launch), you can start building skills.

---

## How Skills are Discovered

Wingman AI uses a **Progressive Tool Disclosure** system to manage skills and their tools efficiently. This system reduces token usage and improves reliability by only loading tools when needed.

### Progressive Tool Disclosure

When Wingman AI starts, not all skill tools are immediately available to the AI. Instead, skills use an **enum-based discovery mechanism**:

1. **Registration**: When a Wingman loads, all its configured skills are registered in the `SkillRegistry`
2. **Manifest Creation**: Each skill creates a lightweight `SkillManifest` containing metadata for discovery
3. **Unified Discovery**: The `CapabilityRegistry` combines skills and MCP servers into a single discovery interface
4. **Activation**: The AI receives an `activate_capability` tool with an enum of all available capabilities

**How the AI discovers and activates skills:**

```
User: "Can you generate an image for me?"

AI sees: activate_capability tool with enum including:
  - ImageGeneration: "Generate images using DALL-E 3. Keywords: create image, generate picture..."
  - FileManager: "Manage local files and folders..."
  - Timer: "Set timers and reminders..."

AI calls: activate_capability(capability_name="ImageGeneration")

Result: ImageGeneration's tools (generate_image) are now available

AI calls: generate_image(prompt="...")
```

**Benefits of this approach:**

- **Token efficient**: Only active skills' tools consume context tokens
- **Language agnostic**: Works reliably in any language (no fuzzy search)
- **100% reliable**: AI must pick from valid enum values
- **Semantic discovery**: Keywords and tags help AI find the right skill
- **Unified interface**: Skills and MCP servers use the same activation pattern

### The Capability Registry

The `CapabilityRegistry` ([capability_registry.py](../services/capability_registry.py)) provides a unified interface that combines:

- **Skills** (local, fast, Wingman runtime access)
- **MCP Servers** (local or remote, network-based)

From the AI's perspective, both are "capabilities" that provide tools. The registry:

- Lists skills first (faster/local) then MCPs (network-based) in the activation enum
- Delegates execution to the appropriate registry (`SkillRegistry` or `McpRegistry`)
- Preserves separate logging (`[SKILL]` vs `[MCP]` prefixes)
- Maintains separate lifecycle management

**Unified meta-tools:**

- `activate_capability(capability_name)` - Activate a skill or MCP server
- `list_active_capabilities()` - See what's currently active

### The SkillManifest

Each skill produces a `SkillManifest` dataclass that powers discovery. The manifest is defined in [skill_registry.py](../services/skill_registry.py):

```python
@dataclass
class SkillManifest:
    name: str                          # Internal class name (e.g., 'FileManager')
    display_name: str                  # Human-readable name (e.g., 'File Manager')
    description: str                   # What the skill does — shown in the activation enum
    tags: list[str]                    # Categorical tags like ['Utility', 'Image']
    tool_names: list[str]              # Names of tools this skill provides
    tool_summaries: list[str]          # One-line descriptions of each tool
    is_auto_activated: bool = False    # Always active, hidden from progressive disclosure
    discovery_keywords: str = ""       # Optional keywords to enhance discovery
```

Manifests are built automatically from your `default_config.yaml` and `@tool` decorators — you don't need to construct them manually. The `description`, `tags`, and `discovery_keywords` fields come from your config; `tool_names` and `tool_summaries` are extracted from your decorated tools at registration time.

### Writing Good Discovery Metadata (CRITICAL!)

> **The quality of your skill's discovery metadata directly determines whether the AI can find and activate it correctly. Poor metadata = invisible skill!**

The discovery system relies entirely on your skill's descriptions, keywords, and tags to match user intent. Take great care when writing these:

#### Skill Description (`description.en` in default_config.yaml)

**This is the MOST IMPORTANT field for discovery.** The AI reads this to decide if your skill matches the user's request.

Good skill descriptions:

- **Clear and concise**: Explain what the skill does in one sentence
- **Action-focused**: Start with verbs ("Generate images", "Manage files", "Set timers")
- **Include use cases**: Mention common scenarios ("useful for VTubers, audio mixing")
- **Avoid jargon**: Use plain language the AI can understand

```yaml
# GOOD
description:
  en: Generate images using DALL-E 3 based on text descriptions. Create artwork, illustrations, and visual content.

# BAD (too vague)
description:
  en: Image stuff.

# BAD (too technical)
description:
  en: Integrates with OpenAI's DALL-E 3 API endpoint to perform text-to-image synthesis operations.
```

#### Discovery Keywords (`discovery_keywords` in default_config.yaml)

Keywords are **optional but recommended** for any non-auto-activated skill. They enhance semantic matching by listing synonyms and variations of how users might request your skill's functionality.

If you omit `discovery_keywords`, the AI relies solely on your `description` to find the skill. For simple, well-described skills this may be sufficient, but adding keywords significantly improves discovery.

Good discovery keywords:

- **Synonyms**: All ways to say the same thing ("create image", "generate picture", "draw", "make image")
- **Domain terms**: Technical terms users might use ("DALL-E", "AI art", "image generation")
- **Action verbs**: What users want to do ("search", "find", "lookup", "query")
- **Common phrases**: Natural language requests ("show me", "get me", "I need")

```yaml
# GOOD - comprehensive keyword coverage
discovery_keywords:
  - create image
  - generate picture
  - make image
  - draw
  - DALL-E
  - AI art
  - image creation
  - artwork
  - illustration

# BAD - missing obvious variations
discovery_keywords:
  - image
```

#### Tool Descriptions (in `@tool` decorator or docstrings)

Once your skill is activated, the AI needs clear tool descriptions to use them correctly.

Good tool descriptions:

- **Explain WHEN to use the tool**: Include a "WHEN TO USE" section
- **Describe the outcome**: What happens when this tool is called?
- **Parameter guidance**: Explain what each parameter does and expects
- **Examples help**: Mention example scenarios

```python
# GOOD - Clear purpose and guidance
@tool(
    description="""Generates an image using DALL-E 3 based on a text description.

    WHEN TO USE:
    - User requests image creation: 'Generate an image of...', 'Create a picture of...'
    - User wants visual content created from a description
    - Any request for AI-generated artwork or illustrations

    Produces high-quality, detailed images matching user specifications.""",
    wait_response=True
)
async def generate_image(self, prompt: str) -> str:
    """
    Args:
        prompt: The image generation prompt describing what to create.
                Should be detailed and descriptive for best results.
    """

# BAD - Vague and unhelpful
@tool(description="Makes an image")
async def generate_image(self, prompt: str) -> str:
    """Args: prompt: a prompt"""
```

#### Tags (`tags` in default_config.yaml)

**Use for categorization.** Tags help group skills by domain and improve filtering.

- Use standard categories: `Utility`, `Image`, `File`, `Internet`, `Audio`, `Game`, `Productivity`, `Overlay`
- Be specific: Add domain tags like `Star Citizen`, `MSFS2020` for game integrations
- Keep it short: 2-4 tags maximum

```yaml
# GOOD
tags:
  - Image
  - Internet
  - Productivity

# BAD - too many, too vague
tags:
  - Tool
  - Thing
  - Feature
  - Capability
  - Function
```

#### Testing Your Metadata

**Before distributing your skill, test discovery:**

1. Disable `auto_activate` temporarily
2. Start Wingman AI and say variations of your use case:
   - "Can you help me generate an image?"
   - "I need to create a picture"
   - "Draw me something"
3. Check if the AI activates your skill (look for `[SKILL] Skill activated: YourSkill`)
4. If not, improve your description and keywords
5. Test in different languages if you support them

**Common discovery failures:**

- Description too vague: "This skill does things with files"
- Missing keywords: User says "draw" but you only have "generate image"
- Wrong category: Skill has wrong tags making it hard to filter
- Tool descriptions unclear: AI activates skill but doesn't know when to use tools

**Remember:** The AI cannot read your code. It ONLY sees your descriptions, keywords, and tags. Make them count!

### Auto-Activation

Skills can be marked with `auto_activate: true` in their `default_config.yaml`. This bypasses the progressive disclosure system.

**What auto_activate does:**

- The skill's tools are **always available** to the AI
- The skill is **hidden from the discovery enum** (not shown in `activate_capability`)
- The skill is marked as `(auto)` in `list_active_capabilities`
- The skill remains active even when conversation history is reset

**When to use auto_activate:**

Use `auto_activate: true` when:

- Your skill provides **essential functionality** that should always be available
- The skill has **very few tools** (1-3) with minimal token overhead
- The tools are **frequently used** across many conversation contexts
- The skill provides **hooks only** (no tools exposed to AI)
- Examples:
  - Audio Device Changer (automatic, hook-based)
  - Thinking Sound (hook-based audio feedback)
  - Quick Commands (frequently used, 1-2 tools)

**When NOT to use auto_activate:**

Do NOT use `auto_activate: true` when:

- Your skill has **many tools** (wastes tokens if not needed)
- The tools are **specialized** and only used occasionally
- The functionality is **domain-specific** (image generation, file management)
- You want users to **explicitly enable** the skill
- Examples:
  - Image Generation (specialized, high token cost)
  - File Manager (many tools, not always needed)
  - Timer (specialized use case)
  - Vision AI (expensive operations, explicit opt-in)

**Token impact example:**

```yaml
# Bad: ImageGeneration with auto_activate: true
# - Adds ~500 tokens to EVERY conversation
# - Tools rarely needed for most conversations
# - Wastes context on general chit-chat

# Good: ImageGeneration with auto_activate: false
# - Only adds tokens when user needs images
# - AI activates it on-demand: "generate an image of..."
# - Saves tokens for other context
```

**Configuration in default_config.yaml:**

```yaml
module: skills.your_skill.main
name: YourSkill
display_name: Your Skill Name
auto_activate: false # Default - requires explicit activation
# ... other settings
```

**Best practice:** Start with `auto_activate: false` and only enable it if:

1. Your skill is genuinely needed in most conversations, AND
2. The token cost is minimal (1-3 simple tools)

---

## Skill vs MCP: Decision Guide

Before creating a skill, decide whether your functionality should be:

1. **A Wingman Skill**
2. **A Local MCP Server**
3. **A Remote MCP Server**

### When to Use Skills

**Use a Skill when you need:**

- Access to Wingman's runtime (configs, hooks, audio player, etc.)
- Lifecycle hooks (on_play_to_user, on_add_message, etc.)
- Local system integration that requires deep Wingman context
- Simple distribution via Discord/ZIP files (no infrastructure needed)

**Drawbacks:**

- Dependencies must be bundled with the skill
- Distribution is manual (ZIP files shared on Discord)
- Updates require users to manually replace files

**Examples:**

- Audio Device Changer (hooks into audio playback)
- Auto Screenshot (hooks into conversation flow)
- Timer (maintains state across Wingman sessions)

### When to Use Local MCP Servers

**Use Local MCP when you need:**

- Standalone functionality that doesn't need Wingman runtime access
- Clean separation from Wingman's codebase
- Standard MCP protocol for potential reuse

**Drawbacks:**

- **Too complicated for most users** - requires MCP setup knowledge
- No access to Wingman runtime (configs, hooks, audio, etc.)
- Harder to share and install for non-technical users
- Requires users to configure MCP settings

**Examples:**

- File system operations
- Database queries
- Local API integrations

### When to Use Remote MCP Servers

**Use Remote MCP when you need:**

- Stateless operations that work the same for all users
- Easy sharing and distribution (just share the URL)
- Centralized updates (users always get the latest version)
- No local installation required

**Drawbacks:**

- **Stateless** - can't maintain state between calls
- No access to Wingman runtime
- Requires hosting infrastructure (e.g., Cloudflare Workers)
- Network dependency

**Examples:**

- Web searches
- API calls to external services
- Data transformations
- Calculator functions

### Decision Matrix

| Feature                | Skill            | Local MCP | Remote MCP    |
| ---------------------- | ---------------- | --------- | ------------- |
| Wingman Runtime Access | Yes              | No        | No            |
| Lifecycle Hooks        | Yes              | No        | No            |
| Easy Sharing           | Manual (Discord) | Complex   | URL only      |
| Maintains State        | Yes              | Yes       | No            |
| Updates                | Manual           | Manual    | Automatic     |
| User Setup Complexity  | Medium           | High      | Low           |
| Hosting Required       | No               | No        | Yes           |
| Dependencies           | Bundled          | Separate  | None (remote) |

**TL;DR:** If you need Wingman integration → **Skill**. If you need easy sharing and updates → **Remote MCP**. Avoid Local MCP unless you have a specific reason.

---

## Skill Types

Skills come in two main flavors based on how they interact with the AI:

### Hook-Based Skills

Hook-based skills intercept and respond to Wingman lifecycle events. They work **automatically** without requiring the AI to explicitly call them.

**Use hooks when:**

- You need to modify or intercept data flow (e.g., change audio device before playback)
- Your functionality should run automatically based on events
- You're implementing side effects that don't require AI decision-making

**Common hooks:**

```python
async def on_add_user_message(self, message: str) -> None:
    """Called when a user message is added to the conversation."""
    pass

async def on_add_assistant_message(self, message: str, tool_calls: list) -> None:
    """Called when an assistant message is added to the conversation."""
    pass

async def on_play_to_user(self, text: str, sound_config: SoundConfig) -> str:
    """Called before TTS synthesis. Return modified text or {SKIP-TTS} to skip."""
    return text

async def prepare(self) -> None:
    """Called once during initialization. Set up resources here."""
    pass

async def unload(self) -> None:
    """Called when skill is unloaded. Clean up resources here."""
    pass
```

**Tool behavior hooks:**

These hooks let you control how the AI handles tool responses without modifying the tool itself:

```python
async def is_summarize_needed(self, tool_name: str) -> bool:
    """Returns whether a tool's result should be summarized by the AI.
    Defaults to True. The @tool decorator's `summarize` parameter sets
    this per-tool, but you can override this method for dynamic logic."""
    return True

async def is_waiting_response_needed(self, tool_name: str) -> bool:
    """Returns whether a 'please wait' message should be shown while
    the tool executes. Defaults to False. The @tool decorator's
    `wait_response` parameter sets this per-tool."""
    return False
```

**Example:** [AudioDeviceChanger](audio_device_changer/main.py)

```python
class AudioDeviceChanger(Skill):
    def __init__(self, config, settings, wingman):
        super().__init__(config, settings, wingman)
        # Subscribe to audio events
        self.wingman.audio_player.playback_events.subscribe(
            "finished", self.playback_finished
        )

    async def on_play_to_user(self, text: str, sound_config: SoundConfig) -> str:
        """Automatically change audio device before TTS playback."""
        audio_device = self.retrieve_custom_property_value("audio_changer_device", [])
        if audio_device:
            await self._change_audio_device(audio_device)
        return text

    async def playback_finished(self, _):
        """Reset audio device after playback."""
        await self.reset_audio_device()
```

### Tool-Based Skills

Tool-based skills provide **tools** (functions) that the AI can call when needed. The AI decides when and how to use these tools based on the user's request.

**Use tools when:**

- The AI needs to make a decision about when to use your functionality
- You're providing discrete actions (generate image, set timer, search web)
- Your functionality has parameters that the AI should determine

**Modern approach (recommended):** Use the `@tool` decorator to automatically generate tool schemas from your function signatures:

```python
from skills.skill_base import Skill, tool
from typing import Literal

class ImageGeneration(Skill):

    @tool(
        name="generate_image",
        description="Generates an image using DALL-E 3 based on a text description.",
        wait_response=True  # Show "please wait" message
    )
    async def generate_image(self, prompt: str) -> str:
        """
        Args:
            prompt: The image generation prompt describing what to create.
        """
        image = await self.wingman.generate_image(prompt)
        return "Here is your generated image."

    @tool(description="Set a timer with specific duration and behavior")
    def create_timer(
        self,
        seconds: int,
        label: str = "Timer",
        mode: Literal["once", "loop"] = "once"
    ) -> str:
        """
        Args:
            seconds: Duration in seconds
            label: Optional label for the timer
            mode: Whether to run once or loop continuously
        """
        # Implementation here
        return f"Timer '{label}' set for {seconds} seconds"
```

**Key features of `@tool` decorator:**

- **Auto-generates OpenAI tool schema** from type hints
- Required parameters: No default value in signature
- Optional parameters: Has default value
- Supports `Literal` types for enum-like parameters
- Uses docstring for tool and parameter descriptions
- `wait_response=True`: Shows "please wait" message for long operations
- `summarize=False`: Skip AI summarization after tool execution

**Example:** [ImageGeneration](image_generation/main.py)

### Combining Hooks and Tools

Skills can use **both** hooks and tools! For example:

- Use tools to let the AI perform actions
- Use hooks to automatically clean up or manage state

```python
class Timer(Skill):
    @tool()
    def create_timer(self, seconds: int) -> str:
        """AI calls this to create a timer."""
        # Create timer
        return "Timer created"

    async def unload(self):
        """Hook automatically cleans up all timers when skill unloads."""
        await self._cleanup_all_timers()
```

---

## Skill Structure

Every skill requires these files:

### Required Files

```text
skills/your_skill_name/
├── main.py              # Your Skill class implementation
├── default_config.yaml  # Skill metadata and configuration
└── logo.png            # Skill icon (displayed in UI)
```

### `main.py` - Your Skill Implementation

```python
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class YourSkillName(Skill):
    """Brief description of what your skill does."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        # Initialize your skill here

    async def validate(self) -> list[WingmanInitializationError]:
        """
        Validate configuration at startup.
        Call retrieve_custom_property_value() for each config property.
        """
        errors = await super().validate()

        # Validate properties exist
        self.retrieve_custom_property_value("your_property", errors)

        return errors

    async def prepare(self) -> None:
        """Called once during initialization. Set up resources."""
        await super().prepare()
        # Initialize providers, subscribe to events, etc.

    # Add your tools or hooks here

    async def unload(self) -> None:
        """Clean up resources when skill is unloaded."""
        await super().unload()
        # Unsubscribe from events, close connections, etc.
```

### `default_config.yaml` - Skill Metadata

> **IMPORTANT**: The `description` and `discovery_keywords` fields are CRITICAL for skill discovery. The AI uses these to match user intent. See [Writing Good Discovery Metadata](#writing-good-discovery-metadata-critical) for detailed guidance.

```yaml
module: skills.your_skill_name.main # Python import path
name: YourSkillName # Class name (must match main.py)
display_name: Your Skill Name # Human-readable name (shown in UI)
author: Your Name # Your name or organization

tags: # Categories for filtering - use standard categories
  - Utility
  - Internet

auto_activate: false # Auto-enable for all Wingmen? (see Auto-Activation section)

# Controls whether the skill appears in the activation enum by default.
# Defaults to true if omitted. Set to false for specialized skills that
# should only be activated when explicitly added to a Wingman's config.
discoverable_by_default: true

# CRITICAL: This is how the AI finds your skill!
description:
  en: |
    Clear, concise description of what your skill does.
    Be specific about functionality and use cases.
    The AI reads this to decide if it matches the user's request.
  de: German description (optional but helpful for international users)

# Optional but recommended: All variations of how users might ask for your functionality
discovery_keywords:
  - primary action verb (e.g., "generate", "create", "manage")
  - synonyms for your functionality
  - domain-specific terms users might say
  - common phrases and variations
  - related concepts
  # Example for image generation:
  # - create image
  # - generate picture
  # - draw
  # - make image
  # - DALL-E
  # - AI art

custom_properties: # User-configurable settings
  - id: your_property_id # Unique identifier
    name: Property Display Name # Shown in UI
    hint: Helpful description for users
    value: default_value # Default value
    required: true # Is this property required?
    property_type: string # See "Custom Properties — Available Types" below
```

### Custom Properties — Available Types

Custom properties allow your skill to be configured by users through the Wingman AI client UI. Each property type renders a specific UI control.

> **IMPORTANT — Use SecretKeeper for API Keys and Secrets!**
>
> **Never use custom properties for API keys, passwords, or other sensitive data.** Always use the `SecretKeeper` service instead:
>
> ```python
> async def validate(self) -> list[WingmanInitializationError]:
>     errors = await super().validate()
>
>     # Use SecretKeeper for sensitive data
>     api_key = await self.retrieve_secret(
>         secret_name="your_service_api_key",
>         errors=errors,
>         hint="Get your API key from https://your-service.com/api-keys"
>     )
>
>     return errors
> ```
>
> **Why use SecretKeeper?**
>
> - Secrets are stored securely in `secrets.yaml` (separate from config)
> - Not exposed in config files that might be shared
> - Centralized management across all Wingmen and skills
> - Users are prompted automatically if secrets are missing
> - Supports secret rotation without changing skill code
>
> **Custom properties should only be used for:**
>
> - Non-sensitive configuration values
> - User preferences (quality settings, timeouts, etc.)
> - Feature flags and options
> - File paths and URLs (public ones)

#### `string` - Single-line Text Input

Simple text input field for short strings.

```yaml
custom_properties:
  - id: api_endpoint
    name: API Endpoint
    hint: The URL of your API endpoint
    value: 'https://api.example.com'
    required: true
    property_type: string
```

**Use for:** URLs, short text values, identifiers

---

#### `textarea` - Multi-line Text Input

Large text area for longer strings, paragraphs, or formatted text.

```yaml
custom_properties:
  - id: custom_prompt
    name: Custom Instructions
    hint: Additional instructions for the AI
    value: |
      Be concise and helpful.
      Always confirm actions before executing.
    required: false
    property_type: textarea
```

**Use for:** Prompts, instructions, multi-line configuration, formatted text

---

#### `number` - Numeric Input

Number input field with validation for integers and floats.

```yaml
custom_properties:
  - id: timeout_seconds
    name: Timeout (seconds)
    hint: How long to wait before timing out
    value: 30
    required: true
    property_type: number
```

**Use for:** Timeouts, thresholds, counts, durations

---

#### `boolean` - Checkbox

Simple on/off toggle rendered as a checkbox.

```yaml
custom_properties:
  - id: enable_debug
    name: Enable Debug Logging
    hint: Show detailed debug information
    value: false
    required: false
    property_type: boolean
```

**Use for:** Feature flags, enable/disable options, binary choices

---

#### `single_select` - Dropdown Menu

Dropdown menu with predefined options. Requires `options` list.

```yaml
custom_properties:
  - id: quality_level
    name: Quality Level
    hint: Select the quality level for processing
    value: 'medium'
    required: true
    property_type: single_select
    options:
      - label: 'Low (Faster)'
        value: 'low'
      - label: 'Medium (Balanced)'
        value: 'medium'
      - label: 'High (Best Quality)'
        value: 'high'
```

**Use for:** Predefined choices, quality settings, mode selection

---

#### `slider` - Range Slider

Visual slider control for numeric values within a range. Configure range in `options`.

```yaml
custom_properties:
  - id: volume
    name: Volume
    hint: Audio volume level
    value: 0.8
    required: true
    property_type: slider
    options:
      - label: 'min'
        value: 0.0
      - label: 'max'
        value: 1.0
      - label: 'step'
        value: 0.1
```

**Use for:** Volume controls, opacity, percentage values, anything with a visual range

---

#### `color` - Color Picker

Color picker for hex color values. Renders a visual color picker in the UI.

```yaml
custom_properties:
  - id: accent_color
    name: Accent Color
    hint: Accent color for highlights (hex format).
    value: '#00aaff'
    required: false
    property_type: color

  - id: bg_color
    name: Background Color
    hint: Background color (hex format, e.g. #1e212b or #1e212b80 for 50% transparent).
    value: '#1e212b'
    required: false
    property_type: color
```

**Use for:** Theme colors, accent colors, background colors, any visual color setting. Values are hex strings (e.g., `#00aaff`). Supports optional alpha channel (e.g., `#1e212b80` for 50% transparency).

---

#### `audio_device` - Audio Device Selector

Dropdown populated with available audio devices from the user's system.

```yaml
custom_properties:
  - id: output_device
    name: Output Audio Device
    hint: The audio device to use for playback
    value: null
    required: false
    property_type: audio_device
```

**Use for:** Audio routing, device selection, VTuber setups

**Note:** Value is `null` by default. When set, it becomes an `AudioDeviceSettings` object with `name` and `hostapi` fields.

---

#### `voice_selection` - Voice Selector

Complex selector for TTS voices across different providers (OpenAI, ElevenLabs, Azure, etc.).

```yaml
custom_properties:
  - id: alert_voice
    name: Alert Voice
    hint: Voice used for alerts
    value: null
    required: false
    property_type: voice_selection
    options:
      - label: 'multiple'
        value: false # Set to true for multiple voice selection
```

**Use for:** Custom TTS voices, per-skill voice configuration, voice randomization

**Value format:**

```python
VoiceSelection(
    provider="openai",  # or "elevenlabs", "azure", etc.
    voice="alloy"       # voice ID/name for that provider
)
```

**Multiple voices:** Set `options[0].value = true` to allow selecting multiple voices (returns `list[VoiceSelection]`)

---

#### `audio_files` - Audio File Manager

File browser for selecting audio files with playback settings.

```yaml
custom_properties:
  - id: notification_sound
    name: Notification Sound
    hint: Audio file(s) to play for notifications
    value:
      files: []
      volume: 1.0
      wait: false
      stop: false
      resume: false
    required: false
    property_type: audio_files
```

**Use for:** Sound effects, notification sounds, custom audio playback

**Value format:**

```python
AudioFileConfig(
    files=[AudioFile(path="/path/to/sound.mp3", name="notification")],
    volume=0.8,
    wait=False,    # Wait for playback to finish
    stop=False,    # Stop instead of play
    resume=False   # Resume last stopped audio
)
```

---

### Accessing Custom Properties in Your Skill

**Always retrieve custom properties just-in-time, never cache them.** Users can change property values in the UI while the skill is running. Retrieving values fresh ensures your skill always uses current settings without requiring restart or reactivation.

```python
class YourSkill(Skill):
    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        # Validate that required properties exist (don't cache!)
        self.retrieve_custom_property_value("timeout_seconds", errors)
        self.retrieve_custom_property_value("quality_level", errors)
        return errors

    def _get_timeout(self) -> int:
        """Get timeout value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("timeout_seconds", errors)

    def _get_quality(self) -> str:
        """Get quality level just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("quality_level", errors)

    @tool()
    async def process_data(self, data: str) -> str:
        """Process data with current settings."""
        timeout = self._get_timeout()  # Always fresh value
        quality = self._get_quality()  # Reflects UI changes immediately
        # ... use the values
```

```python
# BAD - Don't cache config values:
async def validate(self):
    errors = await super().validate()
    self.my_setting = self.retrieve_custom_property_value("my_setting", errors)  # cached!
    return errors

# GOOD - Retrieve fresh at runtime:
def _get_my_setting(self):
    errors = []
    return self.retrieve_custom_property_value("my_setting", errors)
```

### `logo.png` - Skill Icon

- Recommended size: 256x256px or 512x512px
- Format: PNG with transparency
- Design: Clear, simple icon representing your skill's function

---

## Creating a Skill

### Step-by-Step Guide

#### If Your Skill Has NO New Dependencies

1. **Create your skill directory** in the repo:

   ```bash
   mkdir -p skills/your_skill_name
   cd skills/your_skill_name
   ```

2. **Create the required files:**
   - `main.py` (your Skill class)
   - `default_config.yaml` (configuration)
   - `logo.png` (icon)

3. **Implement and test** your skill by running Wingman AI from source

4. **Test with release version:**

   ```bash
   # Copy to user directory for testing
   # macOS:
   cp -r skills/your_skill_name ~/Library/Application\ Support/WingmanAI/custom_skills/

   # Windows:
   # Copy skills/your_skill_name to %APPDATA%/ShipBit/WingmanAI/custom_skills/
   ```

5. **Package for distribution:**
   - ZIP the skill directory
   - Share on Discord or your preferred platform

#### If Your Skill Has New Dependencies

See [Bundling Dependencies](#bundling-dependencies) for the full process.

**Quick summary:**

1. Create your skill directory and required files
2. Create a virtual environment inside your skill directory
3. Install and develop with your dependencies
4. Bundle with `pip install -r requirements.txt --target=dependencies`
5. Remove `venv/` before distributing (only `dependencies/` is needed)

---

## Bundling Dependencies

### Why Bundle Dependencies?

Wingman AI uses PyInstaller to create standalone executables. Skills with custom dependencies need to bundle those dependencies so they work in the frozen executable environment.

### Dependency Loading

When a skill has a `dependencies/` directory, Wingman AI automatically adds it to `sys.path` before loading the skill. This allows the skill to import its bundled packages.

From `module_manager.py`:

```python
dependencies_dir = path.join(custom_skill_path, "dependencies")
with add_to_sys_path(dependencies_dir):
    # Load skill with access to bundled dependencies
    spec = util.spec_from_file_location(skill_name, plugin_module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
```

### Step-by-Step Bundling Process

**1. Create a virtual environment inside your skill directory:**

```bash
cd skills/your_skill_name

# macOS/Linux:
python -m venv venv
source venv/bin/activate

# Windows:
python -m venv venv
.\venv\Scripts\activate
```

**2. Install your dependencies with the venv active:**

```bash
pip install your-package another-package
```

**3. Implement and test your skill** (the skill will automatically use the venv when running from source)

**4. Generate requirements.txt:**

```bash
pip freeze > requirements.txt
```

**5. Install dependencies to target directory:**

```bash
pip install -r requirements.txt --target=dependencies
```

**6. Copy to custom_skills directory and remove venv:**

```bash
# macOS:
cp -r skills/your_skill_name ~/Library/Application\ Support/WingmanAI/custom_skills/
rm -rf ~/Library/Application\ Support/WingmanAI/custom_skills/your_skill_name/venv

# Windows (PowerShell):
Copy-Item -Recurse skills\your_skill_name $env:APPDATA\ShipBit\WingmanAI\custom_skills\
Remove-Item -Recurse $env:APPDATA\ShipBit\WingmanAI\custom_skills\your_skill_name\venv
```

**7. Test with release version:**

- Close VS Code / development environment
- Run the installed Wingman AI application
- Verify your skill loads and functions correctly

**8. Create distribution ZIP:**

```bash
# From custom_skills directory
cd ~/Library/Application\ Support/WingmanAI/custom_skills  # macOS
cd %APPDATA%\ShipBit\WingmanAI\custom_skills  # Windows

# Create ZIP
zip -r your_skill_name.zip your_skill_name/
```

**To reset and start fresh:**

```bash
cd skills/your_skill_name
rm -rf venv dependencies requirements.txt
# Start over from step 1
```

### Common Dependency Issues

**Problem:** Dependency conflicts with Wingman AI's core dependencies

**Solution:** Try to use compatible versions. Check Wingman's `requirements.txt` for version constraints.

---

**Problem:** Large dependency size

**Solution:** Consider if you really need all the dependencies. Some packages (like `transformers` or `torch`) can be huge and may not be suitable for skill distribution.

---

**Problem:** Platform-specific dependencies

**Solution:** Document which platforms your skill supports. Some dependencies (especially those with C extensions) may not work on all platforms.

---

## Skill Directory Structure

Wingman AI loads skills from multiple locations with a specific priority order:

### Load Priority (Later Overrides Earlier)

1. **Bundled skills** (built into the app)
   - Release: `_internal/skills/`
   - Dev mode: `./skills/`

2. **Custom skills** (user-created, persists across updates)
   - macOS: `~/Library/Application Support/WingmanAI/custom_skills/`
   - Windows: `%APPDATA%\ShipBit\WingmanAI\custom_skills\`

### Source vs Working Directory

**Source directory (`skills/` in repo):**

- Used when running Wingman AI from source for development
- Changes here are immediately reflected when you restart
- Perfect for iterating on your skill

**Custom skills directory (APPDATA):**

- Used by the installed/release version of Wingman AI
- **NOT versioned** - persists across Wingman AI updates
- Users install skills here
- Custom skills can override built-in skills with the same name

### Skill with Dependencies Structure

When your skill is fully bundled, it looks like this:

```text
custom_skills/your_skill_name/
├── main.py
├── default_config.yaml
├── logo.png
├── requirements.txt         # Generated by pip freeze
└── dependencies/            # Generated by pip install --target
    ├── your_package/
    ├── another_package/
    └── ...all dependencies...
```

**Note:** The `venv/` directory is ONLY used during development and should NOT be included in the distributed ZIP file.

### Generated Files Directory

Skills can store generated or persistent files using `self.get_generated_files_dir()`:

```python
class YourSkill(Skill):
    def __init__(self, config, settings, wingman):
        super().__init__(config, settings, wingman)
        self.output_dir = self.get_generated_files_dir()
        # macOS: ~/Library/Application Support/WingmanAI/generated_files/YourSkillName
        # Windows: %APPDATA%/ShipBit/WingmanAI/generated_files/YourSkillName
```

This directory:

- Is automatically created
- Persists across Wingman AI updates (not versioned)
- Is unique per skill
- Perfect for saving images, logs, exports, etc.

---

## AI Agent Bootstrap Checklist

If you're using an AI agent to create a skill, use this checklist to ensure everything is set up correctly:

### Pre-Development

- [ ] Decide: Does this need to be a Skill, Local MCP, or Remote MCP?
- [ ] Choose skill type: Hook-based, Tool-based, or both?
- [ ] List required dependencies (if any)
- [ ] Check for dependency conflicts with core Wingman packages

### Skill Structure

- [ ] Create `skills/your_skill_name/` directory
- [ ] Create `main.py` with Skill class inheriting from `Skill`
- [ ] Create `default_config.yaml` with all required fields:
  - [ ] `module` path is correct
  - [ ] `name` matches class name exactly
  - [ ] `display_name` is user-friendly
  - [ ] `author` is set
  - [ ] `tags` are appropriate
  - [ ] `description` (English at minimum)
  - [ ] `custom_properties` are defined (if needed)
- [ ] Create `logo.png` (256x256 or 512x512, PNG format)

### Code Implementation

- [ ] `__init__` calls `super().__init__()`
- [ ] `validate()` implemented to check custom properties
- [ ] Config values retrieved just-in-time (not cached in `validate()`)
- [ ] `prepare()` implemented for initialization (if needed)
- [ ] `unload()` implemented for cleanup (if needed)
- [ ] Tools use `@tool` decorator with type hints
- [ ] Tool descriptions are clear and include "WHEN TO USE" guidance
- [ ] Hooks are implemented correctly (if used)
- [ ] Type hints are used correctly (`TYPE_CHECKING` guard for imports)

### Dependencies (if any)

- [ ] Virtual environment created in skill directory
- [ ] Dependencies installed with venv active
- [ ] `requirements.txt` generated with `pip freeze`
- [ ] `dependencies/` folder generated with `pip install --target`
- [ ] Tested in development mode (from source)
- [ ] Tested in release mode (from custom_skills)

### Testing

- [ ] Skill loads without errors
- [ ] `validate()` catches configuration errors
- [ ] Tools appear in AI tool list
- [ ] Tools execute correctly with various parameters
- [ ] Hooks trigger at the right time
- [ ] No conflicts with other skills
- [ ] Memory leaks checked (unload() cleanup works)
- [ ] Error handling works gracefully

### Distribution

- [ ] Skill copied to custom_skills directory
- [ ] `venv/` directory removed (if exists)
- [ ] `dependencies/` included (if needed)
- [ ] Tested with release version of Wingman AI
- [ ] ZIP file created correctly
- [ ] README or documentation written (optional but nice)
- [ ] Shared on Discord with usage instructions

### Documentation

- [ ] Clear description of what the skill does
- [ ] Configuration instructions (if custom_properties exist)
- [ ] Example use cases
- [ ] Known limitations documented
- [ ] Platform compatibility noted (if relevant)

---

## Local AI API (`self.local_ai`)

Every skill has access to a `self.local_ai` facade that provides a stable, safe interface to the local AI capabilities: the support model (small local LLM), embeddings, and persistent memory.

### Overview

The local AI features run entirely on the user's machine via llama.cpp. Users enable and configure them in Settings (model selection, context window size, GPU backend). Your skill doesn't need to worry about any of that — `self.local_ai` handles everything internally.

**Key principles:**

- **Always available on `self`** — no imports needed, lazily initialized
- **Safe by default** — all methods handle errors internally, log them to the client, and return `None` or empty results. Skills never need `try/except` around these calls.
- **Both async and sync** — async is preferred, sync variants have a `_sync` suffix
- **Stable contract** — the internal implementation may change across versions, but this API won't break

```python
# Quick taste — that's really all it takes:
result = await self.local_ai.support("Summarize this text", "You are a summarizer.")
if result:
    print(result.text)
```

### Checking Availability

Local AI is optional — users may not have it enabled or models may not be downloaded yet. Always check before using:

```python
@tool()
async def my_tool(self, query: str) -> str:
    if not self.local_ai.available:
        return "Local AI is not enabled. Please enable it in Settings."

    result = await self.local_ai.support(query, "Answer concisely.")
    return result.text if result else "Processing failed."
```

**Availability properties:**

```python
self.local_ai.available        # Support model is loaded and ready
self.local_ai.embed_available  # Embedding model is loaded and ready
self.local_ai.memory_available # Persistent memory is available (requires local AI + wingman config)
```

> **Tip:** `memory_available` implies `embed_available` (memory needs embeddings). `available` and `embed_available` are independent — both models load separately.

### Support Model

The support model is a small local LLM (e.g., Qwen 3.5 2B) that runs on the user's machine. Use it for text processing tasks like extraction, classification, summarization, or reformatting. It's fast, free, and private — no API calls leave the machine.

```python
async def support(text: str, system_prompt: str = "") -> SupportResponse | None
def support_sync(text: str, system_prompt: str = "") -> SupportResponse | None
```

**Parameters:**

| Parameter       | Type  | Description                                                    |
| --------------- | ----- | -------------------------------------------------------------- |
| `text`          | `str` | The input text / user prompt                                   |
| `system_prompt` | `str` | Instructions for the model. If empty, a default prompt is used |

**Returns `SupportResponse`:**

```python
@dataclass(frozen=True)
class SupportResponse:
    text: str | None         # The model's response
    prompt_tokens: int       # Tokens used by the input
    completion_tokens: int   # Tokens generated
    truncated: bool          # True if output was cut off by context limit
```

Returns `None` if local AI is unavailable or an error occurs (error is logged to client automatically).

**Examples:**

```python
# Simple text processing
result = await self.local_ai.support(
    text=user_message,
    system_prompt="Extract the player name and ship type from this message. Return as JSON."
)
if result and result.text:
    data = json.loads(result.text)

# Check if output was truncated
result = await self.local_ai.support(text=very_long_input, system_prompt="Summarize.")
if result and result.truncated:
    # The model ran out of context — consider using summarize() instead
    pass
```

> **Important:** The support model has a limited context window (user-configurable, default 4096 tokens). If your input is too large, the model silently loses data beyond its context limit. For potentially large inputs, use `summarize()` instead.

#### Prompt Writing Guidelines for Small Models

The support model is a 2B-parameter model with limited instruction-following ability. Prompts that work well with large cloud models (GPT-4, Claude) will often fail here. Follow these rules when writing `system_prompt` strings:

- **Be direct and literal.** Use short, imperative sentences. Avoid nuance, hedging, or nested clauses.
- **Use labeled sections** (`Backstory:`, `Input:`, `Rules:`) instead of prose paragraphs. The model parses structured prompts more reliably.
- **Say "EXACT words"** when you want the model to reference source material. Without this, it will paraphrase loosely and hallucinate details (e.g., turning "gift ideas" into "gift cards").
- **Say "IN CHARACTER" explicitly** when the model must rephrase instructions in its persona's voice. Otherwise it will dump template text verbatim (e.g., outputting "The user talks to you by holding the home key" instead of weaving it into a natural sentence).
- **Constrain what it may NOT do.** Small models are prone to confabulation — add explicit "Do NOT add anything not in [source]" rules.
- **Keep prompts short.** Every token of system prompt reduces the budget available for input and output. Aim for under 200 tokens.

### Summarizing Large Text

When you have text that might exceed the model's context window (e.g., API responses, large documents), use `summarize()`. It automatically chunks the text, summarizes each chunk, and merges the results.

```python
async def summarize(text: str, instruction: str = "") -> SupportResponse | None
def summarize_sync(text: str, instruction: str = "") -> SupportResponse | None
```

**Parameters:**

| Parameter     | Type  | Description                                                                 |
| ------------- | ----- | --------------------------------------------------------------------------- |
| `text`        | `str` | The text to summarize. Can be arbitrarily large                             |
| `instruction` | `str` | Optional focus instruction (e.g., "Focus on combat stats and ship loadout") |

If the text fits in the context window, it's processed in a single call (same as `support()`). If it's too large, chunking and merging happen automatically.

**Common pattern — API call → summarize → remember:**

```python
@tool(wait_response=True)
async def fetch_player_stats(self, player_name: str) -> str:
    """Fetch and remember player statistics."""
    if not self.local_ai.available:
        return "Local AI is not enabled."

    # 1. Fetch (could be huge)
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"https://api.game.com/stats/{player_name}")
        raw = await resp.text()

    # 2. Summarize — handles any size automatically
    summary = await self.local_ai.summarize(
        text=raw,
        instruction="Extract key stats: rank, wins, losses, favorite loadout."
    )
    if not summary or not summary.text:
        return "Failed to process stats."

    # 3. Remember for future conversations
    if self.local_ai.memory_available:
        await self.local_ai.remember_fact(
            f"{player_name}'s stats: {summary.text}"
        )

    return summary.text
```

**When to use `support()` vs `summarize()`:**

| Use `support()` when                         | Use `summarize()` when                     |
| -------------------------------------------- | ------------------------------------------ |
| Input size is predictable and small          | Input size is unknown or potentially large |
| You need precise control over the prompt     | You want a hands-off summary               |
| Doing extraction, classification, formatting | Condensing API responses, documents, logs  |

### Embeddings

Generate vector embeddings for semantic search, similarity comparison, or custom RAG workflows. Embeddings are 768-dimensional vectors from the Nomic Embed v1.5 model.

```python
async def embed(texts: list[str]) -> list[list[float]] | None
def embed_sync(texts: list[str]) -> list[list[float]] | None
```

**Example:**

```python
# Generate embeddings for custom similarity search
embeddings = await self.local_ai.embed([
    "The user prefers stealth gameplay",
    "The user likes aggressive combat tactics",
])
if embeddings:
    # embeddings[0] = 768-dim vector for first text
    # embeddings[1] = 768-dim vector for second text
    similarity = cosine_similarity(embeddings[0], embeddings[1])
```

> **Tip:** For most use cases, the persistent memory API (below) handles embeddings automatically. Only use `embed()` directly if you're building custom search or similarity features.

### Persistent Memory

Persistent memory lets your skill remember facts about the user across conversations. Memories are stored locally in a SQLite database with vector embeddings for semantic search.

#### Remembering Facts

```python
async def remember_fact(
    content: str,
    entry_type: MemoryType = MemoryType.FACT,
) -> int | None
def remember_fact_sync(...) -> int | None
```

**Automatic deduplication:** When you save a fact that's semantically similar (>90%) to an existing one, it **updates** the existing entry instead of creating a duplicate. This means you can safely call `remember_fact()` repeatedly without worrying about duplicates.

```python
# First call: creates a new entry
await self.local_ai.remember_fact("Player rank: Gold 3")

# Later: player ranks up — this UPDATES the existing entry (>90% similar)
await self.local_ai.remember_fact("Player rank: Platinum 1")
```

**Memory types:**

```python
from services.skill_local_ai import MemoryType

MemoryType.FACT             # Durable facts about the user (default)
MemoryType.SESSION_SUMMARY  # Conversation session summaries
```

**Returns** the entry ID (`int`) on success, or `None` on failure.

#### Recalling Memories

```python
async def recall_memory(
    query: str,
    limit: int = 5,
    entry_type: MemoryType | None = None,
) -> list[MemorySearchResult]
def recall_memory_sync(...) -> list[MemorySearchResult]
```

Search memories by semantic similarity. Returns results sorted by relevance.

```python
@dataclass(frozen=True)
class MemorySearchResult:
    id: int                     # Entry ID (for update/delete)
    content: str                # The memory text
    entry_type: str             # "fact" or "session_summary"
    source_wingman: str | None  # Which wingman stored this
    created_at: float           # Unix timestamp
```

**Always returns a list** — empty on failure or no matches. Safe to iterate without None checks.

```python
# Search for relevant memories
results = await self.local_ai.recall_memory("player's ship and loadout", limit=3)
for memory in results:
    print(f"[{memory.entry_type}] {memory.content}")

# Filter by type
facts_only = await self.local_ai.recall_memory(
    "combat preferences",
    entry_type=MemoryType.FACT
)
```

#### Getting Memory Context for Prompts

```python
async def memory_context(query: str, max_tokens: int = 500) -> str
def memory_context_sync(...) -> str
```

Returns a **pre-formatted string** of relevant memories, ready to inject into a system prompt. Combines facts and recent session summaries, formatted with headers.

**Always returns a string** — empty on failure. Safe to concatenate directly.

```python
# Build context-aware prompts
async def get_prompt(self) -> str | None:
    """Inject relevant memories into the wingman's system prompt."""
    if not self.local_ai.memory_available:
        return None

    context = await self.local_ai.memory_context("user preferences and history")
    if context:
        return f"What you remember about this user:\n{context}"
    return None
```

#### Updating and Deleting Memories

```python
# Update a specific memory (re-embeds automatically)
async def update_memory(entry_id: int, new_content: str) -> bool
def update_memory_sync(...) -> bool

# Delete by ID (deterministic)
async def forget_memory_by_id(entry_id: int) -> bool
def forget_memory_by_id_sync(...) -> bool

# Delete by semantic search (fuzzy — finds closest match)
async def memory_forget(query: str) -> bool
def memory_forget_sync(...) -> bool
```

**Two deletion strategies:**

```python
# Strategy 1: Track the ID from remember_fact() — deterministic
entry_id = await self.local_ai.remember_fact("Player owns a Cutlass Black")
# ... later ...
await self.local_ai.forget_memory_by_id(entry_id)  # Exactly this entry

# Strategy 2: Fuzzy search — deletes the closest semantic match
await self.local_ai.memory_forget("Cutlass Black")  # Finds and deletes closest match
```

> **When to use which:** Use `forget_memory_by_id()` when you tracked the ID. Use `memory_forget()` when you want to delete "anything about X" without tracking IDs. Deduplication in `remember_fact()` often makes explicit deletion unnecessary — just save the updated fact and the old one gets replaced.

### Token Budget (Advanced)

Most skills don't need this. Use it only if you're sending large amounts of text and need to chunk it yourself (e.g., processing documents in batches).

```python
def get_support_model_token_budget(system_prompt: str = "") -> TokenBudget | None
```

```python
@dataclass(frozen=True)
class TokenBudget:
    n_ctx: int              # Raw context window from user settings
    safe_ctx: int           # Usable context after 10% safety margin
    system_tokens: int      # Tokens consumed by the system prompt
    max_input_tokens: int   # Max user-text tokens (with MIN_OUTPUT_TOKENS reserved)
    min_output_tokens: int  # Minimum guaranteed output tokens (256)
```

#### Example: Custom Chunking

```python
budget = self.local_ai.get_support_model_token_budget("You are a summarizer.")
if not budget:
    return "Local AI not available."

# budget.max_input_tokens tells you how much text fits per call
chunk_size = budget.max_input_tokens
for chunk in split_text(document, chunk_size):
    result = await self.local_ai.support(chunk, "You are a summarizer.")
    # ... process result
```

> **Tip:** If you just want to summarize large text, use `summarize()` instead — it handles all of this automatically.

### Complete API Reference

```text
self.local_ai
│
├── Properties
│   ├── .available          → bool    # Support model ready?
│   ├── .embed_available    → bool    # Embedding model ready?
│   └── .memory_available   → bool    # Persistent memory ready?
│
├── Support Model
│   ├── .support(text, system_prompt)             → SupportResponse | None
│   ├── .support_sync(text, system_prompt)        → SupportResponse | None
│   ├── .summarize(text, instruction)             → SupportResponse | None
│   └── .summarize_sync(text, instruction)        → SupportResponse | None
│
├── Embeddings
│   ├── .embed(texts)                             → list[list[float]] | None
│   └── .embed_sync(texts)                        → list[list[float]] | None
│
├── Memory
│   ├── .remember_fact(content, entry_type)       → int | None
│   ├── .remember_fact_sync(content, entry_type)  → int | None
│   ├── .recall_memory(query, limit, entry_type)  → list[MemorySearchResult]
│   ├── .recall_memory_sync(query, limit, entry_type) → list[MemorySearchResult]
│   ├── .memory_context(query, max_tokens)        → str
│   ├── .memory_context_sync(query, max_tokens)   → str
│   ├── .update_memory(entry_id, new_content)     → bool
│   ├── .update_memory_sync(entry_id, new_content) → bool
│   ├── .forget_memory_by_id(entry_id)            → bool
│   ├── .forget_memory_by_id_sync(entry_id)       → bool
│   ├── .memory_forget(query)                     → bool
│   └── .memory_forget_sync(query)                → bool
│
└── Advanced
    └── .get_support_model_token_budget(system_prompt) → TokenBudget | None
```

**Return type conventions:**

| Return type       | On failure            |
| ----------------- | --------------------- |
| `SupportResponse` | `None` (error logged) |
| `list[...]`       | Empty list `[]`       |
| `str`             | Empty string `""`     |
| `bool`            | `False`               |
| `int` (entry ID)  | `None`                |
| `TokenBudget`     | `None`                |

### Full Example: Game Stats Tracker

A complete skill that fetches player stats from an API, summarizes them with the local support model, and remembers key facts for future conversations.

```python
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool
from services.skill_local_ai import MemoryType

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class GameStatsTracker(Skill):
    """Tracks and remembers player game statistics."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.retrieve_custom_property_value("api_base_url", errors)
        return errors

    def _get_api_base_url(self) -> str:
        errors = []
        return self.retrieve_custom_property_value("api_base_url", errors)

    async def get_prompt(self) -> str | None:
        """Inject remembered player facts into every conversation."""
        if not self.local_ai.memory_available:
            return None

        context = await self.local_ai.memory_context("player stats and preferences")
        if context:
            return f"What you remember about this player:\n{context}"
        return None

    @tool(
        description="""Fetch and remember a player's current game statistics.

        WHEN TO USE:
        - User asks about their stats, rank, or performance
        - User wants to check their current standing
        - User mentions a player name and wants info about them""",
        wait_response=True,
    )
    async def fetch_player_stats(self, player_name: str) -> str:
        """
        Args:
            player_name: The in-game player name to look up.
        """
        if not self.local_ai.available:
            return "Local AI is not enabled. Enable it in Settings to use this feature."

        # 1. Fetch from API
        import aiohttp
        base_url = self._get_api_base_url()
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/players/{player_name}") as resp:
                if resp.status != 200:
                    return f"Could not find player '{player_name}'."
                raw = await resp.text()

        # 2. Summarize (handles large responses automatically)
        summary = await self.local_ai.summarize(
            text=raw,
            instruction="Extract: player rank, win/loss ratio, favorite loadout, "
                        "notable achievements. Be concise.",
        )
        if not summary or not summary.text:
            return "Failed to process the stats response."

        # 3. Remember for future conversations
        if self.local_ai.memory_available:
            await self.local_ai.remember_fact(
                f"{player_name}: {summary.text}"
            )

        return summary.text

    @tool(
        description="""Recall what you remember about a player.

        WHEN TO USE:
        - User asks "what do you remember about..."
        - User references a player you've looked up before
        - User wants historical stats comparison""",
    )
    async def recall_player_info(self, query: str) -> str:
        """
        Args:
            query: What to search for (e.g., "player rank", "combat stats").
        """
        if not self.local_ai.memory_available:
            return "Memory is not available. Enable Local AI and Persistent Memory in Settings."

        results = await self.local_ai.recall_memory(query, limit=5)
        if not results:
            return "No matching memories found."

        return "\n".join(
            f"- {r.content}" for r in results
        )

    @tool(
        description="""Forget stored information about a player.

        WHEN TO USE:
        - User explicitly asks to forget or delete player data
        - User wants to clear outdated information""",
    )
    async def forget_player_info(self, query: str) -> str:
        """
        Args:
            query: What to forget (e.g., "player stats for Marcus").
        """
        if not self.local_ai.memory_available:
            return "Memory is not available."

        deleted = await self.local_ai.memory_forget(query)
        return "Done, I've forgotten that." if deleted else "No matching memory found."
```

---

## Additional Resources

### Example Skills to Study

**Auto-Activated (Hook-Based, always on):**

- [audio_device_changer](audio_device_changer/) - Routes audio to specific output devices
- [thinking_sound](thinking_sound/) - Plays sound effects during AI processing
- [voice_changer](voice_changer/) - Real-time voice modification for TTS
- [radio_chatter](radio_chatter/) - Background ambient radio audio
- [hud](hud/) - Transparent HUD overlay for messages and panels
- [quick_commands](quick_commands/) - Frequently-used shortcut actions

**Tool-Based (Progressive Disclosure):**

- [image_generation](image_generation/) - DALL-E image generation
- [timer](timer/) - Timer and countdown management
- [vision_ai](vision_ai/) - Screen capture and image analysis
- [file_manager](file_manager/) - Local file and folder operations
- [spotify](spotify/) - Spotify music playback control
- [api_request](api_request/) - Make HTTP API requests
- [typing_assistant](typing_assistant/) - Text input and typing automation
- [control_windows](control_windows/) - Window management and control
- [auto_screenshot](auto_screenshot/) - Automatic screenshot capture on conversation events

**Game Integrations:**

- [msfs2020_control](msfs2020_control/) - Microsoft Flight Simulator 2020 controls
- [uexcorp](uexcorp/) - Star Citizen trading data via UEX Corp
- [ats_telemetry](ats_telemetry/) - American/Euro Truck Simulator telemetry (auto-activated)

### Key APIs

**Wingman Access:**

```python
self.wingman.config               # Wingman configuration
self.wingman.name                 # Wingman name
self.wingman.generate_image()     # Generate image
self.wingman.audio_player         # Audio player instance
```

**Settings:**

```python
self.settings.debug_mode          # Is debug mode enabled?
self.settings.audio.output        # Output device config
```

**Utilities:**

```python
self.printr.print()               # Log to console
await self.printr.print_async()   # Async logging
self.get_generated_files_dir()    # Get persistent storage dir
```

**Configuration & Secrets:**

```python
self.retrieve_custom_property_value(property_id, errors)  # Get config value (just-in-time!)
await self.retrieve_secret(secret_name, errors, hint)      # Get secret from SecretKeeper
self.secret_keeper.retrieve()                              # Direct SecretKeeper access
```

### Best Practices

1. **Never cache config values** - retrieve them just-in-time so UI changes take effect immediately
2. **Always implement `unload()`** - clean up resources to prevent memory leaks
3. **Use type hints** - they auto-generate tool schemas and improve code quality
4. **Write clear tool descriptions** - include "WHEN TO USE" guidance for the AI
5. **Handle errors gracefully** - validate in `validate()`, don't crash at runtime
6. **Test in both modes** - development (source) and release (custom_skills)
7. **Keep dependencies minimal** - large dependencies make distribution difficult
8. **Document your skill** - help users understand how to configure and use it

---

## Getting Help

- **Discord**: Join the [Wingman AI Discord](https://www.shipbit.de/discord) for community support
- **GitHub**: Check existing skills for examples and patterns
- **Base Class**: Read [skill_base.py](skill_base.py) for complete API documentation

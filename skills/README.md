# Wingman AI Skills Developer Documentation

This guide explains how skills work in Wingman AI and how to create your own custom skills.

> Migrating an older skill? See [MIGRATING-TO-V3.md](MIGRATING-TO-V3.md).

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
  - [Command Actions](#command-actions)
- [Skill Structure](#skill-structure)
  - [Required Files](#required-files)
  - [default_config.yaml - Skill Metadata](#default_configyaml---skill-metadata)
  - [Custom Properties — Available Types](#custom-properties--available-types)
  - [Accessing Custom Properties](#accessing-custom-properties-in-your-skill)
- [Creating a Skill](#creating-a-skill)
- [Bundling Dependencies](#bundling-dependencies)
- [Skill Directory Structure](#skill-directory-structure)
- [AI Agent Bootstrap Checklist](#ai-agent-bootstrap-checklist)
- [The `self.wingman` facade API](#the-selfwingman-facade-api)
  - [Dialogs in the client](#selfwingmanui--show-something-in-the-client)
  - [The HUD overlay](#selfwingmanhud--the-hud-overlay)
  - [Screenshots](#selfwingmanscreen--screenshots-on-every-os)
  - [Star Citizen's Game.log](#selfwingmansc_gamelog--star-citizens-gamelog-live)
  - [Star Citizen's game folder](#selfwingmanstar_citizen--where-star-citizen-is-installed)
  - [Calling other skills & MCP servers](#calling-other-skills--mcp-servers)
  - [Threads and event loops](#threads-and-event-loops)
- [Local AI API](#local-ai-api-selfwingmanlocal_ai)
  - [Overview](#overview)
  - [Checking Availability](#checking-availability)
  - [The Local Model](#the-local-model)
  - [Summarizing Large Text](#summarizing-large-text)
  - [Embeddings](#embeddings)
  - [Persistent Memory](#persistent-memory)
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
- **Linux**: Follow [Developing on Linux](../docs/develop-linux.md)

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

The AI only sees the tools the user left switched on for that Wingman.

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
    tags: list[str] = field(default_factory=list)            # Categorical tags like ['Utility', 'Image']
    tool_names: list[str] = field(default_factory=list)      # Names of tools this skill provides
    tool_summaries: list[str] = field(default_factory=list)  # One-line descriptions of each tool
    is_auto_activated: bool = False    # Always active, hidden from progressive disclosure
    discovery_keywords: str = ""       # Optional keywords to enhance discovery
```

Manifests are built automatically from your `default_config.yaml` and `@tool` decorators — you don't need to construct them manually. The `description`, `tags`, and `discovery_keywords` fields come from your config; `tool_names` and `tool_summaries` are extracted from your decorated tools at registration time. Tools the user switched off for a Wingman are left out, and `discovery_keywords` is English only.

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

Keywords are **optional but recommended** for any non-auto-activated skill. Write them in English only; 5-10 keywords are usually enough. They enhance semantic matching by listing synonyms and variations of how users might request your skill's functionality.

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
    """Called once, when the skill is first activated (lazy). Set up resources here."""
    pass

async def update_config(self, new_config: SkillConfig) -> None:
    """Called when the user changes the skill's custom properties at runtime."""
    pass

async def secret_changed(self, secrets: dict) -> None:
    """Called when a secret is changed."""
    pass

async def get_prompt(self) -> str | None:
    """Extra system prompt text for this skill. Returns config.prompt by default."""
    return await super().get_prompt()

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
        self._sub = None

    async def prepare(self) -> None:
        await super().prepare()
        # Subscribe to audio events here, not in __init__ — keep the returned Subscription
        self._sub = self.wingman.audio.on_playback_finished(self.playback_finished)

    async def on_play_to_user(self, text: str, sound_config: SoundConfig) -> str:
        """Automatically change audio device before TTS playback."""
        audio_device = self.retrieve_custom_property_value("audio_changer_device", [])
        if audio_device:
            await self._change_audio_device(audio_device)
        return text

    async def playback_finished(self, _):
        """Reset audio device after playback."""
        await self.reset_audio_device()

    async def unload(self) -> None:
        await super().unload()
        if self._sub:
            self._sub.unsubscribe()  # detach the callback
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
        image = await self.wingman.ai.generate_image(prompt)
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
- A tool may return `(result, instant_response)`: `result` goes to the model, `instant_response` is spoken right away and ends the turn. `(result, ".")` ends the turn without a word, for a tool that handed the conversation to someone else (see `conversation.take_over`).

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

### Command Actions

`@command_action` makes a skill method available in the user's command editor, so a command can call it. It is separate from `@tool`; a method can have both.

```python
from skills.skill_base import Skill, command_action

class MySkill(Skill):
    @command_action(label="Say hello", respond="speak")
    def say_hello(self, name: str) -> str:
        return f"Hello {name}"
```

- Signature: `@command_action(label=None, description=None, respond="ai")`
- Parameters must be `str`, `int`, `float`, `bool` or `Literal[...]`
- `respond="ai"`: the returned string goes to the AI, which voices it
- `respond="speak"`: the returned string is spoken as is and also given to the AI
- Returning `None` gives the plain "OK" acknowledgment
- A command's static `responses` are its fixed acknowledgment. A `respond="speak"` result replaces them: the Wingman never says both

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
    from wingmen.wingman_context import WingmanContext


class YourSkillName(Skill):
    """Brief description of what your skill does."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
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
        """Called once, when the skill is first activated (lazy). Set up resources."""
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
api_version: 3 # REQUIRED for v3 — skills without it are treated as legacy and won't load
name: YourSkillName # Class name (must match main.py)
display_name: Your Skill Name # Human-readable name (shown in UI)
author: Your Name # Your name or organization

tags: # Categories for filtering - use standard categories
  - Utility
  - Internet

auto_activate: false # Auto-enable for all Wingmen? (see Auto-Activation section)

version: 1.0.0 # Your skill's own release, shown in error reports. Bump it when you ship.

# Only if the skill uses OS-specific modules: windows, darwin (macOS), linux.
# On other systems the skill is not offered. Leave it out otherwise.
platforms:
  - windows

# Whether the skill is switched on as discoverable when a new Wingman is
# created. Defaults to true if omitted. Set to false for specialized skills;
# users can still enable them per Wingman.
discoverable_by_default: true

# Core services that must be switched on in the settings. The client greys
# the skill out and tells the user which setting to turn on first.
# hud_server = the HUD (Windows, macOS, Linux with X11), sc_gamelog = the Star Citizen log.
# Leave it out when your skill needs neither.
requires:
  - sc_gamelog

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
>     api_key = await self.wingman.secrets.retrieve(
>         "your_service_api_key",
>         errors,
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

#### `range_slider` - Two-Handle Range Slider

Slider with a lower and an upper handle. The value is a list `[low, high]`. `options` hold `min`, `max` and `step`, as for `slider`.

```yaml
custom_properties:
  - id: interval_range
    name: Interval (sec)
    value: [60, 600]
    required: true
    property_type: range_slider
    options:
      - label: 'min'
        value: 60
      - label: 'max'
        value: 600
      - label: 'step'
        value: 10
```

**Use for:** Min/max pairs like intervals or counts. Read it as a `list` in the skill.

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

#### `directory` and `file` - Folder and File Picker

A text field with a button that opens the system's folder or file dialog. The
value is the full path as a string, so the skill reads it like a `string`.
Use one of these for every path, so the user never has to copy a path out of
Explorer or Finder.

```yaml
custom_properties:
  - id: install_directory
    name: Install Directory
    hint: Where the game is installed.
    value: C:\Program Files (x86)\Steam\steamapps\common\American Truck Simulator
    required: false
    property_type: directory

  - id: profile_file
    name: Profile
    hint: The profile file to read.
    value: ""
    required: false
    property_type: file
```

**Use for:** Install folders, output folders, files to read. For Star Citizen's
folder use `self.wingman.star_citizen` instead: the user sets it once for every
skill.

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
    provider="openai",  # a TtsProvider, see api/enums.py
    voice="alloy"       # voice ID/name for that provider
)
```

`subprovider` is optional. `voice` is a string for most providers. For ElevenLabs, XVASynth and Hume it is a config object (`ElevenlabsVoiceConfig`, `XVASynthVoiceConfig`, `HumeVoiceConfig`).

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

   # Linux:
   cp -r skills/your_skill_name ~/.local/share/WingmanAI/custom_skills/
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

Wingman AI adds the skill's packages to `sys.path` before loading it. Where they come from depends on how the skill is run:

- **Run from source (and bundled skills):** `venv/lib/python3.11/site-packages` (Windows: `venv\Lib\site-packages`) inside the skill folder. On macOS and Linux create the venv with Python 3.11: the path contains the version, other versions are not picked up. On Windows the path has no version.
- **Installed app (custom skills):** the `dependencies/` folder inside the skill folder.

For custom skills, `module_manager.py` does this:

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

**3. Implement and test your skill** (when running from source, Wingman adds the venv's `site-packages` automatically; Python 3.11 on macOS and Linux)

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

# Linux:
cp -r skills/your_skill_name ~/.local/share/WingmanAI/custom_skills/
rm -rf ~/.local/share/WingmanAI/custom_skills/your_skill_name/venv
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
   - Linux: `~/.local/share/WingmanAI/custom_skills/`

Only the skill's settings entry is overridden by a later location. The Python code comes from the first place that has the folder: source tree, then the bundled skills, then `custom_skills`. A custom skill therefore needs its own folder name; it does not replace the code of a bundled skill with the same name. The old community skills `hud`, `sc_log_reader`, `sc_log_reader_2` and `sc_accountant` are ignored because Core replaced them.

In dev mode, folders in `./skills/` that git does not track show up as local dev skills (the client cannot uninstall them).

### Source vs Working Directory

**Source directory (`skills/` in repo):**

- Used when running Wingman AI from source for development
- Changes here are immediately reflected when you restart
- Perfect for iterating on your skill

**Custom skills directory (APPDATA):**

- Used by the installed/release version of Wingman AI
- **NOT versioned** - persists across Wingman AI updates
- Users install skills here
- Give a custom skill its own folder name, it does not replace a bundled skill with the same name

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
        # Linux: ~/.local/share/WingmanAI/generated_files/YourSkillName
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
  - [ ] `api_version: 3` is set (without it the skill is treated as legacy and does not load)
  - [ ] `version` is set
  - [ ] `platforms` is set if the skill is not cross-platform
  - [ ] `requires` is set if the skill needs the HUD or the Star Citizen log
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
- [ ] Every `on(...)` / `on_playback_*` / `sc_gamelog.on` subscription is unsubscribed in `unload()`
- [ ] No work at import time, no `print()`
- [ ] Imports only from the [Allowed imports](AGENTS.md#allowed-imports) table
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

## The `self.wingman` facade API

In v3, a skill talks to the runtime **only** through `self.wingman` — a controlled facade
grouped into feature namespaces. `self.` is *your skill* (its identity, config, storage,
decorators, lifecycle hooks); `self.wingman` is *the runtime* (everything about the
wingman/app). No capability lives on both. There is no raw passthrough to the underlying
Wingman.

> Porting an older skill from the pre-v3 surface (`self.llm_call`, `self.wingman.audio_player`,
> `self.local_ai`, `self.retrieve_secret`, the registries …)? See
> [MIGRATING-TO-V3.md](MIGRATING-TO-V3.md) for the full old → new mapping.

The reference below lists every member, one line each. Gotchas (cap, interrupt, read-only,
`ToolResult`) are called out inline.

### Top level — `self.wingman`

| Member | Description |
| --- | --- |
| `.name` | This wingman's name (`str`). |
| `.avatar_path` | **Read-only** local file path to this wingman's avatar image (PNG, `str`). Falls back to the default Wingman AI avatar if the user hasn't set a custom one; `None` if unavailable. |
| `.config` | **Read-only** live view of the wingman config. Reads pass through to live values; any write raises `FacadeError`. Change things through a capability (`tts.set_voice`, `commands.*`, `audio.set_output_device`). |
| `.language` | The language the user speaks, read fresh on every access. `.name` is the English name for prompts (`"German"`, `"Dutch"`), `.code` the ISO 639 code (`"de"`; `None` for an other language that has none), `.is_other` is True for a language beyond the seven Wingman supports end to end. Put `.name` into every `ai.generate` / `local_ai` prompt whose output the user hears or reads: those calls do not get the Wingman's system prompt, so nothing else tells the model the language. |
| `.settings` | **Read-only** view of app settings, with `.output_device` / `.input_device` shortcuts for `settings.audio.output` / `.input`. Writing raises `FacadeError`; change devices via `audio.set_output_device(...)`. |
| `.run_in_thread(fn, *args)` | Start `fn` in its own thread and return at once (args spread **positionally**). If `fn` is a coroutine function it's run in a fresh event loop. For a background loop; to wait for one blocking call inside an `async def`, use `await asyncio.to_thread(fn, *args)`. |

### `self.wingman.ai` — main (cloud) model

Single-turn side-calls on the user's main model. Results are NOT added to the conversation.

| Member | Description |
| --- | --- |
| `await .generate(prompt="", *, system=None, data=None, image=None, messages=None, auto_shorten=False)` | Single-turn generation. Returns the response **`str`** (`""` if empty, never `None`). **Capped:** combined input is limited like a tool response (32,000 tokens, or a quarter of a smaller main model's window) — over the cap raises `FacadeError` (or truncates the prompt/data path if `auto_shorten=True`). Pass `messages=` (a prebuilt OpenAI-style list) to send your own turns directly — then `prompt`/`system`/`data`/`image` are ignored and it can't auto-shorten. |
| `await .sees_images()` | `False` when the main model is known not to take images (check before `generate(image=...)`); `True` for a model Wingman has no metadata for. |
| `await .converse(user_message)` | Conversation-aware reply using the wingman's system prompt + live history, subject to normal condensation. Appends both turns to the conversation. |
| `await .summarize(text, *, system=None)` | Summarize via the main **cloud** model (capped like `generate`). For bulk/cheap work prefer `local_ai.summarize`. |
| `await .generate_image(prompt, *, aspect="square", reference_images=None)` | Generate an image; returns it as data URL or URL (`str`, `""` on failure). `aspect`: `square`, `portrait` or `landscape`. `reference_images`: up to 4 data URLs the model builds on ("the same character, but …"); shrink them first with `services.image_generation.reference_data_url`. |
| `.recent_user_images()` | The images the user attached to their most recent message that had any, as data URLs (`tuple`, empty if none). |

### `self.wingman.local_ai` — free local model

Runs on the user's machine. Returns `""` when the local model is unavailable — check `.available`.

| Member | Description |
| --- | --- |
| `.available` | `bool` — local model loaded and ready. |
| `await .generate(text, *, system="", preset=None, temperature=None, top_p=None, top_k=None, reasoning=None)` | Single-turn generation on the support model → `str`. Pick a `SamplingPreset` (`PRECISE` for extraction and yes/no, `CREATIVE` for in-character lines). `reasoning=True` makes it think first: better, slower, only for background work. |
| `.generate_sync(...)` | Synchronous variant of `generate`. |
| `await .summarize(text, *, instruction="", preset=None, temperature=None, top_p=None, reasoning=None)` | Summarization → `str`; chunks large input automatically. `.summarize_sync(...)` for the sync variant. |
| `await .embed(texts)` | Vector embeddings for a list of strings. (`.embed_sync(...)` for the sync variant.) |

### `self.wingman.tts` — speech

| Member | Description |
| --- | --- |
| `.voice` | The voice configured on the current provider (read). |
| `await .voices()` | All voices on the current provider (best-effort; `[]` if not cheaply enumerable). |
| `await .missing_voices(voices)` | The voices in the list the current provider doesn't have, e.g. a Pocket TTS voice whose file was deleted. Only Pocket TTS is checked; other providers return `[]`. |
| `await .set_voice(voice, errors=None)` | Set the voice on the **current** provider (no provider switch) and rebuild TTS so it takes effect. Refuses a voice from `missing_voices`. Returns a human-readable result string. |
| `await .speak(text, *, interrupt=True, sound_config=None, priority=None)` | Say text in the wingman's voice; returns whether it was spoken. `interrupt=True` (default) cuts off current playback; `interrupt=False` waits for it. `interrupt` is **keyword-only** and inverted from the old `no_interrupt`. Lines said on the skill's own initiative pass a `priority` (`SpeechPriority` from `api.enums`). The order is answers, then events, then background: `EVENT` (a game event, a timer) waits until the user and every answer are done, also when one starts while the line is synthesized, and talks over background audio. `BACKGROUND` (radio chatter) never talks over anything and never waits: it is dropped when it can't be said right away, also while another background line plays. To say several background lines in a row, wait until `audio.is_playing` and `conversation.user_busy` are False before each one. A `priority` overrides `interrupt`. |

### `self.wingman.audio` — playback & devices

| Member | Description |
| --- | --- |
| `.is_playing` | `bool` — true while the wingman is playing TTS/audio. |
| `.is_playing_at_least(priority)` | `bool` — something at least as important as `priority` (`SpeechPriority`) plays. Check it with `EVENT` before an event line, so it waits for answers but not for radio chatter. |
| `await .play(audio_config, *, volume=1.0)` | Start playback of a skill-owned audio file. |
| `await .stop(audio_config, *, fade_out=0.5)` | Stop playback (optionally fading out). |
| `.on_playback_started(cb)` → `Subscription` | Observe playback start. Keep the returned `Subscription` and call `.unsubscribe()` in `unload()`. |
| `.on_playback_finished(cb)` → `Subscription` | Observe playback finish (same `Subscription` contract). |
| `.output_device` / `.input_device` | Currently selected audio device settings (read-only). |
| `await .set_output_device(device)` / `await .set_input_device(device)` | Switch one device and re-route playback; the other side stays as it is. `device` is a sounddevice index, a value read from `.output_device` / `.input_device` earlier (to switch back), or `None` for the system default. Returns `False` if unavailable. |
| `.mic_status` | The current `MicStatus` (listening, recording, playing, ...), or `None` before Core published one. |
| `.on_mic_status_changed(cb)` → `Subscription` | `cb(status)` on every mic / voice-activation change. Unsubscribe in `unload()`. |

### `self.wingman.stt` — speech to text

Which provider transcribes is a global setting. A skill may add words the transcript is corrected against.

| Member | Description |
| --- | --- |
| `.hotwords` | The hotwords this Wingman added (`list[str]`). |
| `.add_hotwords(words)` / `.remove_hotwords(words)` | Add or remove names (ships, places, people) for this run. Never written to a file. Returns how many changed. |
| `.remember_spelling(correct, heard=None)` | Put a spelling into the user's vocabulary in Settings, for good and for every provider. With `heard`, exactly that form is replaced. The user sees a line in the chat for every new entry, since it changes every transcript. Only call it when the user asked for the spelling. Returns `bool` (`False` if it was already there). |
| `.forget_spelling(word)` | Remove it again. Returns the number of entries removed. |

### `self.wingman.system_one` — typed decisions

A fast, cheap model that picks from options you give it instead of writing text: which of these
does the user mean, how urgent is this, yes or no. About 300 ms, a fraction of the cost of
`ai.generate`. `.available` is `False` when the user switched it off or the plan lacks it; check
it and fall back to `local_ai` or a rule. The entry point is `await .decide(state, questions)`
(`.decide_sync(...)` for threads).

Use it whenever the skill needs to **pick, rate or judge** rather than write.
It cannot answer outside the options you give it, so there is nothing to parse
and nothing to validate.

This is a thin wrapper around [TypeSafe's Jev](https://docs.typesafe.ai) and
keeps their names, so their docs and examples read straight across:

| TypeSafe SDK | here |
|---|---|
| `Choice(instructions, criteria)` | `so.choice(instructions, criteria)` |
| `Score(instructions, criteria)` | `so.score(instructions, criteria)` |
| `Noul(instructions)` | `so.noul(instructions)` |
| `client.system_one(state, questions)` | `await so.decide(state, questions)` |
| `answers[k].choice` / `.confidence` | `answers.choice(k)` / `.confidence(k)` |
| `answers[k].score` / `.probabilities` | `answers.score(k)` / `.probabilities(k)` |
| `answers[k].noul` | `answers.noul(k)` |

Three things are ours, each filling a gap: `so.describe()` builds their
structured description object, `answers.level()` turns a score back into its
label, and `answers.yes_no()` applies a threshold to a noul.

```python
so = self.wingman.system_one
if so.available:
    answers = await so.decide(
        state={"transcript": text, "cargo": cargo},
        questions={
            "intent": so.choice("What does the pilot want?", {
                "sell": so.describe("offload cargo", not_for="buying more"),
                "buy":  "acquire cargo",
                "none": "nothing about cargo",          # always give it an out
            }),
            "urgent": so.noul("Does this need doing right now?"),
            "risk":   so.score("How risky is this route?", ["safe", "watchful", "dangerous"]),
        },
    )
    answers.choice("intent", min_confidence=0.8)   # "sell", or None if unsure
    answers.noul("urgent")                         # 0.94 — a probability
    answers.yes_no("urgent")                       # True — thresholded at 0.5
    answers.level("risk")                          # "dangerous"
    answers.score("risk")                          # 1.99 — the position, continuous
    answers.probabilities("risk")                  # {"safe": 0.0, ... } keyed by label
```

Four rules that come out of measuring it:

- **Ask everything in one `decide()`.** Questions are evaluated in parallel:
  eight cost 13 ms and 28% more tokens than one. Three calls for three
  questions is three times the latency for nothing.
- **Describe options that could be confused.** Descriptions cut wrong answers
  from 16 to 3 out of 152 on Wingman's own command routing, at no cost in
  latency. `not_for=` separates two neighbours better than a longer
  description of either. A bare option name is fine when nothing is close.
- **Give a choice a "none of these" option** whenever nothing applying is an
  honest answer. Without one the probability has nowhere to go but onto the
  real options.
- **`min_confidence` separates unsure from sure, not two overlapping options.**
  If the wrong neighbour keeps winning at high confidence, the fix is a better
  description, not a higher threshold.

The other readers on the answers:

| Member | Description |
| --- | --- |
| `.ok` / `.error` | Whether an answer came back, and why not (`"system one is off"`). `error` is for the log: branch on the value being `None` instead. |
| `.seconds` | How long the call took. |
| `.keys()` | The questions that were answered. |
| `.levels(k)` | The level labels of a score, lowest first. |
| `.raw(k=None)` | The answers exactly as the model sent them, for anything the readers above don't cover. |

Always handle `available` being False — the user can switch System One off in
Settings, and a plan may not include it. Every reader returns `None`/`{}` in
that case, so the skill silently takes the None branch unless you check.

### `self.wingman.commands` — user commands

| Member | Description |
| --- | --- |
| `.get(name)` | Live `CommandConfig` with this name, or `None`. |
| `.all()` | All configured commands (live objects, read-only tuple). |
| `.add(command, *, category=None)` | Add a command (optionally into a category). Call `save()` to persist. |
| `.remove(name)` | Remove a command by name. Call `save()`. |
| `.add_category(name)` → `CommandCategory` | Create/return a category (idempotent by name). |
| `.update_category(category)` / `.delete_category(id_or_name)` | Rename / remove a category. |
| `.categories()` | All categories as `CommandCategory` objects. |
| `.register_function(func, *, label=None, description=None, respond="ai", parameters=None)` | Register a bound skill method as a runtime command function (dynamic `@command_action`). Returns the function name. |
| `.unregister_function(name)` | Remove a previously registered runtime command function. |
| `.add_skill_command(name, func, *, category=None, instant_phrases=None, respond="ai")` | One call: register `func`, build a command bound to it, categorize it. Call `save()`. |
| `await .save()` | Persist the commands section to disk. Returns `True` on success. |

### `self.wingman.tools` — discover & invoke functions

Every callable function the wingman has: your `@tool`s, other active skills' tools, MCP tools, and commands.

| Member | Description |
| --- | --- |
| `.names()` | `set[str]` of all callable function names. |
| `.has(name)` | `bool` — is this function callable right now? |
| `.source(name)` | Human origin of a tool: the owning skill's name, or the MCP server's display name (`None` if unknown). It's a **name string**, not the skill/server object. |
| `.describe(name)` → `ToolDescriptor` | `name`, `source`, `description`, `parameters` (JSON-schema) — or `None`. |
| `.all()` | Tuple of `ToolDescriptor` for every callable function (with params). |
| `.icon(name)` | Path to the owning skill's `logo.png`, or `None` (MCP tools / no logo). For UIs that show a per-tool icon. |
| `.servers()` | Active MCP servers as dicts (`name`, `display_name`, `connected`, `tools`). |
| `await .invoke(name, arguments=None)` → `ToolResult` | Call a function by name. Returns a **`ToolResult`** (`.response`, `.instant_response`, `.skill`, `.label`) — not a 4-tuple. |

### `self.wingman.conversation` — the live conversation

| Member | Description |
| --- | --- |
| `.history()` | Shallow copy of the live history (`list[dict]`). Don't mutate individual messages. |
| `.summary` | The condenser's running summary (`str`). |
| `await .add_user(content)` | Append a user turn. |
| `await .add_assistant(content)` | Append an assistant turn. |
| `await .show(text, *, skill_name="")` | Show a line in the chat as said by this Wingman. Display only: pair it with `tts.speak` and `add_note` as needed. |
| `await .add_note(content)` | Put context into the history that is neither the user nor the Wingman talking, for lines your skill said on its own. Call it from `on_add_user_message`. Lines added with `add_assistant` instead come back appended to the Wingman's next answers. |
| `.user_busy` | `True` while the user holds a push-to-talk key, was just heard, or any wingman is answering. Check it before your skill speaks up on its own. |
| `await .summarize()` | Summarize the live conversation via the **free local** model (`""` if unavailable). |
| `await .reset()` | Reset the conversation history. |
| `.takeover` | Who has the conversation right now (`Takeover` with `.speaker`, `.active`, `.release()`), or `None`. |
| `.take_over(speaker, handler, *, idle_s=300)` → `Takeover` | Hand the conversation to `handler`: what the user says goes to `await handler(text)` instead of the model, and the Wingman says nothing. The handler answers in `speaker`'s name and returns `False` when the conversation is over. It also ends when the user addresses the Wingman by name, after `idle_s` without a word, on `release()` and on unload. Both sides land in the history as notes. |
| `.register_speaker(name, opener)` → `Subscription` | Make `name` addressable like a Wingman: a sentence starting with it goes to `await opener(name, text)`, matched by sound. The opener usually takes over and answers; `False` leaves the sentence to the model. Unsubscribe in `unload()`. |
| `await .said_by(speaker, text, *, skill_name="")` | Show a line said by someone the skill voices, under their name and in the chat's character style, and record it in the history. Speak it yourself with `tts.speak`. |

#### Voicing someone else

A skill that plays a character, an NPC at a counter or a caller on the radio, takes the
conversation over so the user talks to them directly, without the Wingman in between:

```python
async def prepare(self):
    self._tecia = self.wingman.conversation.register_speaker("Tecia", self._addressed)

async def _addressed(self, name: str, text: str) -> bool:
    self.wingman.conversation.take_over("Tecia Varga", self._turn, idle_s=300)
    return await self._turn(text)

async def _turn(self, text: str) -> bool:
    line = await self.wingman.ai.generate(messages=self._as_tecia(text))
    await self.wingman.conversation.said_by("Tecia Varga", line, skill_name=self.config.display_name)
    await self.wingman.tts.speak(line)          # in her voice: tts.set_voice around it
    return "[END]" not in line                  # False ends the conversation

async def unload(self):
    self._tecia.unsubscribe()
    if self.wingman.conversation.takeover:
        self.wingman.conversation.takeover.release()
```

A tool can start it too, returning `(result, ".")` so the Wingman stays silent. "Computer, ..."
always takes the conversation back, the same way the name picks a Wingman in voice activation.

### `self.wingman.memory` — local persistent memory

Free, runs locally. Returns `None`/empty when unavailable — check `.available`.

| Member | Description |
| --- | --- |
| `.available` | `bool` — persistent memory ready (needs local AI + config). |
| `await .remember(content, *, entry_type=MemoryType.FACT)` | Store a fact; auto-dedupes against similar entries. Returns the entry ID. |
| `await .track(content)` | Put something the user took on and has not finished (a mission, a plan) on the Open list. Returns the entry ID. Wingman 3.2.10 or later. |
| `await .close(entry, outcome="")` | Close the open entry `entry` describes; `outcome` becomes its text. Returns `bool`. Wingman 3.2.10 or later. |
| `await .recall(query, *, limit=5, entry_type=None)` | Semantic search; returns matches sorted by relevance. |
| `await .context(query, max_tokens=500)` | The whole MEMORY block (facts, open and finished entries, recent episodes), the text Core already puts in the system prompt. `query` and `max_tokens` are ignored. |
| `await .update(entry_id, new_content)` | Update an entry by ID (re-embeds). |
| `await .forget(query)` | Fuzzy delete: removes the closest semantic match. |
| `await .forget_by_id(entry_id)` | Deterministic delete by ID. |

### `self.wingman.secrets` — stored secrets

| Member | Description |
| --- | --- |
| `await .retrieve(name, errors=None)` | Fetch a stored secret (prompts the user if missing). |

### `self.wingman.skills` — loaded skills

| Member | Description |
| --- | --- |
| `.active()` | Tuple of `{name, display_name}` for every loaded skill. |
| `.has(name)` | `bool` — is a skill with this name loaded? (symmetric with `tools.has`). |

### `self.wingman.ui` — show something in the client

| Member | Description |
| --- | --- |
| `await .show_dialog(title, text, *, image=None, once=None)` | Open a dialog in the client. `text` is Markdown (sanitized, links open in the browser), `image` a data URL shown under it. With `once="MySkill.welcome"` it appears a single time ever and later calls return `False`. If no client is connected yet, it appears as soon as one is. |

### `self.wingman.hud` — the HUD overlay

Core's HUD server draws the overlay, on an OS the HUD supports (Windows,
macOS, Linux with X11) and only when the user switched it on in the settings. All Wingmen share two containers, the chat and
the info panel; where they are and how they look comes from the user's HUD
profile. Every call checks that the HUD runs and returns `False` when it does
not. The shared containers also follow the Wingman's own HUD switches.

| Member | Description |
| --- | --- |
| `.available` | `bool` — the HUD runs (switched on, on a supported OS). |
| `.chat_enabled` / `.info_enabled` | `bool` — the HUD runs and this Wingman uses the chat container / the info panel. |
| `.profile` | The HUD profile in use, read-only: `chat` and `info` are the containers' areas (`x1`, `y1`, `x2`, `y2` in pixels), `style` their look. `None` before a config is loaded. |
| `await .show_message(title, text, *, duration=10.0, color=None)` | A message in the shared chat container for `duration` seconds. Markdown; `color` is a hex accent. With the Wingman's name as title it shows its avatar. |
| `await .add_info(title, text="", *, color=None, duration=None)` | A panel on the shared info panel. The same title replaces it; `duration` removes it after that many seconds. |
| `await .remove_info(title)` | Take a panel off the info panel. |
| `await .show_progress(title, current, maximum=100, *, text="", color=None, auto_close=False)` | A progress bar on the info panel; the same title updates it. |
| `await .show_timer(title, seconds, *, text="", color=None, auto_close=True)` | A countdown on the info panel. |
| `.info_items()` | What the shared info panel shows now, oldest first: dicts with `title`, `text` and `added_by`. `[]` when the HUD is off. |
| `.group(name, element="persistent", **props)` | A group of the skill's own, e.g. a status icon in a corner (see below). |

Panel and message text is Markdown, with tables (`---:` aligns a column
right), task lists and three data blocks: a fenced ` ```bar ` (labelled
bars of segments, e.g. a cargo hold), ` ```steps ` (a route of done, current
and next stops) and ` ```stats ` (figures side by side). They follow the
user's HUD profile; their syntax is in `hud_server/README.md`, Data blocks.

The info panel belongs to every Wingman: only remove panels your skill put
there. Each panel remembers who added it; yours read as "added by the Your
Skill skill of Computer" to the Wingmen, which read the panel with their
`hud_read_info` tool.

Core already shows every line that goes into the conversation in the chat
container. Show a line yourself only when it does not go there, or it appears
twice (`chat_enabled` tells you whether Core shows it).

**A group of your own.** `self.wingman.hud.group("mic", anchor="top_right",
width=72)` returns a handle named after the Wingman plus `"mic"`, so two
Wingmen running your skill get one each. `props` are HUD server props:
`anchor`/`priority` to stack at a screen edge, or `layout_mode="manual"` with
`x`/`y` (and `align`) for a free spot; colours, `opacity`, `content_padding`...
Anything you leave out comes from the user's HUD profile. The handle has
`show_message`, `hide_message`, `append_message` (text added to the message
on screen, for streaming), `add_info`, `remove_info`, `show_progress`,
`show_timer`, `info_items()`, `clear()`, `set_loader(show)`, `hide()` and
`show()` (a hidden group keeps every update), `update(**props)` (windows
follow right away) and `delete()`. All handle methods are awaited, including `info_items()`; only
`self.wingman.hud.info_items()` is sync. The shared chat and info panel have no
`clear` or `hide`: they belong to every Wingman.
Core deletes the group when the skill unloads, and makes it again with its
props if the HUD server restarts. See `skills/mic_status`.

If your skill is pointless without the HUD, declare `requires: [hud_server]`
in its `default_config.yaml`. The client then keeps the skill off and tells the
user to switch the HUD on first. A skill that only uses the HUD as an extra
(like Star Citizen Events) leaves it out and relies on the `False` return.

### `self.wingman.screen` — screenshots on every OS

| Member | Description |
| --- | --- |
| `await .capture(display=1, region=None)` | A PIL image (RGB) of monitor `display` (1 = the first, 0 = all), or of `region` (`{"left", "top", "width", "height"}`). Raises `RuntimeError` with what the user has to do, e.g. allow Screen Recording on macOS. |
| `.wayland` | `bool` — a Wayland session: the desktop picks the monitor. |

Use it instead of capturing yourself (mss, PIL.ImageGrab): under Wayland a
skill's own capture only sees XWayland windows and gives black for the rest.
Core asks the desktop there: Spectacle on KDE, grim on Sway and Hyprland, the
screenshot portal elsewhere (the desktop may ask the user once). See
`skills/vision_ai` and `skills/auto_screenshot`.

### `self.wingman.clipboard` — the system clipboard

| Member | Description |
| --- | --- |
| `await .read()` | The clipboard's text, `""` when it holds none (an image, a file). Raises `RuntimeError` with what the user has to do, e.g. install xclip on Linux. |
| `await .write(text)` | Puts `text` on the clipboard, replacing what was there. |

Windows, macOS and Linux (wl-clipboard under Wayland, xclip or xsel under
X11); both calls run off the event loop. A game or another program may write
the clipboard at any time, so read it right when you need it. See
`skills/sc_position`, which reads a game's answer from it.

### `self.wingman.star_citizen` — where Star Citizen is installed

The StarCitizen folder that holds LIVE, PTU and the other environments. The
user sets it once, in the setup after the first start or in Settings, and every
skill that reads the game's files uses it. Do not ask for the folder in a
custom property of your own. Read-only.

| Member | Description |
| --- | --- |
| `.game_path` | `Path` of the folder as the user set it, `None` if empty. It may not exist. |
| `.found` | `bool` — the folder holds at least one environment. |
| `.environments` | `("LIVE", "PTU", ...)` — environment folders in it right now. |
| `.environment_path(environment="LIVE")` | `Path` to that environment's folder, `None` if it does not exist. |
| `.plays` | What the user answered to "Do you play Star Citizen?", `None` before they answered. |

```python
live = self.wingman.star_citizen.environment_path("LIVE")
if not live:
    return "Star Citizen was not found. Set the game folder in Settings > Star Citizen."
profiles = live / "user" / "client" / "0" / "Profiles" / "default"
```

### `self.wingman.sc_gamelog` — Star Citizen's Game.log, live

Core reads the Game.log of every Star Citizen environment (LIVE, PTU, ...) in
one background reader for all Wingmen and turns it into events: missions,
zones, locations, ships, injuries, rewards, trades. The user can switch the
reader off in the settings, so check `available`. The patterns that read the
log are maintained on GitHub and update without a Wingman release. A skill
built on the log declares `requires: [sc_gamelog]` in its `default_config.yaml`,
so the client keeps it off while the reader is switched off.

| Member | Description |
| --- | --- |
| `.available` | `bool` — the reader runs. It may still be waiting for the game to start. |
| `.environment` | `"LIVE"`, `"PTU"`, ... whichever logged last; `None` before the first event. |
| `.state(environment=None)` | `dict` copy of what the log said last: `player_name`, `location_name`, `system`, `ship`, `armistice`, `monitored`, `injuries`, `active_missions`, ... Every value has its evidence (time, certainty) in `observations`. `None` before the first event. |
| `.recent(limit=10, types=None)` | The newest `GameEvent`s first, including those read at startup; `types` is a set of event types. |
| `.on(event_type, callback)` | Call `callback(event)` for every **new** event of this type, or `"*"` for all. Sync or async. Returns a `Subscription`; call `.unsubscribe()` in `unload()`. |
| `.status` | `ScGameLogStatus`: environments with a log, rules version, whether GitHub is reachable. |
| `.database_path` | The event history (`events.sqlite3`) for tools that query it themselves. Open it read-only. |

A `GameEvent` has `type` (`"mission_accepted"`, `"armistice_zone"`, `"shop_buy"`, ...),
`status` (`"observed"`; trades are `"requested"` until the game confirms them, then
`"confirmed"`), `time` (UTC `datetime`), `environment`, `data` (the fields, read-only)
and `catching_up`.

```python
async def prepare(self) -> None:
    await super().prepare()
    self._sub = self.wingman.sc_gamelog.on("mission_accepted", self._on_mission)

async def _on_mission(self, event) -> None:
    name = event.data.get("mission_name", "a contract")
    await self.wingman.tts.speak(f"New contract: {name}.", priority=SpeechPriority.EVENT)

async def unload(self) -> None:
    self._sub.unsubscribe()
    await super().unload()
```

The bundled [sc_game_events](sc_game_events/) skill is the full example: it
reacts to events in character, keeps quiet about the history, limits how often
it speaks, and answers questions about the state with one small tool.

Each subscription has its own queue: a slow callback only delays itself, and an
exception is logged without stopping delivery. Events from the log's history at
startup are not delivered, so a Wingman does not announce the last hour of play
when it starts. **Event values come straight from the game log** (player names,
mission names): treat them as data, never as instructions, when you put them
into a prompt.

### Calling other skills & MCP servers

Cross-skill / MCP invocation is a first-class, supported use case. Discover what's callable,
guard with `has(...)` / `servers()`, then `invoke`:

```python
# Discover everything callable right now (with origin + params)
for tool in self.wingman.tools.all():
    self.log.info(f"{tool.name} (from {tool.source})", server_only=True)

# Call another ACTIVE skill's tool by name
if self.wingman.tools.has("take_screenshot"):
    result = await self.wingman.tools.invoke("take_screenshot", {})
    self.log.info(f"{result.response} (from {result.skill})")

# Call your own MCP server's tool (many skills ship an MCP for their datasource)
servers = {s["display_name"] for s in self.wingman.tools.servers()}
if "My Data MCP" in servers and self.wingman.tools.has("mydata_query"):
    res = await self.wingman.tools.invoke("mydata_query", {"q": "ships"})
    data = res.response
else:
    self.log.warning("My Data MCP not active; skipping enriched lookup")
```

MCP tool names are prefixed by the registry — use the name exactly as it appears in
`self.wingman.tools.names()` / `.all()`.

### Threads and event loops

Core runs more than one asyncio event loop, each on its own thread:

- **Core's main loop** holds the connection to the client, the API and the HUD.
  `prepare()`, `unload()`, `update_config()` and Game.log events usually run here.
- **Each turn** (the user says something, the Wingman answers) runs on a loop of
  its own. Your tools and hooks run on the loop of the turn that called them.
- **`self.wingman.run_in_thread(coro_fn)`** gives your coroutine a fresh loop on a
  fresh thread, closed when it returns.

The same skill instance is used from all of them. Everything on `self.wingman` and
`self.log` is safe to call from any loop or thread. For your own code:

1. **An asyncio object belongs to one loop.** `asyncio.Lock`, `Event`, `Queue`,
   `Task`, `aiohttp.ClientSession`, `httpx.AsyncClient` and websocket connections
   work only on the loop that created or first used them. Do not create one in
   `prepare()` and use it from a tool or a background thread. A lock one loop holds
   raises `RuntimeError: ... is bound to a different event loop` when another loop
   waits for it. Open network clients per call
   (`async with aiohttp.ClientSession() as session:`), or use a sync client like
   `requests` inside `await asyncio.to_thread(...)`.
2. **For a lock shared by tools, background loops and `prepare()`, use
   `threading.Lock` and take it in the worker thread.** Never `with lock:` directly
   in an `async def`: while it waits, the whole loop stands still.

   ```python
   import threading

   self._db_lock = threading.Lock()

   async def _db(self, fn, *args):
       return await asyncio.to_thread(self._locked, fn, *args)

   def _locked(self, fn, *args):
       with self._db_lock:
           return fn(*args)
   ```

3. **Never cancel a task or close a connection from another thread.** Not even in
   `unload()`. Stop a background loop with a flag or a run id it checks on each
   pass. If you must touch another loop, hand the work over:
   `loop.call_soon_threadsafe(task.cancel)` or
   `asyncio.run_coroutine_threadsafe(coro, loop)`. On Windows, a socket closed from
   the wrong thread can stop the loop that owns it, and with Core's main loop the
   whole Wingman stops answering.
4. **Background threads end on their own.** `run_in_thread` threads are daemon
   threads. Let them finish when your flag says so. Do not `join()` them without a
   timeout in `unload()`.

---

## Local AI API (`self.wingman.local_ai`)

Every skill can reach the support model through `self.wingman` — the small, cheap model
(`self.wingman.local_ai`), embeddings, and persistent memory (`self.wingman.memory`). The name
is historical: by default the support model runs in the Wingman cloud; users can also run it
on their own machine or their own llama.cpp server. Calls cost the user nothing either way.

### Overview

Users choose in Settings where the support model runs (cloud, local or their own server). Your skill doesn't need to worry about any of that — `self.wingman.local_ai` and `self.wingman.memory` handle everything internally.

**Key principles:**

- **Reached through `self.wingman`** — `self.wingman.local_ai` for the model/embeddings, `self.wingman.memory` for persistent memory
- **Safe by default** — methods handle errors internally, log them to the client, and return `""`/empty results. Skills never need `try/except` around these calls.
- **Both async and sync** — async is preferred; sync variants have a `_sync` suffix
- **Plain strings** — `generate`/`summarize` return a `str` (`""` when the local model is unavailable), not a response object
- **Stable contract** — the internal implementation may change across versions, but this API won't break

```python
# Quick taste — that's really all it takes:
text = await self.wingman.local_ai.generate("Summarize this text", system="You are a summarizer.")
if text:
    self.log.info(text, server_only=True)
```

### Checking Availability

Local AI is optional — users may not have it enabled or models may not be downloaded yet. Always check before using:

```python
@tool()
async def my_tool(self, query: str) -> str:
    if not self.wingman.local_ai.available:
        return "Local AI is not enabled. Please enable it in Settings."

    text = await self.wingman.local_ai.generate(query, system="Answer concisely.")
    return text or "Processing failed."
```

**Availability properties:**

```python
self.wingman.local_ai.available  # Local model is loaded and ready
self.wingman.memory.available    # Persistent memory is available (requires local AI + wingman config)
```

> **Tip:** `self.wingman.memory.available` implies the embedding model is loaded (memory needs embeddings). The local model (`local_ai.available`) loads separately.

### The Local Model

The local model is Wingman's support model: a small, cheap LLM for text processing tasks like extraction, classification, summarization, or reformatting. By default it runs in the Wingman cloud; users can also run it on their own machine (Qwen 3.5 4B) or on their own llama.cpp server. Your skill calls it the same way in every case.

```python
async def generate(text: str, *, system: str = "", preset=None,
                   temperature=None, top_p=None, top_k=None, reasoning=None) -> str
def generate_sync(text: str, *, system: str = "", ...) -> str
```

**Parameters:**

| Parameter | Type  | Description                                                    |
| --------- | ----- | -------------------------------------------------------------- |
| `text`    | `str` | The input text / user prompt                                   |
| `system`  | `str` | Instructions for the model. If empty, a default prompt is used |
| `preset`  | `SamplingPreset` | `PRECISE`, `BALANCED` or `CREATIVE` (from `services.skill_local_ai`). Pick one per call |
| `temperature`, `top_p`, `top_k` | `float`, `float`, `int` | Optional overrides of the preset |
| `reasoning` | `bool` | `True` lets the model think first. Only for background work |

**Returns** a plain `str` — the model's response, or `""` if local AI is unavailable or an error occurs (error is logged to the client automatically).

**Examples:**

```python
# Simple text processing
text = await self.wingman.local_ai.generate(
    user_message,
    system="Extract the player name and ship type from this message. Return as JSON.",
)
if text:
    data = json.loads(text)
```

> **Important:** When the model runs locally, its context window is small (user-configurable, default 4096 tokens). If your input is too large, the model silently loses data beyond its context limit. For potentially large inputs, use `summarize()` instead.

#### Prompt Writing Guidelines for Small Models

The support model is a small model with limited instruction-following ability, and your prompt has to work on the weakest variant a user may run. Prompts that work well with large models (GPT-4, Claude) will often fail here. Follow these rules when writing `system` strings:

- **Be direct and literal.** Use short, imperative sentences. Avoid nuance, hedging, or nested clauses.
- **Use labeled sections** (`Backstory:`, `Input:`, `Rules:`) instead of prose paragraphs. The model parses structured prompts more reliably.
- **Say "EXACT words"** when you want the model to reference source material. Without this, it will paraphrase loosely and hallucinate details (e.g., turning "gift ideas" into "gift cards").
- **Say "IN CHARACTER" explicitly** when the model must rephrase instructions in its persona's voice. Otherwise it will dump template text verbatim (e.g., outputting "The user talks to you by holding the home key" instead of weaving it into a natural sentence).
- **Constrain what it may NOT do.** Small models are prone to confabulation — add explicit "Do NOT add anything not in [source]" rules.
- **Keep prompts short.** Every token of system prompt reduces the budget available for input and output. Aim for under 200 tokens.
- **Name the language** when the user hears or reads the output: `f"Write in {self.wingman.language.name}."`. Put it last, right before the output starts — small models forget a language rule at the top of the prompt.

### Summarizing Large Text

When you have text that might exceed the model's context window (e.g., API responses, large documents), use `summarize()`. It automatically chunks the text, summarizes each chunk, and merges the results.

```python
async def summarize(text: str, *, instruction: str = "", preset=None,
                   temperature=None, top_p=None, reasoning=None) -> str
def summarize_sync(text: str, *, instruction: str = "", ...) -> str
```

**Parameters:**

| Parameter     | Type  | Description                                                                 |
| ------------- | ----- | --------------------------------------------------------------------------- |
| `text`        | `str` | The text to summarize. Can be arbitrarily large                             |
| `instruction` | `str` | Optional focus instruction (e.g., "Focus on combat stats and ship loadout") |
| `preset`, `temperature`, `top_p`, `reasoning` | | Same as for `generate()` |

If the text fits in the context window, it's processed in a single call (same as `generate()`). If it's too large, chunking and merging happen automatically. Returns a plain `str` (`""` if unavailable).

**Common pattern — API call → summarize → remember:**

```python
@tool(wait_response=True)
async def fetch_player_stats(self, player_name: str) -> str:
    """Fetch and remember player statistics."""
    if not self.wingman.local_ai.available:
        return "Local AI is not enabled."

    # 1. Fetch (could be huge)
    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"https://api.game.com/stats/{player_name}")
        raw = await resp.text()

    # 2. Summarize — handles any size automatically
    summary = await self.wingman.local_ai.summarize(
        raw,
        instruction="Extract key stats: rank, wins, losses, favorite loadout.",
    )
    if not summary:
        return "Failed to process stats."

    # 3. Remember for future conversations
    if self.wingman.memory.available:
        await self.wingman.memory.remember(f"{player_name}'s stats: {summary}")

    return summary
```

**When to use `generate()` vs `summarize()`:**

| Use `generate()` when                        | Use `summarize()` when                     |
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
embeddings = await self.wingman.local_ai.embed([
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

Persistent memory lets your skill remember facts about the user across conversations, through the `self.wingman.memory` namespace. Memories are stored locally in a SQLite database with vector embeddings for semantic search.

#### Remembering Facts

```python
async def remember(content: str, *, entry_type=MemoryType.FACT) -> int | None
```

**Automatic deduplication:** When you save a fact that's semantically similar (>90%) to an existing one, it **updates** the existing entry instead of creating a duplicate. This means you can safely call `remember()` repeatedly without worrying about duplicates.

```python
# First call: creates a new entry
await self.wingman.memory.remember("Player rank: Gold 3")

# Later: player ranks up — this UPDATES the existing entry (>90% similar)
await self.wingman.memory.remember("Player rank: Platinum 1")
```

**Returns** the entry ID (`int`) on success, or `None` on failure.

#### Open entries

Something the user took on and has not finished goes on the Open list: the wingman sees it in every session until it is closed, then for two weeks as finished. The chat model does this itself with its memory tools; a skill that learns of it another way (a game log, an API) does it with `track()` and `close()`.

```python
await self.wingman.memory.track("Accepted the mission 'Medical Supplies to Lorville'")
# later, when the game reports it done
await self.wingman.memory.close("Medical Supplies to Lorville", "Delivered the medical supplies to Lorville.")
```

#### Recalling Memories

```python
async def recall(query: str, *, limit: int = 5, entry_type=None) -> list[MemorySearchResult]
```

Search memories by semantic similarity. Returns results sorted by relevance.

```python
@dataclass(frozen=True)
class MemorySearchResult:
    id: int                     # Entry ID (for update/delete)
    content: str                # The memory text
    entry_type: str             # "fact", "open", "done" or "episode" ("session_summary" in older databases)
    source_wingman: str | None  # Which wingman stored this
    created_at: float           # Unix timestamp
```

**Always returns a list** — empty on failure or no matches. Safe to iterate without None checks.

```python
# Search for relevant memories
results = await self.wingman.memory.recall("player's ship and loadout", limit=3)
for memory in results:
    print(f"[{memory.entry_type}] {memory.content}")
```

#### Getting Memory Context for Prompts

```python
async def context(query: str, max_tokens: int = 500) -> str
```

Returns the whole MEMORY block: every fact, the open and recently finished entries, and the recent episodes. It is the same text Core already puts in the system prompt, so you rarely need it. `query` and `max_tokens` are accepted for older skills and ignored. Use `recall()` for a targeted lookup.

**Always returns a string** — empty on failure. Safe to concatenate directly. Do not add it to your own `get_prompt()`: the Wingman would see the memories twice.

#### Updating and Deleting Memories

```python
# Update a specific memory (re-embeds automatically)
async def update(entry_id: int, new_content: str) -> bool

# Delete by ID (deterministic)
async def forget_by_id(entry_id: int) -> bool

# Delete by semantic search (fuzzy — finds closest match)
async def forget(query: str) -> bool
```

**Two deletion strategies:**

```python
# Strategy 1: Track the ID from remember() — deterministic
entry_id = await self.wingman.memory.remember("Player owns a Cutlass Black")
# ... later ...
await self.wingman.memory.forget_by_id(entry_id)  # Exactly this entry

# Strategy 2: Fuzzy search — deletes the closest semantic match
await self.wingman.memory.forget("Cutlass Black")  # Finds and deletes closest match
```

> **When to use which:** Use `forget_by_id()` when you tracked the ID. Use `forget()` when you want to delete "anything about X" without tracking IDs. Deduplication in `remember()` often makes explicit deletion unnecessary — just save the updated fact and the old one gets replaced.

### Complete API Reference

```text
self.wingman.local_ai                                # free local model + embeddings
│   ├── .available                                   → bool    # local model ready?
│   ├── .generate(text, *, system, preset, ...)      → str    # also temperature, top_p, top_k, reasoning
│   ├── .generate_sync(text, *, system, ...)         → str
│   ├── .summarize(text, *, instruction, ...)        → str
│   ├── .summarize_sync(text, *, instruction, ...)   → str
│   ├── .embed(texts)                                → list[list[float]] | None
│   └── .embed_sync(texts)                           → list[list[float]] | None

self.wingman.memory                                  # local persistent memory
    ├── .available                                   → bool    # persistent memory ready?
    ├── .remember(content, **kw)                     → int | None
    ├── .recall(query, **kw)                         → list[MemorySearchResult]
    ├── .context(query, max_tokens)                  → str    # whole MEMORY block, args ignored
    ├── .update(entry_id, new_content)               → bool
    ├── .forget(query)                               → bool
    └── .forget_by_id(entry_id)                      → bool
```

**Return type conventions:**

| Return type       | On failure            |
| ----------------- | --------------------- |
| `str`             | Empty string `""`     |
| `list[...]`       | Empty list `[]`       |
| `bool`            | `False`               |
| `int` (entry ID)  | `None`                |

### Full Example: Game Stats Tracker

A complete skill that fetches player stats from an API, summarizes them with the local support model, and remembers key facts for future conversations.

```python
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class GameStatsTracker(Skill):
    """Tracks and remembers player game statistics."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.retrieve_custom_property_value("api_base_url", errors)
        return errors

    def _get_api_base_url(self) -> str:
        errors = []
        return self.retrieve_custom_property_value("api_base_url", errors)

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
        if not self.wingman.local_ai.available:
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
        summary = await self.wingman.local_ai.summarize(
            raw,
            instruction="Extract: player rank, win/loss ratio, favorite loadout, "
                        "notable achievements. Be concise.",
        )
        if not summary:
            return "Failed to process the stats response."

        # 3. Remember for future conversations
        if self.wingman.memory.available:
            await self.wingman.memory.remember(f"{player_name}: {summary}")

        return summary

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
        if not self.wingman.memory.available:
            return "Memory is not available. Enable Local AI and Persistent Memory in Settings."

        results = await self.wingman.memory.recall(query, limit=5)
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
        if not self.wingman.memory.available:
            return "Memory is not available."

        deleted = await self.wingman.memory.forget(query)
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
- [quick_commands](quick_commands/) - Frequently-used shortcut actions

**Tool-Based (Progressive Disclosure):**

- [image_generation](image_generation/) - Image generation with styles, aspect ratios and reference images
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
- [sc_game_events](sc_game_events/) - Reacts to Star Citizen log events in character (`sc_gamelog.on`, support model, `language`)
- [sc_accountant](sc_accountant/) - Books trades and rewards from the Star Citizen log, with its own dashboard

**HUD:**

- [mic_status](mic_status/) - Microphone state as a HUD icon in its own group (`hud.group`, `audio.on_mic_status_changed`, `requires: [hud_server]`)

The chat and info panel on the HUD are Core's own (HUD profiles in the
settings, `hud` switches per Wingman); there is no HUD skill any more.

### Key APIs

**Wingman Access (`self.wingman` facade — see [the full reference above](#the-selfwingman-facade-api)):**

```python
self.wingman.config                    # Wingman configuration (read-only)
self.wingman.name                      # Wingman name
self.wingman.avatar_path               # Path to the wingman's avatar PNG (or None)
await self.wingman.ai.generate(...)    # Main-model side-call (capped)
await self.wingman.ai.generate_image(prompt)  # Generate image
self.wingman.audio.is_playing          # Is the wingman speaking?
```

**Client, HUD and game:**

```python
await self.wingman.conversation.show(text)              # A line in the chat, as said by this Wingman
await self.wingman.ui.show_dialog(title, markdown, once="MySkill.welcome")
text = await self.wingman.clipboard.read()               # the system clipboard; .write(text) sets it
await self.wingman.hud.add_info(title, markdown)         # shared info panel; False when the HUD is off
icon = self.wingman.hud.group("status", anchor="top_right")  # a group of your own, profile look
sub = self.wingman.sc_gamelog.on("mission_accepted", cb)  # sub.unsubscribe() in unload()
```

**Settings (read-only):**

```python
self.wingman.settings.debug_mode       # Is debug mode enabled?
self.wingman.settings.audio.output     # Output device config
self.wingman.language.name             # "German": say it in side-call prompts the user hears
```

**Utilities:**

```python
self.log.info(msg)                     # Friendly logging (pass server_only=True to skip the toast)
self.log.warning(msg) / self.log.error(msg)
self.get_generated_files_dir()         # Get persistent storage dir
self.wingman.run_in_thread(fn, *args)  # Run a blocking callable off the event loop
```

**Configuration & Secrets:**

```python
self.retrieve_custom_property_value(property_id, errors)  # Get config value (just-in-time!)
await self.wingman.secrets.retrieve(secret_name, errors)  # Get secret from SecretKeeper
```

### Best Practices

1. **Never cache config values** - retrieve them just-in-time so UI changes take effect immediately
2. **Never block the event loop** - wrap blocking calls in `await asyncio.to_thread(...)`; a sync `def` tool runs on the loop too. Keep asyncio objects on the loop that made them, see [Threads and event loops](#threads-and-event-loops)
3. **Import only the facade** - see [Allowed imports](AGENTS.md#allowed-imports)
4. **Always implement `unload()`** - clean up resources to prevent memory leaks
5. **Use type hints** - they auto-generate tool schemas and improve code quality
6. **Write clear tool descriptions** - include "WHEN TO USE" guidance for the AI
7. **Handle errors gracefully** - validate in `validate()`, don't crash at runtime
8. **Test in both modes** - development (source) and release (custom_skills)
9. **Keep dependencies minimal** - large dependencies make distribution difficult
10. **Document your skill** - help users understand how to configure and use it

---

## Getting Help

- **Discord**: Join the [Wingman AI Discord](https://www.shipbit.de/discord) for community support
- **GitHub**: Check existing skills for examples and patterns
- **Base Class**: Read [skill_base.py](skill_base.py) for complete API documentation

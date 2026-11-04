# Wingman AI Documentation

Welcome to the Wingman AI documentation hub. Here you'll find guides for development, configuration, and extending Wingman AI.

## Development Guides

Get started with Wingman AI development on your platform:

- **[Windows Development](develop-windows.md)** - Set up your development environment on Windows
- **[macOS Development](develop-macos.md)** - Set up your development environment on macOS
- **[Linux Development](develop-linux.md)** - Set up your development environment on Linux

## Extending Wingman AI

Learn how to create custom extensions for Wingman AI:

- **[Skills Developer Guide](../skills/README.md)** - Comprehensive guide for creating custom skills
  - How skills work and are discovered
  - Tool-based vs hook-based skills
  - Skill vs MCP decision guide
  - Available custom property types and UI controls
  - Bundling dependencies
  - Best practices and examples

## System One provider

System One's existing master and per-feature switches still control Jev. Its default
Wingman Subscription/Vercel route is unchanged. For OpenRouter:

1. Set `WINGMAN_JEV_PROVIDER=openrouter` in the environment that launches Core.
2. Set `OPENROUTER_API_KEY`, or use Wingman's existing `openrouter` secret.
   The older `Openrouter` spelling is accepted too; the lowercase name takes precedence.
3. Enable the existing fast-decision settings for the features you want.

The environment key takes precedence over saved secrets. Each decision reads the
selection and current key; an already running Core inherits its launch environment.
Missing credentials or request failures use Jev's existing fallback to the normal
model/matcher, without sending the OpenRouter key to Pro or Vercel. Remove the
provider environment setting to restore the default route. This does not select
Jev as the conversation model or change other speech/model providers.

## Reference

Additional reference documentation:

- **[The HUD](hud.md)** - The shared chat and info containers, HUD profiles per config, the preview and the per-Wingman switches
- **[What Wingman AI shortens, and when](context-and-shortening.md)** - Every place where tool responses, the conversation or skill input get cut, cleared or summarized, with example scenarios
- **[CI/CD Pipeline](ci-cd.md)** - How Core is built and staged
- **[MCP OAuth](mcp-oauth.md)** - How hosted MCP servers that need OAuth are connected
- **[Available Edge TTS Voices](available-edge-tts-voices.md)** - Complete list of available voices for Edge TTS

## Additional Resources

- [Main Repository README](../README.md) - Project overview and getting started
- [Official Website](https://www.wingman-ai.com) - Downloads, client, and subscription info
- [Discord Community](https://www.shipbit.de/discord) - Get help and connect with other developers
- [API Documentation](http://127.0.0.1:49111/docs) - OpenAPI/Swagger spec (when Wingman AI Core is running)

## Contributing

If you're planning to develop a major feature or new integration, please contact us on [Discord](https://www.shipbit.de/discord) first. We'll be happy to help you get started and ensure your work aligns with the project's direction.

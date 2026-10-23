"""Migration from version 3.2.0 to 3.2.1.

3.2.1 teaches Wingman OAuth for MCP servers, and ships ElevenLabs' hosted server
as the first one that needs it. Two things follow for a config written by 3.2.0.

`mcp.yaml` is a user-owned file: it is copied from the template once and then
belongs to whoever edits it, so a new template entry never reaches anyone who
already has one. The ElevenLabs server is appended here, unless a server of that
name is already present — someone may have added it by hand, and their settings
win.

Nothing else changes. `McpServerConfig.auth` defaults to `api_key`, which is
exactly what every server did before, so servers already in the file keep sending
the `mcp_<name>` secret as a bearer header without being touched.
"""

from services.migrations.base_migration import BaseMigration

# Kept in step with templates/configs/mcp.template.yaml. Duplicating it is the
# lesser evil: reading the template at migration time would make this migration's
# result depend on whichever version of the file happens to be installed, and a
# migration has to produce the same config every time it runs.
ELEVENLABS_SERVER = {
    "name": "elevenlabs",
    "display_name": "ElevenLabs",
    "description": (
        "ElevenLabs generative media. Generate images and video from a prompt, "
        "turn text into speech, transcribe audio, design new voices and browse "
        "the voice library."
    ),
    "discovery_keywords": [
        "ElevenLabs",
        "11labs",
        "generate an image",
        "create a picture",
        "generate a video",
        "text to speech",
        "read this out loud",
        "voice",
        "design a voice",
        "transcribe",
        "speech to text",
    ],
    "type": "http",
    "url": "https://api.us.elevenlabs.io/v1/mcp",
    "auth": "oauth",
    "oauth_client_id": (
        "https://wingman-ai-mcp-servers.wingman-ai.workers.dev/oauth/client"
    ),
    # Every generator runs through a flow, so `flows` is not optional: without
    # it even speech answers 403.
    "oauth_scopes": [
        "flows",
        "image_video_generation",
        "text_to_speech",
        "voice_generation",
        "speech_history_read",
    ],
    # 111 tools, roughly 222,000 tokens of schema. These seven are what a voice
    # assistant reaches for, at 6,782. See `tools_allow` on McpServerConfig.
    "tools_allow": [
        "creative_generate_image",
        "creative_generate_video",
        "creative_generate_speech",
        "creative_edit_image",
        "creative_transcribe_audio",
        "creative_list_voices",
        "creative_get_flow_run_status",
    ],
    "discoverable_by_default": False,
}


class Migration320To321(BaseMigration):
    """Migration from 3.2.0 to 3.2.1."""

    old_version = "3_2_0"
    new_version = "3_2_1"

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Keep the user's MCP servers and add the ElevenLabs one."""
        if not old:
            # No mcp.yaml before this point, so the template is already right.
            return new

        servers = old.get("servers")
        if not isinstance(servers, list):
            self.log_warning(
                "mcp.yaml has no server list — leaving it alone and skipping the "
                "ElevenLabs entry."
            )
            return old

        if any(
            isinstance(server, dict) and server.get("name") == ELEVENLABS_SERVER["name"]
            for server in servers
        ):
            self.log("ElevenLabs MCP server already configured — left as it is.")
            return old

        servers.append(dict(ELEVENLABS_SERVER))
        self.log("Added the ElevenLabs MCP server, which authenticates with OAuth.")
        return old

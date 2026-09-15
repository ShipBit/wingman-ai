"""Migration from version 3.2.1 to 3.2.2.

3.2.1 narrowed an MCP server's tool list with two glob fields, `tools_allow` and
`tools_deny`. 3.2.2 replaces them with `disabled_tools`: every tool the server
offers stays visible in the UI with a switch, and the names in that list are
the ones switched off. A blacklist, so a tool the server adds later is on by
default.

For the ElevenLabs entry that 3.2.1 shipped with `tools_allow: creative_*`-style
whitelists, the equivalent blacklist is written here: the 104 tools that are
not the seven a voice assistant reaches for. For any other server that carried
glob fields, they are dropped with a warning — the tool names are only known
once the server is connected, so a glob cannot be turned into names here.
"""

from services.migrations.base_migration import BaseMigration

# Kept in step with templates/configs/mcp.template.yaml. The 111 names were read
# from the live server on 2026-09-15.
ELEVENLABS_DISABLED_TOOLS = [
    "agents_list",
    "agents_get",
    "agents_get_summaries",
    "agents_get_widget",
    "agents_get_link",
    "agents_get_knowledge_size",
    "agents_calculate_llm_usage",
    "agents_list_conversations",
    "agents_get_conversation",
    "agents_duplicate",
    "agents_delete",
    "agents_search_conversation_messages",
    "agents_resolve_conversation",
    "agents_get_topics",
    "agents_list_branches",
    "agents_get_branch",
    "agents_update_branch",
    "agents_get_version",
    "agents_merge_branch_preview",
    "agents_merge_branch",
    "agents_create_deployment",
    "agents_create_draft",
    "agents_delete_draft",
    "agents_create_procedure",
    "agents_list_procedures",
    "agents_get_procedure",
    "agents_delete_procedure",
    "agents_compile_procedures",
    "agents_get_procedure_draft",
    "agents_update_procedure_draft",
    "agents_delete_procedure_draft",
    "agents_list_knowledge_base",
    "agents_get_kb_document",
    "agents_create_kb_text",
    "agents_create_kb_url",
    "agents_create_kb_folder",
    "agents_update_kb_document",
    "agents_delete_kb_document",
    "agents_bulk_delete_knowledge_base",
    "agents_bulk_move_knowledge_base",
    "agents_search_knowledge_base",
    "agents_query_knowledge_base_rag",
    "agents_get_kb_dependents",
    "agents_create_tool",
    "agents_list_tools",
    "agents_get_tool",
    "agents_update_tool",
    "agents_delete_tool",
    "agents_get_tool_dependents",
    "agents_get_tool_executions",
    "agents_create_mcp_server",
    "agents_list_mcp_servers",
    "agents_get_mcp_server",
    "agents_update_mcp_server",
    "agents_delete_mcp_server",
    "agents_list_mcp_server_tools",
    "agents_create_test",
    "agents_list_tests",
    "agents_get_test",
    "agents_delete_test",
    "agents_run_tests",
    "agents_list_test_runs",
    "agents_get_test_run",
    "agents_list_phone_numbers",
    "agents_get_phone_number",
    "agents_update_phone_number",
    "agents_delete_phone_number",
    "agents_list_triage_tickets",
    "agents_create_manual_triage_ticket",
    "agents_get_triage_ticket_assignable_users",
    "agents_get_triage_ticket",
    "agents_create_triage_ticket",
    "agents_update_triage_ticket",
    "agents_add_triage_ticket_comment",
    "agents_add_triage_ticket_turn_comment",
    "agents_delete_triage_ticket",
    "agents_create",
    "agents_update",
    "agents_create_branch",
    "agents_create_code_tool",
    "agents_update_code_tool",
    "creative_generate_in_flow",
    "creative_create_flow",
    "creative_get_flow",
    "creative_get_flow_node_types",
    "creative_add_flow_node",
    "creative_add_flow_asset_node",
    "creative_upload_flow_reference",
    "creative_connect_flow_nodes",
    "creative_update_node",
    "creative_run_flow_nodes",
    "creative_show_flow_results",
    "creative_get_model_guide",
    "creative_get_model_schema",
    "creative_design_voice",
    "creative_save_designed_voice",
    "creative_get_voice_design_previews",
    "creative_get_view_state",
    "creative_save_view_state",
    "creative_get_available_assets",
    "creative_create_asset_upload",
    "creative_finalize_asset_upload",
    "creative_attach_reference_file",
    "get_more_tools",
]


class Migration321To322(BaseMigration):
    """Migration from 3.2.1 to 3.2.2."""

    old_version = "3_2_1"
    new_version = "3_2_2"

    # Two feature keys 3.2.2 no longer reads. `remember_messages` deleted old
    # turns outright, with no summary, and had no UI since the redesign;
    # condensation does that job. `condense_keep_recent` counted user messages
    # and is replaced by `condense_keep_recent_tokens`, a token budget — twelve
    # turns of trading play were 23,000 tokens, twelve turns of chat 3,000, and
    # a message count cannot tell the two apart. The new key comes from the
    # template backfill with its default; the old value is not converted, no
    # number of messages maps to a number of tokens.
    DROPPED_FEATURES = ("remember_messages", "condense_keep_recent")

    def _drop_features(self, config: dict, label: str) -> dict:
        features = config.get("features")
        if isinstance(features, dict):
            for key in self.DROPPED_FEATURES:
                if key in features:
                    features.pop(key)
                    self.log(f"{label}: removed features.{key}")
        return config

    def _replace_inworld_prompt(self, config: dict, label: str) -> dict:
        """Drop the Inworld TTS prompt so the template backfill writes the 3.2.2 one.

        For everyone, edited or not. The old prompt asked for a sound
        "regularly", listed [breathe] first and spent half its lines on emotion
        tags that inworld-tts-2-flash ignores; the result was a "[breathe]" at
        the start of every reply. The new text was tuned against every chat
        model in the plan, and a hand-edited copy of the old one carries the
        same flaw. Anyone who wants their own prompt back edits it again.
        """
        inworld = config.get("inworld")
        if isinstance(inworld, dict) and "tts_prompt" in inworld:
            inworld.pop("tts_prompt")
            self.log(f"{label}: replaced the Inworld TTS prompt with the 3.2.2 version")
        return config

    def migrate_defaults(self, old: dict) -> dict:
        return self._replace_inworld_prompt(self._drop_features(dict(old), "defaults"), "defaults")

    def migrate_wingman(self, old: dict) -> dict:
        label = old.get("name", "wingman")
        return self._replace_inworld_prompt(self._drop_features(dict(old), label), label)

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Turn the 3.2.1 glob filters into the 3.2.2 disabled list."""
        if not old:
            return new

        servers = old.get("servers")
        if not isinstance(servers, list):
            return old

        for server in servers:
            if not isinstance(server, dict):
                continue
            had_globs = "tools_allow" in server or "tools_deny" in server
            server.pop("tools_allow", None)
            server.pop("tools_deny", None)

            if server.get("name") == "elevenlabs":
                if not server.get("disabled_tools"):
                    server["disabled_tools"] = list(ELEVENLABS_DISABLED_TOOLS)
                    self.log(
                        "ElevenLabs MCP server: replaced the tool whitelist with the "
                        "matching disabled list."
                    )
            elif had_globs:
                self.log_warning(
                    f"MCP server '{server.get('name')}': the tools_allow/tools_deny "
                    "filter was removed. Switch tools off in the server's tool list "
                    "instead."
                )

        return old

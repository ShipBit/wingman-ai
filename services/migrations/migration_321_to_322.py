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

Speech-to-text also moves in 3.2.2. It used to be chosen twice: once per
wingman (`features.stt_provider`, read when a record key was held) and once
in settings (`voice_activation.stt_provider`, read when voice activation
heard something). The same recording could take two different engines. Now
there is one `stt` block in settings.yaml and nothing in the wingman files.
Everyone is put on local Parakeet: it runs on the machine, costs nothing, is
fast, and handles 25 languages. The other providers stay selectable in
Settings for anyone it does not work for.
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
    DROPPED_FEATURES = ("remember_messages", "condense_keep_recent", "stt_provider")

    # Per-wingman STT tuning that has no home any more. The global equivalents
    # live under `stt` in settings.yaml.
    DROPPED_STT_SECTIONS = ("parakeet", "fasterwhisper", "whispercpp")
    DROPPED_WINGMAN_PRO_KEYS = ("stt_provider", "languages")

    # The fields that are about listening, not about transcribing.
    VOICE_ACTIVATION_KEYS = (
        "enabled",
        "mute_toggle_key",
        "mute_toggle_key_codes",
    )
    STT_SECTIONS = (
        "languages",
        "parakeet",
        "parakeet_config",
    )
    # Providers 3.2.2 no longer ships: FasterWhisper, whisper.cpp, and the
    # OpenAI and Groq transcription. Their settings are dropped, not carried.
    REMOVED_STT_SECTIONS = (
        "fasterwhisper",
        "fasterwhisper_config",
        "whispercpp",
        "whispercpp_config",
    )

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

    def _drop_stt(self, config: dict, label: str) -> dict:
        """Speech-to-text is a global setting now; nothing of it stays here."""
        for key in self.DROPPED_STT_SECTIONS:
            if key in config:
                config.pop(key)
                self.log(f"{label}: removed the {key} section (speech-to-text is set in Settings now)")
        pro = config.get("wingman_pro")
        if isinstance(pro, dict):
            for key in self.DROPPED_WINGMAN_PRO_KEYS:
                if key in pro:
                    pro.pop(key)
                    self.log(f"{label}: removed wingman_pro.{key}")
        return config

    def _migrate_wingman_config(self, old: dict, label: str) -> dict:
        config = dict(old)
        config = self._drop_features(config, label)
        config = self._replace_inworld_prompt(config, label)
        config = self._unpin_chat_model(config, label)
        return self._drop_stt(config, label)

    def _unpin_chat_model(self, config: dict, label: str) -> dict:
        """Clear a pinned chat model so everyone follows the plan default.

        3.2.2 makes gpt-4.1-mini the default chat model on the backend. A user
        who never changed it has `conversation_deployment` empty already and
        follows along; one who picked a specific model at some point is pinned
        to it and would miss the new default. Emptying the field puts everyone
        back on "follow the plan default". Anyone who wants a specific model
        can pick it again in Settings; the choice is one click and the list is
        the plan's."""
        pro = config.get("wingman_pro")
        if not isinstance(pro, dict):
            return config
        pinned = str(pro.get("conversation_deployment") or "").strip()
        if pinned:
            pro = dict(pro)
            pro["conversation_deployment"] = ""
            config = dict(config)
            config["wingman_pro"] = pro
            self.log(f"{label}: chat model '{pinned}' -> plan default (unpinned)")
        return config

    def migrate_settings(self, old: dict) -> dict:
        """Split `voice_activation` into listening (stays) and transcribing (new `stt`),
        and move the local support model from the 2B to the 4B."""
        new = dict(old)
        self._upgrade_local_support_model(new)
        va = old.get("voice_activation")
        if not isinstance(va, dict):
            return new

        stt: dict = dict(new.get("stt") or {})
        for key in self.STT_SECTIONS:
            if key in va and key not in stt:
                stt[key] = va[key]

        was = va.get("stt_provider")
        stt["provider"] = "parakeet"
        parakeet = dict(stt.get("parakeet") or {})
        if parakeet.get("run_locally") is False:
            parakeet["run_locally"] = True
            self.log("settings: Parakeet now runs on this machine (was remote)")
        # The old template put this machine as the server address. Picking
        # "Remote" then failed at once, there is no server here. Empty means
        # "not set" now; a real address of the user's stays.
        if str(parakeet.get("host") or "").rstrip("/") in ("http://127.0.0.1", "http://localhost", "127.0.0.1", "localhost"):
            parakeet["host"] = ""
        if parakeet:
            stt["parakeet"] = parakeet
        if was and was != "parakeet":
            self.log_warning(
                f"settings: speech-to-text '{was}' -> 'parakeet'. Parakeet runs on "
                "this machine; the subscription's cloud transcription can be picked in Settings."
            )
        elif not was:
            self.log("settings: speech-to-text set to 'parakeet'")

        # Fields that no longer exist
        parakeet_config = stt.get("parakeet_config")
        if isinstance(parakeet_config, dict) and "language" in parakeet_config:
            parakeet_config.pop("language")
        # The FasterWhisper hotword list is not carried over into the new
        # vocabulary: that list starts clean.
        for key in self.REMOVED_STT_SECTIONS:
            if key in stt:
                stt.pop(key)
                self.log(f"settings: removed stt.{key} (provider no longer shipped)")

        new["stt"] = stt
        listening = {key: va[key] for key in self.VOICE_ACTIVATION_KEYS if key in va}
        # The energy threshold was a loudness number that depended on the
        # microphone. A voice detector replaces it; what survives is how far
        # the user had pushed the old number, mapped onto the new sensitivity.
        threshold = va.get("energy_threshold")
        if isinstance(threshold, (int, float)):
            if threshold <= 0.001:
                listening["sensitivity"] = 0.8
            elif threshold >= 0.02:
                listening["sensitivity"] = 0.3
            else:
                listening["sensitivity"] = 0.5
            self.log(
                f"settings: voice detection sensitivity {listening['sensitivity']} "
                f"(was energy threshold {threshold})"
            )
        new["voice_activation"] = listening
        self.log("settings: moved the speech-to-text settings out of voice_activation into stt")
        return new

    def _upgrade_local_support_model(self, settings: dict) -> None:
        """Memory is written by one rewrite prompt from 3.2.2 on, and the 2B
        cannot follow it: on the bench it returned nothing usable in 17 of 19
        sessions. The 4B scores level with the cloud models. Only the old
        default is moved; a model the user picked stays."""
        llama = settings.get("llama_cpp")
        if not isinstance(llama, dict):
            return
        if llama.get("support_model") == "Qwen3.5-2B-Q4_K_M.gguf":
            llama = dict(llama)
            llama["support_model"] = "Qwen3.5-4B-Q4_K_M.gguf"
            settings["llama_cpp"] = llama
            self.log("settings: local support model Qwen3.5-2B -> Qwen3.5-4B (the 2B cannot write memory any more)")

    def migrate_defaults(self, old: dict) -> dict:
        return self._migrate_wingman_config(old, "defaults")

    def migrate_wingman(self, old: dict) -> dict:
        return self._migrate_wingman_config(old, old.get("name", "wingman"))

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

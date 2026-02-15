"""
Improved Star Citizen Keybindings Manager

This module manages Star Citizen keybindings with a unified data structure that makes it
easier to understand, configure, and update keybindings for voice commands.

Key improvements:
- Single source of truth: sc_all_keybindings.json with complete metadata
- Clear status tracking with ai_status field
- Easy to reference commands in config.yaml
- Simplified update process that preserves custom data
- Better documentation and helper methods
"""

import xml.etree.ElementTree as ET
import json
import re
import traceback
import os
import copy
import requests
import time
from typing import Dict, List, Set, Optional, Any
from pathlib import Path

from services.secret_keeper import SecretKeeper

DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class SCKeybindings:
    """
    Manages Star Citizen keybindings for Wingman AI voice commands.
    
    This class handles:
    - Loading default and custom keybindings from SC files
    - Generating AI command phrases (using OpenAI)
    - Tracking which commands are active for AI
    - Providing easy access to command information
    """

    def __init__(self, config: Dict[str, Any], secret_keeper: SecretKeeper):
        """
        Initialize the keybindings manager.
        
        Args:
            config: Configuration dictionary from config.yaml
            secret_keeper: Service for managing API keys
        """
        self.config = config
        self.secret_keeper = secret_keeper
        
        # ─── Path Configuration ───
        self.data_root_path = f'{config["data-root-directory"]}{config["sc-keybind-mappings"]["keybindings-directory"]}'
        self.sc_installation_dir = config["sc-keybind-mappings"]["sc_installation_dir"]
        self.user_keybinding_file_name = config["sc-keybind-mappings"]["user_keybinding_file_name"]
        self.sc_active_channel = config["sc-keybind-mappings"]["sc_active_channel"]
        self.sc_channel_version = config["sc-keybind-mappings"]["sc_channel_version"]
        
        # ─── File Paths ───
        self.version_dir = Path(self.data_root_path) / self.sc_channel_version
        self.json_path = self.version_dir / "sc_all_keybindings.json"
        
        # Deprecated files (kept for backward compatibility during migration)
        self.json_path_knowledge = self.version_dir / "keybindings_existing_knowledge.json"
        self.json_path_miss_knowledge = self.version_dir / "keybindings_missing_knowledge.json"
        
        # SC game files
        self.default_keybinds_file = self.version_dir / config["sc-keybind-mappings"]["sc_unp4k_file_default_keybindings_filter"]
        self.keybindings_localization_file = self.version_dir / config["sc-keybind-mappings"]["sc_unp4k_file_keybinding_localization_filter"]
        self.en_translation_file = config["sc-keybind-mappings"]["en_translation_file"]
        self.sc_translations_en = self.version_dir / self.en_translation_file
        
        # User custom keybindings
        user_keybinding_file_config = f"{self.sc_installation_dir}/{self.sc_active_channel}/USER/Client/0/Controls/Mappings/{self.user_keybinding_file_name}"
        self.user_keybinding_file = Path(user_keybinding_file_config.format(sc_channel_version=self.sc_channel_version))
        
        # ─── Runtime Data ───
        self.keybindings: Optional[Dict] = None  # Loaded on first access
        
        # ─── Configuration ───
        self.player_language = config["openai"]["player_language"]
        self.command_languages = config["command_languages"]
        self.keybind_categories_to_ignore: Set[str] = set(config.get("keybind_categories_to_ignore", []))
        self.keybind_actions_to_include: Set[str] = set(config.get("include_actions", []))
        self.ignored_actionnames: Set[str] = set(config.get("ignored_actionnames", []))
        
        # ─── OpenAI Configuration ───
        self.openai_keybinding_generation_model = config.get("keybinding_generation_model", "gpt-4")
        self.open_api_key = secret_keeper.retrieve(
            requester="openai",
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False,
        )
        
        # ─── State Flags ───
        self.instant_activation_commands_built = False

    # ════════════════════════════════════════════════════════════════════════
    # Public API Methods
    # ════════════════════════════════════════════════════════════════════════

    def get_command(self, command_name: str) -> Optional[Dict]:
        """
        Get a specific command by its actionname.
        
        Args:
            command_name: The actionname (e.g., "v_toggle_mining_mode")
            
        Returns:
            Command dictionary with all data including ai_status, or None if not found
        """
        self._ensure_keybindings_loaded()
        command = self.keybindings.get(command_name)
        if command:
            return command

        for cmd in self.keybindings.values():
            if cmd.get("ai_command_reference_name") == command_name:
                return cmd

        return None

    def get_active_commands(self) -> Dict[str, Dict]:
        """
        Get all commands that are active for AI.
        
        Returns:
            Dictionary of active commands (actionname -> command data)
        """
        self._ensure_keybindings_loaded()
        return {
            name: cmd for name, cmd in self.keybindings.items()
            if cmd.get('ai_status', {}).get('is_active', False)
        }

    def get_bound_keybinding_names(self) -> List[str]:
        """
        Get list of all command names that should be available to AI.
        
        This method also builds instant activation commands if not already done.
        
        Returns:
            List of actionnames for active commands
        """
        self._ensure_keybindings_loaded()

        filtered = []
        
        for key, keybindingEntry in self.keybindings.items():
            # Check if command is active for AI
            if keybindingEntry.get('ai_status', {}).get('is_active', False):
                filtered.append(key)
                reference_name = keybindingEntry.get("ai_command_reference_name")
                if reference_name:
                    filtered.append(reference_name)

        if not self.instant_activation_commands_built:
            self._build_instant_activation_commands(filtered)
            self.instant_activation_commands_built = True
               
        return list(dict.fromkeys(filtered))

    def parse_and_create_files(self):
        """
        Main entry point to parse SC keybindings and create/update the unified JSON file.
        
        This method:
        1. Checks if update is needed
        2. Loads or builds default keybindings
        3. Merges custom user keybindings
        4. Calculates AI status for all commands
        5. Generates command phrases (if needed)
        6. Saves to unified sc_all_keybindings.json
        """
        # Check if files exist and updates are disabled
        if self.json_path.exists() and not self.config.get("update_keybindings", False):
            print_debug(f"Keybind files already exist, updates disabled: {self.json_path}")
            return

        print_debug("=" * 80)
        print_debug(f"Processing keybindings for {self.sc_channel_version}")
        print_debug("=" * 80)

        # Load existing or build from scratch
        if self.json_path.exists() and self.config.get("update_keybindings", True):
            print_debug("Update mode: Loading existing keybindings")
            actions = self._load_sc_all_keybindings()
            actions = self._merge_missing_default_actions(actions)
        else:
            print_debug("Initial build: Parsing SC default keybindings")
            actions = self._build_sc_keybinding_default_actions()

        # Load custom player keybindings
        if self.user_keybinding_file.exists():
            print_debug(f"Loading custom user keybindings from: {self.user_keybinding_file}")
            actions = self._load_custom_keybinds(actions)
        else:
            print_debug(f"No custom keybindings file found: {self.user_keybinding_file}")

        # Ensure ai_command_reference_name is present for all actions
        self._ensure_ai_command_reference_names(actions)

        # Calculate AI status for all commands
        print_debug("Calculating AI status for all commands...")
        self._calculate_ai_status_for_all(actions)

        # Save unified file
        print_debug(f"Saving unified keybindings to: {self.json_path}")
        self._save_unified_keybindings(actions)

        # Generate command phrases for active commands without phrases
        # Never regenerate if command-phrases already exist
        needs_phrases = {
            name: cmd for name, cmd in actions.items()
            if cmd.get('ai_status', {}).get('is_active', False)
            and not cmd.get('command-phrases')
        }

        if needs_phrases:
            print_debug(f"Generating command phrases for {len(needs_phrases)} active commands without phrases...")
            print_debug("Command phrases will be generated for:")
            for action_name, cmd in self._get_sorted_action_items(needs_phrases):
                category = cmd.get('category', '') or 'uncategorized'
                reference_name = cmd.get("ai_command_reference_name") or action_name
                print_debug(f"  - {category}: {reference_name}")
            self._create_instant_activation_value(needs_phrases)
        else:
            print_debug("No command phrase generation needed (all active commands have phrases)")

        # Clear cached data to force reload
        self.keybindings = None
        
        print_debug("=" * 80)
        print_debug("Keybindings processing complete!")
        print_debug("=" * 80)

    # ════════════════════════════════════════════════════════════════════════
    # Private Helper Methods
    # ════════════════════════════════════════════════════════════════════════

    def _ensure_keybindings_loaded(self):
        """Ensure keybindings are loaded from file."""
        if self.keybindings is None:
            self.keybindings = self._load_sc_all_keybindings()

    def _merge_missing_default_actions(self, actions: Dict) -> Dict:
        """
        Merge newly added default actions into existing keybindings.

        Existing entries are preserved exactly (including user-defined command-phrases).
        Only action names that are missing in the current JSON are added.
        """
        default_actions = self._build_sc_keybinding_default_actions()
        missing_action_names = [
            action_name for action_name in default_actions
            if action_name not in actions
        ]

        if not missing_action_names:
            print_debug("Update mode: No new default actions to add")
            return actions

        for action_name in missing_action_names:
            actions[action_name] = copy.deepcopy(default_actions[action_name])

        print_debug(
            f"Update mode: Added {len(missing_action_names)} new actions from default keybindings"
        )

        return actions

    def _load_sc_all_keybindings(self) -> Dict:
        """Load the unified keybindings from JSON file."""
        if not self.json_path.exists():
            print_debug(f"Warning: Keybindings file not found: {self.json_path}")
            return {}
        
        with open(self.json_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _save_unified_keybindings(self, actions: Dict):
        """Save the unified keybindings to JSON file."""
        self.version_dir.mkdir(parents=True, exist_ok=True)

        sorted_actions = self._sort_actions_for_save(actions)

        with open(self.json_path, mode="w", encoding="utf-8") as file:
            json.dump(sorted_actions, file, indent=4, ensure_ascii=False)

        print_debug(f"✅ Saved {len(sorted_actions)} commands to {self.json_path.name}")

    def _ensure_ai_command_reference_names(self, actions: Dict):
        """Ensure ai_command_reference_name exists for each action."""
        for action_name, cmd in actions.items():
            reference_name = self._build_ai_command_reference_name(cmd)
            if reference_name:
                cmd["ai_command_reference_name"] = reference_name
            elif "ai_command_reference_name" not in cmd:
                cmd["ai_command_reference_name"] = action_name

    def _build_ai_command_reference_name(self, cmd: Dict) -> str:
        """Build a stable, human-friendly command reference name."""
        key_value = (cmd.get("actionname") or "").strip()

        label_en = (cmd.get("action-label-en") or "").strip()
        desc_en = (cmd.get("action-description-en") or "").strip()

        if len(label_en) > 5 or len(label_en) > len(key_value):
            key_value = label_en
        elif len(desc_en) > 5 and len(desc_en) > len(key_value):
            key_value = desc_en

        category = (cmd.get("category") or "").strip()
        if category:
            key_value = f"{category}_{key_value}"

        json_key = ''.join([char if char.isalnum() else '_' for char in key_value])
        json_key = re.sub(r'_+', '_', json_key).strip('_')

        return json_key or (cmd.get("actionname") or "")

    def _sort_actions_for_save(self, actions: Dict) -> Dict:
        """Return actions sorted by active status, category, then action name."""
        sorted_items = self._get_sorted_action_items(actions)
        return {action_name: cmd for action_name, cmd in sorted_items}

    def _get_sorted_action_items(self, actions: Dict) -> List:
        """Return sorted (action_name, cmd) pairs for consistent ordering."""
        def sort_key(item):
            action_name, cmd = item
            is_active = cmd.get('ai_status', {}).get('is_active', False)
            category = (cmd.get('category') or '').lower()
            action_lower = (action_name or '').lower()
            return (0 if is_active else 1, category, action_lower)

        return sorted(actions.items(), key=sort_key)

    def _calculate_ai_status(self, cmd: Dict) -> Dict:
        """
        Calculate AI status metadata for a single command.
        
        Args:
            cmd: Command dictionary
            
        Returns:
            Dictionary with ai_status fields
        """
        status = {
            'is_active': True,
            'inactive_reason': None,
            'has_keybinding': False,
            'has_command_phrases': False,
            'is_custom_configured': False,
            'activation_supported': True
        }
        
        # Check if has keybinding
        kb = cmd.get('keyboard-mapping', '').strip()
        status['has_keybinding'] = bool(kb)
        
        # Check if has command phrases
        phrases = cmd.get('command-phrases', {})
        if phrases:
            status['has_command_phrases'] = any(
                bool(phrase_list) for phrase_list in phrases.values() if phrase_list
            )
        
        # Check if custom configured in config.yaml
        actionname = cmd.get('actionname', '')
        custom_commands = [c.get('name') for c in self.config.get('commands', [])]
        status['is_custom_configured'] = actionname in custom_commands
        
        # Check activation mode support - any mode with "hold" in name is not supported
        activation_mode = cmd.get('activationMode', '')
        if activation_mode and 'hold' in activation_mode.lower():
            status['activation_supported'] = False
            status['is_active'] = False
            status['inactive_reason'] = 'unsupported_activation'
            return status
        
        # Check if explicitly excluded
        if actionname in self.ignored_actionnames:
            # Unless explicitly included
            if actionname not in self.keybind_actions_to_include:
                status['is_active'] = False
                status['inactive_reason'] = 'explicitly_excluded'
                return status
        
        # Check if category is excluded
        category = cmd.get('category', '')
        if category in self.keybind_categories_to_ignore:
            # Unless this specific action is included
            if actionname not in self.keybind_actions_to_include:
                status['is_active'] = False
                status['inactive_reason'] = 'category_excluded'
                return status
        
        # Check if has keybinding
        if not status['has_keybinding']:
            status['is_active'] = False
            status['inactive_reason'] = 'no_keybinding'
            return status
        
        # If we reach here, command is active
        status['is_active'] = True
        return status

    def _calculate_ai_status_for_all(self, actions: Dict):
        """Calculate and set AI status for all commands."""
        for actionname, cmd in actions.items():
            cmd['ai_status'] = self._calculate_ai_status(cmd)

    def _build_instant_activation_commands(self, commands_to_consider: List[str]):
        """
        Build instant activation commands for keybindings and add to config.
        
        This takes command-phrases from the keybindings and creates instant activation
        entries in the config that haven't been manually configured.
        
        Args:
            commands_to_consider: List of actionnames to process
        """
        try:
            custom_commands_list = [
                command["name"]
                for command in self.config.get("commands", [])
            ]

            custom_commands = set(custom_commands_list)  
            self._ensure_keybindings_loaded()

            for key, keybinding_entry in self.keybindings.items():
                if key in custom_commands or key not in commands_to_consider:
                    continue  # Skip custom or excluded commands
                reference_name = keybinding_entry.get("ai_command_reference_name") or key
                if reference_name in custom_commands:
                    continue

                command = {}
                command["name"] = reference_name
                
                sc_commands = []
                sc_commands.append({"sc_command": reference_name})
                command["sc_commands"] = sc_commands
                
                # Get command phrases
                player_language = "en"
                instant_activations = []
                command_phrases = keybinding_entry.get("command-phrases", {})

                # Add English phrases
                for command_phrase in command_phrases.get(player_language, []):
                    instant_activations.append(command_phrase)

                # Add player language phrases if different from English
                if self.player_language and not self.player_language.startswith("en"):
                    player_language = self.player_language
                    for command_phrase in command_phrases.get(player_language, []):
                        instant_activations.append(command_phrase)
                
                command["instant_activation"] = instant_activations
                command["responses"] = False  # No AI reaction for player actions

                self.config["commands"].append(command)
        except Exception:
            traceback.print_exc()

    def _build_sc_keybinding_default_actions(self) -> Dict:
        """
        Parse SC default keybindings from XML and build action dictionary.
        
        Returns:
            Dictionary of actions with default keybindings and localizations
        """
        if not self.default_keybinds_file.exists():
            raise FileNotFoundError(f"Default keybindings file not found: {self.default_keybinds_file}")
        
        print_debug(f"Loading default keybindings from: {self.default_keybinds_file}")
        tree = ET.parse(str(self.default_keybinds_file))
        root = tree.getroot()

        actions = {}
        
        for actionmap in root.findall(".//actionmap"):
            category_code = actionmap.get("name")
            for action in actionmap.findall(".//action"):
                action_name = action.get("name")
                activation_mode = action.get("activationMode")
                keyboard_mapping = action.get("keyboard", None)
                label_ui = action.get("UILabel")
                description_ui = action.get("UIDescription")

                # Skip if no keyboard attribute in XML
                if keyboard_mapping is None:
                    continue

                entry = {
                    "category": category_code,
                    "actionname": action_name,
                    "activationMode": activation_mode,
                    "keyboard-mapping": keyboard_mapping,
                    "keyboard-mapping-default": keyboard_mapping,  # Track default
                    "keyboard-mapping-custom": None,  # No custom yet
                    "label-ui": label_ui,
                    "description-ui": description_ui,
                }

                actions[action_name] = entry

        print_debug(f"Loaded {len(actions)} default keybindings")

        # Add localizations
        self._add_localizations(actions)

        return actions

    def _add_localizations(self, actions: Dict):
        """Add localized names and keybindings to actions."""
        if not self.keybindings_localization_file.exists():
            print_debug(f"Warning: Localization file not found: {self.keybindings_localization_file}")
            return

        print_debug("Loading keybinding localizations...")
        tree_localization = ET.parse(str(self.keybindings_localization_file))
        root_localization = tree_localization.getroot()

        # Create mapping of key names to localization strings
        localization_map = {}
        for device in root_localization.findall(".//device"):
            for key in device.findall(".//Key"):
                key_name = key.get("name")
                localization_string = key.get("localizationString")
                localization_map[key_name] = localization_string

        # Update actions with localized keybindings
        for action_name in actions:
            kb = actions[action_name]["keyboard-mapping"]
            actions[action_name]["keyboard-mapping-ui"] = self._localize_keybinding(localization_map, kb)

        # Load English translations
        if self.sc_translations_en.exists():
            translations_en = self._load_translations(self.sc_translations_en)
            self._update_actions_with_translations(actions, translations_en, "en")

        # Load other language translations
        for language in self.command_languages:
            translation_file = self.version_dir / f"global_{language}.ini"
            if translation_file.exists():
                translations = self._load_translations(translation_file)
                self._update_actions_with_translations(actions, translations, language)

    def _load_translations(self, file_path: Path) -> Dict:
        """Load translations from INI file."""
        translations = {}
        print_debug(f"Loading translations from: {file_path}")
        
        with open(file_path, "r", encoding="utf-8", errors='ignore') as file:
            for line in file:
                if "=" in line:
                    key, value = line.split("=", 1)
                    translations[key.strip()] = value.strip()
        
        return translations

    def _update_actions_with_translations(self, actions: Dict, translations: Dict, language_suffix: str):
        """Update actions with translations for a specified language."""
        for action_name, action_details in actions.items():
            # Get UI label and description
            ui_label_key = action_details.get("label-ui")
            ui_description_key = action_details.get("description-ui")

            if ui_label_key:
                ui_label_key = ui_label_key.lstrip("@")
                action_details[f"action-label-{language_suffix}"] = translations.get(ui_label_key, "")
            else:
                action_details[f"action-label-{language_suffix}"] = ""

            if ui_description_key:
                ui_description_key = ui_description_key.lstrip("@")
                action_details[f"action-description-{language_suffix}"] = translations.get(ui_description_key, "")
            else:
                action_details[f"action-description-{language_suffix}"] = ""

            # Localize keybinding
            keybinding_ui = action_details.get("keyboard-mapping-ui", "")
            if keybinding_ui:
                localized_parts = [
                    translations.get(part.strip().lstrip("@"), part.strip().lstrip("@")) 
                    for part in keybinding_ui.split("+") if part.strip()
                ]
                action_details[f"keyboard-mapping-{language_suffix}"] = "+".join(localized_parts)
            else:
                action_details[f"keyboard-mapping-{language_suffix}"] = ""

    def _localize_keybinding(self, localization_map: Dict, keybinding: str) -> str:
        """Replace key names with their localization strings."""
        if not keybinding or keybinding.isspace():
            return keybinding
        
        parts = keybinding.split("+")
        localized_parts = [localization_map.get(part, part) for part in parts]
        return "+".join(localized_parts)

    def _load_custom_keybinds(self, actions: Dict) -> Dict:
        """
        Load user custom keybindings and merge with default actions.
        
        Args:
            actions: Dictionary of default actions
            
        Returns:
            Updated actions dictionary with custom keybindings merged
        """
        if not self.user_keybinding_file.exists():
            print_debug(f"Custom keybindings file not found: {self.user_keybinding_file}")
            return actions

        print_debug(f"Loading custom keybindings from: {self.user_keybinding_file}")
        tree_layout = ET.parse(str(self.user_keybinding_file))
        root_layout = tree_layout.getroot()

        # Create mapping of action names to custom keybindings
        custom_keybindings = {}
        for actionmap in root_layout.findall(".//actionmap"):
            for action in actionmap.findall(".//action"):
                action_name = action.get("name")
                rebind = action.find(".//rebind")
                if rebind is not None:
                    new_keybinding = self._remove_prefix(rebind.get("input"))
                    custom_keybindings[action_name] = new_keybinding

        # Merge custom keybindings into actions
        custom_count = 0
        for action_name in actions:
            if action_name in custom_keybindings:
                actions[action_name]["keyboard-mapping"] = custom_keybindings[action_name]
                actions[action_name]["keyboard-mapping-custom"] = custom_keybindings[action_name]
                custom_count += 1

        print_debug(f"Merged {custom_count} custom keybindings")
        return actions

    def _remove_prefix(self, keybinding: str) -> str:
        """Remove device prefixes from keybinding (e.g., 'kb1_' from 'kb1_m')."""
        prefix_separator = "_"
        parts = keybinding.split("+")
        cleaned_parts = []
        
        for part in parts:
            prefixed_parts = part.strip().split(prefix_separator)
            if len(prefixed_parts) == 1:
                cleaned_parts.append(prefixed_parts[0])
            elif len(prefixed_parts) == 2:
                cleaned_parts.append(prefixed_parts[1])
        
        return "+".join(cleaned_parts)

    def _create_instant_activation_value(self, commands_to_update: Optional[Dict] = None):
        """
        Generate AI command phrases using OpenAI for commands that don't have them.
        
        Args:
            commands_to_update: Optional dict of commands to generate phrases for.
                              If None, generates for all active commands without phrases.
        """
        if not self.open_api_key:
            print_debug("OpenAI API key not found, skipping command phrase generation")
            return

        print_debug("=" * 80)
        print_debug("Generating command phrases (this may take several minutes)...")
        print_debug("=" * 80)

        keybindings = self._load_sc_all_keybindings()
        
        if commands_to_update is None:
            # Generate for all commands that need phrases
            commands_to_update = {
                name: cmd for name, cmd in keybindings.items()
                if cmd.get('ai_status', {}).get('is_active', False)
                and not cmd.get('command-phrases')
            }

        if not commands_to_update:
            print_debug("No commands need phrase generation")
            return

        # Prepare commands for OpenAI (remove unnecessary fields)
        keybindings_reduce = copy.deepcopy(commands_to_update)
        
        attributes_to_remove = [
            "activationMode",
            "keyboard-mapping",
            "keyboard-mapping-en",
            "keyboard-mapping-default",
            "keyboard-mapping-custom",
            "ai_status",  # Don't send to OpenAI
        ]
        
        for language in self.command_languages:
            attributes_to_remove.append(f"keyboard-mapping-{language}")

        # Remove unnecessary attributes
        keybindings_to_update = {}
        for action, item in keybindings_reduce.items():
            for key in attributes_to_remove:
                item.pop(key, None)
            keybindings_to_update[action] = item

        # Process in chunks
        chunk_size = 20
        total_items = len(keybindings_to_update)
        items_list = list(keybindings_to_update.keys())
        total_chunks = (total_items + chunk_size - 1) // chunk_size
        
        print_debug(f"Processing {total_items} commands in {total_chunks} chunks of {chunk_size}")

        chunk = 0
        index = 0
        
        while index < total_items:
            chunk += 1
            keybindings_chunk = {
                items_list[i]: keybindings_to_update[items_list[i]]
                for i in range(index, min(index + chunk_size, total_items))
            }
            
            print_debug(f"Processing chunk {chunk}/{total_chunks} ({len(keybindings_chunk)} commands)...")
            
            # Generate phrases using OpenAI
            updated_phrases = self._generate_phrases_with_openai(keybindings_chunk, chunk)
            
            if updated_phrases:
                # Merge phrases back into main keybindings
                reference_map = {
                    cmd.get("ai_command_reference_name"): action_name
                    for action_name, cmd in keybindings.items()
                    if cmd.get("ai_command_reference_name")
                }

                matched = 0
                unmatched = []
                for action_name, phrases in updated_phrases.items():
                    resolved_action = None

                    if action_name in keybindings:
                        resolved_action = action_name
                    elif action_name in reference_map:
                        resolved_action = reference_map[action_name]
                    elif isinstance(phrases, dict):
                        fallback_action = phrases.get("actionname")
                        if fallback_action in keybindings:
                            resolved_action = fallback_action
                        elif fallback_action in reference_map:
                            resolved_action = reference_map[fallback_action]

                    if resolved_action:
                        keybindings[resolved_action]["command-phrases"] = phrases.get("command-phrases", {})
                        matched += 1
                    else:
                        unmatched.append(action_name)

                if unmatched:
                    print_debug("⚠️  Some generated phrases did not match any actionname or reference name:")
                    for action_name in unmatched:
                        print_debug(f"   - {action_name}")
                elif matched == 0:
                    print_debug("⚠️  No generated phrases matched actionnames; response keys may be wrong")

                # Save progress after each chunk
                self._save_unified_keybindings(keybindings)
            
            index += chunk_size
        
        print_debug("=" * 80)
        print_debug("Command phrase generation complete!")
        print_debug("=" * 80)

    def _generate_phrases_with_openai(self, commands_chunk: Dict, chunk_number: int) -> Optional[Dict]:
        """
        Generate command phrases for a chunk of commands using OpenAI API.
        
        Returns:
            Dictionary of command phrases, or None if failed
        """
        # Load example files for context
        examples_dir = Path(self.data_root_path)
        example_request_path = examples_dir / "example_keybinds_information.json"
        example_response_path = examples_dir / "response_example.json"
        
        example_request_json = {}
        example_response_json = {}
        
        if example_request_path.exists():
            with open(example_request_path, "r", encoding="utf-8") as file:
                example_request_json = json.load(file)
        
        if example_response_path.exists():
            with open(example_response_path, "r", encoding="utf-8") as file:
                example_response_json = json.load(file)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.open_api_key}",
        }
        model = self.openai_keybinding_generation_model

        messages = [
            {"role": "system", "content": (
                "You are an expert in handling json files and translations. "
                "Your task is to provide good command phrases for star citizen ingame actions that the player executes with keybindings. "
                "You are provided with several json files that contain the description for available actions to be processed by you. "
                "The command phrases should be intuitive, and be in the style of a command a user would call out to somebody that must execute the action. "
                "Each command phrase must only contain the command, nothing else, therefore, it should not contain any abbreviations, punctuation marks or any other non alphanumerical characters. "
                "Further, the sentences should be simple, but they must be unique among all actions you have processed so far. "
                "Try to provide several variations of the command phrases around the main word(s). Try to identify different synonyms for the main word per action and provide variations for these main words as well. Example: 'Landing System' could be also 'Landing Gear' "
                "There should be not more than 2 main word variations and per main word, not more than 5 command phrase variations. The minimum being: 1 one word command phrase, 2 two word command phrases and 1 three word command phrase. "
                f"Apart of en, provide the command-phrases also in the following languages: {self.command_languages}. "
                "The commands should have as much context information as possible, be as precise as possible to match the context of the action within the star citizen context and as short as possible. Try to avoid combined words. "
                "The commands should not provide information on how to execute them. Example: If the description is 'Engage Quantum Drive (Hold)' a bad command phrase would be 'Hold quantum'. A good phrase would be 'Engage Quantum Drive' or 'Quantum Drive' or 'Engage Quantum' or 'Jump'. "
                "Whenever you process an action that is a toggle, extend the command phrases to include both opposite action commands. Example 'Open/Close Doors (Toggle) should lead to the following command phrases: 'Open doors', 'Close doors', 'Doors', 'Toggle doors'. "
                "If the action is a 'cycle', extend the command with command phrase for cycle states you know of. For instance: the action 'Cycle Master Mode' could have the following command-phrases 'Cycle Master Mode', 'Master Mode', 'Next Master Mode', 'Navigation Mode', 'Combat Mode'. "
                "The following jsons are example of the input you receive and corresponding good output:"
                f"Example: Getting the following json with action descriptions: {json.dumps(example_request_json)} "
                f"A good response would be: {json.dumps(example_response_json)} "
            )},
            {"role": "user", "content": (
                "Provide good command phrases for the following actions. "
                "Return a JSON object keyed by the exact ai_command_reference_name for each action. "
                "Each value must contain a 'command-phrases' object with language keys. "
                f"json file: {json.dumps(list(commands_chunk.values()))}"
            )}
        ]

        try:
            payload = {
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": messages
            }

            response = requests.post(
                "https://api.openai.com/v1/chat/completions", 
                headers=headers, 
                json=payload, 
                timeout=300
            )

            response_json = response.json()

            if response_json.get("error", False):
                print(f'Error during OpenAI request: {response_json["error"]["type"]} - {response_json}')
                return None

            # Save raw response for debugging
            raw_response_path = self.version_dir / f"raw_response_{chunk_number}.json"
            with open(raw_response_path, mode="w", encoding="utf-8") as file:
                json.dump(response_json, file, indent=2)

            # Parse generated phrases
            updated_keybindings = response_json["choices"][0]["message"]["content"]
            updated_keybindings = json.loads(updated_keybindings)

            # Save parsed phrases for debugging
            phrases_path = self.version_dir / f"completion_message_command_phrases_{chunk_number}.json"
            with open(phrases_path, mode="w", encoding="utf-8") as file:
                json.dump(updated_keybindings, file, indent=4)

            return updated_keybindings

        except Exception:
            traceback.print_exc()
            return None


# ════════════════════════════════════════════════════════════════════════
# Module Entry Point (for standalone testing)
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # This allows running the script standalone for testing/development
    print("SCKeybindings module - for testing only")
    print("Use parse_and_create_files() to process keybindings")

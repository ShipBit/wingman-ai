"""Native command schema and exact speech matching, with input execution mocked.

Uses the full Core environment; does not send keyboard/mouse input or call models.
"""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from api.interface import CommandConfig
from integrations.elite_dangerous.bindings import generate
from wingmen.open_ai_wingman import OpenAiWingman
from wingmen.wingman import Wingman


class CommandExposureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        bindings, presets = root / "bindings", root / "presets"
        bindings.mkdir()
        presets.mkdir()
        (bindings / "StartPreset.4.start").write_text("Default\n" * 4)
        (presets / "Default.binds").write_text(
            '<Root PresetName="Default"><ShipSpotLightToggle>'
            '<Primary Device="Keyboard" Key="Key_Insert"/>'
            '</ShipSpotLightToggle></Root>')
        commands = [CommandConfig.model_validate(command) for command in generate(bindings, presets)["commands"]]
        self.assertEqual(["ship toggle lights"], [command.name for command in commands])
        self.wingman = SimpleNamespace(
            config=SimpleNamespace(commands=commands), _execute_command=AsyncMock(),
            capability_registry=SimpleNamespace(get_meta_tools=lambda: []),
            skill_registry=SimpleNamespace(get_active_tools=lambda: []),
            mcp_registry=SimpleNamespace(get_active_tools=lambda: []))

    async def test_generated_control_is_in_native_execute_command_schema(self):
        tools = OpenAiWingman.build_tools(self.wingman)
        execute = next(tool["function"] for tool in tools if tool["function"]["name"] == "execute_command")
        self.assertEqual(["ship toggle lights"], execute["parameters"]["properties"]["command_name"]["enum"])
        self.wingman._execute_command.assert_not_called()

    async def test_transcribed_period_matches_exact_shortcut_without_extra_words(self):
        result = await Wingman._execute_instant_activation_command(self.wingman, "Ship toggle lights.")
        self.assertEqual(self.wingman.config.commands, result)
        self.wingman._execute_command.assert_awaited_once_with(result[0], True)
        self.wingman._execute_command.reset_mock()
        result = await Wingman._execute_instant_activation_command(self.wingman, "Do not ship toggle lights.")
        self.assertIsNone(result)
        self.wingman._execute_command.assert_not_called()

    async def test_instant_failure_preserves_error_without_saved_success_response(self):
        self.wingman._execute_command.return_value = (None, "ERROR DURING PROCESSING")
        original = self.wingman.config.commands[0]
        result = await Wingman._execute_instant_activation_command(self.wingman, "Ship toggle lights.")
        self.assertEqual("ERROR DURING PROCESSING", result[0].additional_context)
        self.assertIn("failed", result[0].responses[0])
        self.assertNotEqual("ERROR DURING PROCESSING", original.additional_context)

    async def test_native_input_error_propagates_and_never_logs_executed(self):
        command = self.wingman.config.commands[0]
        self.wingman.name = "Test"
        self.wingman._select_instant_command_response = Mock(return_value="Done")
        async def execute(command):
            await Wingman.execute_action(self.wingman, command)
        self.wingman.execute_action = execute
        printer = SimpleNamespace(print=Mock(), print_async=AsyncMock())
        with patch("wingmen.wingman.printr", printer), patch("wingmen.wingman.keyboard.press", side_effect=OSError("injection failed")):
            response = await Wingman._execute_command(self.wingman, command)
        self.assertEqual((None, "ERROR DURING PROCESSING"), response)
        self.assertFalse(any(str(call.args[0]).startswith("Executed") for call in printer.print_async.call_args_list))

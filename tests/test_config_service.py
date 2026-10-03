"""Shared Core regression; requires the full Core development environment."""

from pathlib import Path
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import yaml

from api.interface import Config, ConfigDirInfo, ConfigWithDirInfo
from services.config_service import ConfigService


class ConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        self.selected = ConfigDirInfo(name="Elite Dangerous", directory="Elite Dangerous", is_default=False, is_deleted=False)
        self.named = ConfigDirInfo(name="Other", directory="Other", is_default=True, is_deleted=False)
        config = Config.model_validate(yaml.safe_load(Path("templates/configs/defaults.yaml").read_text(encoding="utf-8")))
        # Avoid constructor side effects (template copies, audio, migration).
        self.service = object.__new__(ConfigService)
        self.service.current_config_dir = self.selected
        self.service.config_manager = Mock()
        self.service.config_manager.get_config_dir.return_value = self.named
        self.service.config_manager.parse_config.side_effect = lambda directory: (directory, config)
        app = FastAPI()
        app.add_api_route("/config", self.service.get_config, methods=["GET"], response_model=ConfigWithDirInfo)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_omitted_or_empty_name_reads_selected_profile(self):
        for url in ("/config", "/config?config_name="):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(200, response.status_code)
                self.assertEqual("Elite Dangerous", response.json()["config_dir"]["name"])
                self.service.config_manager.parse_config.assert_called_with(self.selected)
        self.service.config_manager.get_config_dir.assert_not_called()

    def test_named_read_does_not_change_current_selection(self):
        response = self.client.get("/config?config_name=Other")
        self.assertEqual(200, response.status_code)
        self.assertEqual("Other", response.json()["config_dir"]["name"])
        self.service.config_manager.get_config_dir.assert_called_once_with("Other")
        self.assertEqual(self.selected, self.service.current_config_dir)

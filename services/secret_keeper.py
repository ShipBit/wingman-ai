import os
from typing import Dict, Any
import yaml
from fastapi import APIRouter
from services.enums import LogType, ToastType
from services.websocket_user import WebSocketUser
from services.printr import Printr

SYSTEM_CONFIG_PATH = "configs/system"
SECRETS_FILE = "secrets.yaml"


class SecretKeeper(WebSocketUser):
    """Singleton"""

    _ws_manager = None
    _instance = None
    printr: Printr
    router: APIRouter
    config_file: str
    secrets: Dict[str, Any]
    prompted_secrets: list[str] = []

    def __new__(cls, app_root_path: str = None):
        if cls._instance is None:
            cls._instance = super(SecretKeeper, cls).__new__(cls)

            cls._instance.printr = Printr()
            cls._instance.router = APIRouter()
            cls._instance.router.add_api_route(
                methods=["GET"],
                path="/secrets",
                endpoint=cls._instance.get_secrets,
                response_model=dict[str, Any],
                tags=["secret"],
            )
            cls._instance.router.add_api_route(
                methods=["POST"],
                path="/secrets",
                endpoint=cls._instance.post_secrets,
                tags=["secret"],
            )

            if app_root_path is None:
                raise ValueError(
                    "app_root_path is required for the first instance of SecretKeeper."
                )

            system_config_path = os.path.join(app_root_path, SYSTEM_CONFIG_PATH)
            cls._instance.config_file = os.path.join(system_config_path, SECRETS_FILE)
            cls._instance.secrets = cls._instance.load() or {}

        return cls._instance

    def load(self) -> Dict[str, Any]:
        if not self.config_file or not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, "r", encoding="UTF-8") as stream:
                return yaml.safe_load(stream) or {}
        except yaml.YAMLError as e:
            self.printr.toast_error(f"Could not load ({SECRETS_FILE})\n{str(e)}")
            return {}

    def save(self) -> bool:
        if not self.config_file:
            self.printr.toast_error("No config file path provided.")
            return False
        try:
            with open(self.config_file, "w", encoding="UTF-8") as stream:
                yaml.dump(self.secrets, stream)
                self.load()
                return True
        except yaml.YAMLError as e:
            self.printr.toast_error(f"Could not write ({SECRETS_FILE})\n{str(e)}")
            return False

    async def retrieve(
        self,
        requester: str,
        key: str,
        prompt_if_missing: bool = True,
    ) -> str:
        if self._ws_manager is None:
            raise ValueError("ws_manager has not been set.")

        secret = self.secrets.get(key, "")
        if not secret and prompt_if_missing and not key in self.prompted_secrets:
            await self._ws_manager.prompt_secret(requester=requester, secret_name=key)
            self.prompted_secrets.append(key)
        return secret

    # GET /secrets
    def get_secrets(self):
        return self.secrets

    # POST /secrets
    def post_secrets(self, secrets: dict[str, Any]):
        self.secrets = secrets
        self.save()
        self.printr.print(
            "Secrets updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
        )

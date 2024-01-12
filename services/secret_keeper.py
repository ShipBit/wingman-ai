from os import path
from typing import Dict, Any
import yaml
from fastapi import APIRouter
from api.commands import PromptSecretCommand
from api.enums import (
    LogType,
    ToastType,
)
from services.config_manager import CONFIGS_DIR, SECRETS_FILE
from services.file import get_writable_dir
from services.websocket_user import WebSocketUser
from services.printr import Printr


class SecretKeeper(WebSocketUser):
    """Singleton"""

    _connection_manager = None
    _instance = None
    printr: Printr
    router: APIRouter
    config_file: str
    secrets: Dict[str, Any]
    prompted_secrets: list[str] = []

    def __new__(cls):
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

            cls._instance.config_file = path.join(
                get_writable_dir(CONFIGS_DIR), SECRETS_FILE
            )
            cls._instance.secrets = cls._instance.load() or {}

        return cls._instance

    def load(self) -> Dict[str, Any]:
        if not self.config_file or not path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, "r", encoding="UTF-8") as stream:
                return yaml.safe_load(stream) or {}
        except yaml.YAMLError as e:
            self.printr.toast_error(f"Could not load ({SECRETS_FILE})\n{str(e)}")
            return {}
        except OSError as e:
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
        except OSError as e:
            self.printr.toast_error(f"Could not create ({SECRETS_FILE})\n{str(e)}")
            return False

    async def retrieve(
        self,
        requester: str,
        key: str,
        prompt_if_missing: bool = True,
    ) -> str:
        if self._connection_manager is None:
            raise ValueError("connection_manager has not been set.")

        secret = self.secrets.get(key, "")
        if not secret and prompt_if_missing and not key in self.prompted_secrets:
            await self._connection_manager.broadcast(
                PromptSecretCommand(requester=requester, secret_name=key)
            )
            self.prompted_secrets.append(key)
        return secret

    # GET /secrets
    def get_secrets(self):
        return self.secrets

    # POST /secrets
    def post_secrets(self, secrets: dict[str, Any]):
        if not secrets or len(secrets) == 0:
            return

        self.secrets = secrets
        self.save()
        self.printr.print(
            "Secrets updated.", toast=ToastType.NORMAL, color=LogType.POSITIVE
        )

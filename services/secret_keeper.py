import os
import yaml
import customtkinter as ctk
from services.printr import Printr

SYSTEM_CONFIG_PATH = "configs/system"
SECRETS_FILE = "secrets.yaml"


class SecretKeeper:
    def __init__(self, app_root_path: str):
        self.printr = Printr()
        self.system_config_path: str = os.path.join(app_root_path, SYSTEM_CONFIG_PATH)
        self.config_file = os.path.join(self.system_config_path, SECRETS_FILE)
        self.secrets = self.__load()
        if not self.secrets:
            self.secrets = {}

    def __load(self) -> dict[str, any]:  # type: ignore
        parsed_config = None

        if os.path.exists(self.config_file) and os.path.isfile(self.config_file):
            with open(self.config_file, "r", encoding="UTF-8") as stream:
                try:
                    parsed_config = yaml.safe_load(stream)
                except yaml.YAMLError as e:
                    self.printr.print_err(
                        f"Could not load ({SECRETS_FILE})\n{str(e)}", True
                    )

        return parsed_config

    def save(self):
        """Write all secrets to the file"""
        with open(self.config_file, "w", encoding="UTF-8") as stream:
            try:
                yaml.dump(self.secrets, stream)
                return True
            except yaml.YAMLError as e:
                self.printr.print_err(
                    f"Could not write ({SECRETS_FILE})\n{str(e)}", True
                )
                return False

    def retrieve(
        self,
        requester: str,
        key: str,
        friendly_key_name: str,
        prompt_if_missing: bool = True,
    ) -> str:
        """Retrieve secret a secret and optionally prompt user for it if missing"""

        secret = self.secrets.get(key, None)
        if not secret and prompt_if_missing:
            # Prompt user for key
            dialog = ctk.CTkInputDialog(
                text=f"Please enter '{friendly_key_name}':",
                title=f"{requester} needs to know a secret",
            )
            secret = dialog.get_input()
            if secret:
                secret = secret.strip().replace("\n", "")
            self.secrets[key] = secret
            self.save()

        return secret

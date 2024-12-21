from skills.uexcorp_beta.uexcorp.helper import Helper
from skills.uexcorp_beta.uexcorp.tool.validator import Validator


class Tool:

    def __init__(self):
        self._helper = Helper.get_instance()

    def execute(self, **kwargs) -> str:
        # already validated here
        pass

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {}

    def get_description(self) -> str:
        return ""
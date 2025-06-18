try:
    from skills.uexcorp.uexcorp.helper import Helper
    from skills.uexcorp.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp.uexcorp.helper import Helper
    from uexcorp.uexcorp.tool.validator import Validator


class Tool:
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "UNDEFINED"

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

    def get_prompt(self) -> str:
        return self.get_description()

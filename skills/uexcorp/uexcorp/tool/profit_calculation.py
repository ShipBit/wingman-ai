from skills.uexcorp.uexcorp import compression
from skills.uexcorp.uexcorp.tool.tool import Tool
from skills.uexcorp.uexcorp.tool.validator import Validator


class ProfitCalculation(Tool):
    REQUIRES_AUTHENTICATION = False
    TOOL_NAME = "uex_calculate_profit"

    def __init__(self):
        super().__init__()

    def execute(
        self,
        buy_price: float | None = None,
        sell_price: float | None = None,
        quantity: int | None = 1,
    ) -> (str, str):
        if quantity is None:
            quantity = 1

        if not all([
            buy_price,
            sell_price,
        ]) or buy_price < 0 or sell_price < 0 or quantity < 0:
            return "buy_price and sell_price is needed. As at least one is missing, try to get the value from other uex-functions first and then call this tool again.", ""

        # Units (aUEC / %) are documented once in the tool help prompt.
        data = {
            "buy_price": buy_price, # 1000
            "sell_price": sell_price, # 2000
            "quantity": quantity, # 5
            "profit": sell_price - buy_price, # 1000
            "profit_total": (sell_price - buy_price) * quantity, # 5000
            "base_profit_percent": round(((sell_price / buy_price) - 1) * 100, 2), # 100
            "profit_margin_percent": round(((sell_price - buy_price) / sell_price) * 100, 2), # 50
        }
        return compression.dumps(data), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {
            "buy_price": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Price the player pays per unit (per SCU for commodities) in aUEC, e.g. 1000.",
                config={"min": 1},
            ),
            "sell_price": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Price the player gets per unit (per SCU for commodities) in aUEC, e.g. 2000.",
                config={"min": 1},
            ),
        }

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "quantity": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Number of units (SCU for commodities), e.g. 10. Default 1.",
                config={"min": 1},
            ),
        }

    def get_description(self) -> str:
        return (
            "Calculates profit in aUEC (per unit and total), profit margin in % and base profit in % "
            "from a buy price and a sell price. Use it whenever a profit or margin is asked for, instead of calculating yourself."
        )

    def get_prompt(self) -> str:
        return (
            "Always use this for profit, profit margin or base profit; never calculate them yourself. "
            "If the user did not give a buy or sell price, get it from uex_get_commodity_information first, "
            "only ask the user if no price is found, then call this function."
        )

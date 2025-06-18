import json
try:
    from skills.uexcorp.uexcorp.tool.tool import Tool
    from skills.uexcorp.uexcorp.tool.validator import Validator
except ModuleNotFoundError:
    from uexcorp.uexcorp.tool.tool import Tool
    from uexcorp.uexcorp.tool.validator import Validator


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

        data = {
            "buy_price": f"{buy_price} aUEC", # 1000
            "sell_price": f"{sell_price} aUEC", # 2000
            "quantity": quantity, # 5
            "profit": f"{(sell_price - buy_price)} aUEC", # 1000
            "profit_total": f"{(sell_price - buy_price) * quantity} aUEC", # 5000
            "base_profit": f"{round(((sell_price / buy_price) -1 ) * 100, 2)}%", # 100%
            "profit_margin": f"{round(((sell_price - buy_price) / sell_price) * 100, 2)}%", # 50%
        }
        return json.dumps(data), ""

    def get_mandatory_fields(self) -> dict[str, Validator]:
        return {}

    def get_optional_fields(self) -> dict[str, Validator]:
        return {
            "quantity": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Provide the quantity of items. Defaults to 1. Must be > 0 if given. (e.g. 10)",
                config={"min": 1},
            ),
            "buy_price": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Provide the buy price of the item. Must be > 0. (e.g. 1000)",
                config={"min": 1},
            ),
            "sell_price": Validator(
                Validator.VALIDATE_NUMBER,
                multiple=False,
                prompt="Provide the sell price of the item. Must be > 0. (e.g. 2000)",
                config={"min": 1},
            ),
        }

    def get_description(self) -> str:
        return "Calculates the profit (absolute), profit margin (in %) and base profit (in %) for a given buy and sell price."

    def get_prompt(self) -> str:
        return "Always use this function to calculate profit, profit margin (in %) and base profit (in %) for a given buy and sell price. Never calculate it 'on your own'. If a mandatory parameter is not given, try to get missing data, like sell price, from other uex functions BEFORE asking the user for it AND ALWAYS execute this tool afterwards to get accurate profit data."

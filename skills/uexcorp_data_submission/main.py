import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import asdict, dataclass

import requests
from requests.exceptions import RequestException

from api.enums import LogType, WingmanInitializationErrorType
from api.interface import WingmanInitializationError, SkillConfig, SettingsConfig
from skills.uexcorp.main import UEXCorp

logger = logging.getLogger(__name__)


@dataclass
class VerifiedData:
    terminal_id: int
    faction_affinity: int
    game_version: str
    prices: List[Dict[str, Any]]
    screenshot: str


class UEXCorpDataSubmission(UEXCorp):
    def __init__(
        self, config: SkillConfig, settings: SettingsConfig, wingman: "OpenAiWingman"
    ):
        super().__init__(config=config, settings=settings, wingman=wingman)

        errors: List[WingmanInitializationError] = []

        self.api_url = self.retrieve_custom_property_value(
            "uexcorp_api_url", "https://uexcorp.space/api/2.0"
        )
        self.max_retries = self.retrieve_custom_property_value("max_retries", 3)
        self.retry_delay = self.retrieve_custom_property_value("retry_delay", 2)

        self.api_key = None
        self.verified_data = None

        if errors:
            error_messages = "\n".join(error.message for error in errors)
            self.printr.print(
                f"Initialization warnings occurred:\n{error_messages}",
                color=LogType.WARNING,
            )

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.api_key = await self.secret_keeper.retrieve(
            requester=self.name,
            key="uexcorp",
            prompt_if_missing=True,
        )

        if not self.api_key:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.name,
                    message="Missing UEX Corp API key",
                    error_type=WingmanInitializationErrorType.MISSING_SECRET,
                    secret_name="uexcorp",
                )
            )

        # Check for required skills
        required_skills = ["auto_screenshot", "vision_ai"]
        for skill_name in required_skills:
            if not any(skill.name == skill_name for skill in self.wingman.skills):
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.name,
                        message=f"Missing required skill: {skill_name}",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

        return errors

    def get_tools(self) -> List[tuple[str, Dict]]:
        return [
            (
                "capture_and_verify_trading_terminal_data",
                {
                    "type": "function",
                    "function": {
                        "name": "capture_and_verify_trading_terminal_data",
                        "description": "Capture a screenshot of a Star Citizen commodity terminal, extract data, and verify it",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location_description": {
                                    "type": "string",
                                    "description": "Description of the terminal location",
                                },
                            },
                            "required": ["location_description"],
                        },
                    },
                },
            ),
            (
                "submit_verified_data_to_uexcorp",
                {
                    "type": "function",
                    "function": {
                        "name": "submit_verified_data_to_uexcorp",
                        "description": "Submit verified trading terminal data to UEX Corp",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                },
            ),
        ]

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any]
    ) -> tuple[str, str]:
        if tool_name == "capture_and_verify_trading_terminal_data":
            return await self.capture_and_verify_trading_terminal_data(**parameters)
        return "", ""

    async def capture_and_verify_trading_terminal_data(
        self, location_description: str
    ) -> tuple[str, str]:
        try:
            terminal = await self.fuzzy_search_terminal(location_description)
            if not terminal:
                raise ValueError(f"Terminal not found for: {location_description}")

            auto_screenshot_skill = self.wingman.get_skill("auto_screenshot")
            if not auto_screenshot_skill:
                raise ValueError("Auto Screenshot skill is not available")
            screenshot = await auto_screenshot_skill.take_screenshot(
                "Capturing commodity terminal"
            )

            vision_ai_skill = self.wingman.get_skill("vision_ai")
            if not vision_ai_skill:
                raise ValueError("Vision AI skill is not available")
            extracted_data = await vision_ai_skill.analyse_image(
                screenshot, self.get_vision_ai_prompt()
            )

            verified_data = await self.process_and_validate_data(
                terminal["id"], extracted_data, screenshot
            )

            self.verified_data = verified_data

            return (
                f"Data captured and verified for {location_description}. Ready for submission.",
                "",
            )
        except ValueError as ve:
            return str(ve), ""
        except Exception as e:
            error_msg = f"Error in capture_and_verify_trading_terminal_data: {str(e)}"
            self.printr.print(error_msg, color=LogType.ERROR)
            return error_msg, ""

    async def submit_verified_data_to_uexcorp(self) -> tuple[str, str]:
        try:
            if self.verified_data is None:
                return (
                    "No verified data available for submission. Please capture and verify data first.",
                    "",
                )

            response = await self.submit_data_to_uexcorp(asdict(self.verified_data))
            return f"Data submitted successfully: {response}", ""
        except Exception as e:
            error_msg = f"Error in submit_verified_data_to_uexcorp: {str(e)}"
            self.printr.print(error_msg, color=LogType.ERROR)
            return error_msg, ""

    async def process_and_validate_data(
        self, terminal_id: int, extracted_data: Dict[str, Any], screenshot: str
    ) -> VerifiedData:
        processed_data = self.process_extracted_data(terminal_id, extracted_data)
        self.validate_processed_data(processed_data)

        verified_data = VerifiedData(
            terminal_id=terminal_id,
            faction_affinity=processed_data["faction_affinity"],
            game_version=await self.get_game_version(),
            prices=processed_data["prices"],
            screenshot=self.get_base64_screenshot(screenshot),
        )

        return verified_data

    def validate_processed_data(self, processed_data: Dict[str, Any]):
        if not isinstance(processed_data["prices"], list):
            raise ValueError(
                f"'prices' should be a list, got {type(processed_data['prices'])}"
            )

        if not processed_data["prices"]:
            raise ValueError("No valid commodity data extracted")

        if not -100 <= processed_data["faction_affinity"] <= 100:
            raise ValueError(
                f"Invalid faction affinity: {processed_data['faction_affinity']}"
            )

        for price_data in processed_data["prices"]:
            if "status_buy" in price_data and not 1 <= price_data["status_buy"] <= 7:
                raise ValueError(f"Invalid status_buy: {price_data['status_buy']}")
            if "status_sell" in price_data and not 1 <= price_data["status_sell"] <= 7:
                raise ValueError(f"Invalid status_sell: {price_data['status_sell']}")

    def find_commodity_id(self, commodity_name: str) -> int | None:
        """
        Find the commodity ID using the name.

        Args:
            commodity_name (str): The name of the commodity to search for.

        Returns:
            int | None: The ID of the commodity if found, None otherwise.
        """
        commodity = self._get_commodity_by_name(commodity_name)
        if commodity:
            return commodity["id"]
        return None

    def process_extracted_data(
        self, terminal_id: int, extracted_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        processed_data = {
            "id_terminal": terminal_id,
            "type": "commodity",
            "is_production": 0,
            "faction_affinity": extracted_data.get("faction_affinity", 0),
            "prices": [],  # Ensure this is initialized as a list
        }

        for commodity in extracted_data.get("commodities", []):
            commodity_id = self.find_commodity_id(commodity["name"])
            if commodity_id is None:
                self.printr.print(
                    f"Unknown commodity: {commodity['name']}", color=LogType.WARNING
                )
                continue

            commodity_data = {"id_commodity": commodity_id}

            if "buy_price" in commodity:
                commodity_data.update(
                    {
                        "price_buy": commodity["buy_price"],
                        "scu_buy": commodity.get("buy_quantity", 0),
                        "status_buy": commodity.get("buy_status", 1),
                    }
                )

            if "sell_price" in commodity:
                commodity_data.update(
                    {
                        "price_sell": commodity["sell_price"],
                        "scu_sell": commodity.get("sell_quantity", 0),
                        "status_sell": commodity.get("sell_status", 1),
                    }
                )

            if not isinstance(processed_data["prices"], list):
                raise TypeError("processed_data['prices'] should be a list")

            # Is this the source of the error?
            processed_data["prices"].append(commodity_data)

        self.validate_processed_data(processed_data)
        return processed_data

    def get_base64_screenshot(self, screenshot: str) -> str:
        return base64.b64encode(screenshot.encode()).decode("utf-8")

    async def submit_data_to_uexcorp(self, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"secret_key": self.api_key}
        url = f"{self.api_url}/data_submit"

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    url,
                    json=data,
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                if attempt == self.max_retries - 1:
                    raise
                self.printr.print(
                    f"Request failed, retrying ({attempt + 1}/{self.max_retries}): {str(e)}",
                    color=LogType.WARNING,
                )
                await asyncio.sleep(
                    self.retry_delay * (2**attempt)
                )  # Exponential backoff

    def get_vision_ai_prompt(self) -> str:
        return """
        Analyze this Star Citizen commodity terminal screenshot and extract the following information in a structured format:
        - Faction affinity (if visible)
        - Game version (if visible)
        - List of commodities with their buy or sell information

        For each commodity, provide:
        - Commodity name (exactly as shown)
        - Buy price (if available)
        - Sell price (if available)
        - Buy quantity/SCU (if available)
        - Sell quantity/SCU (if available)
        - Buy status (1-7, where 1 is out of stock and 7 is maximum inventory)
        - Sell status (1-7, where 1 is out of stock and 7 is maximum inventory)

        Output the data in the following JSON structure:
        {
            "faction_affinity": int,
            "commodities": [
                {
                    "name": string,
                    "buy_price": float,
                    "sell_price": float,
                    "buy_quantity": int,
                    "sell_quantity": int,
                    "buy_status": int,
                    "sell_status": int
                },
                ...
            ]
        }
        """

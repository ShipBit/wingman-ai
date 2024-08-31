import base64
import difflib
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException

from api.enums import LogType, WingmanInitializationErrorType
from api.interface import WingmanInitializationError, SkillConfig, SettingsConfig
from skills.uexcorp.main import UEXCorp

logger = logging.getLogger(__name__)


class UEXCorpDataSubmission(UEXCorp):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self.api_url = self.config.custom_properties.get(
            "api_url", "https://uexcorp.space/api/2.0"
        )
        self.max_retries = self.config.custom_properties.get("max_retries", 3)
        self.retry_delay = self.config.custom_properties.get("retry_delay", 2)
        self.ensure_data_loaded()
        self.api_key = self.secret_keeper.retrieve(
            requester=self.name,
            key="uexcorp",
            prompt_if_missing=True,
        )
        self.verified_data = None

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

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
        elif tool_name == "submit_verified_data_to_uexcorp":
            return await self.submit_verified_data_to_uexcorp()
        return "", ""

    async def capture_and_verify_trading_terminal_data(
        self, location_description: str
    ) -> tuple[str, str]:
        try:
            terminal_id = await self.get_terminal_id(location_description)

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

            processed_data = self.process_extracted_data(terminal_id, extracted_data)
            processed_data["screenshot"] = self.get_base64_screenshot(screenshot)

            self.verified_data = processed_data
            return (
                f"Data captured and verified for {location_description}. Ready for submission.",
                "",
            )
        except Exception as e:
            error_msg = f"Error in capture_and_verify_trading_terminal_data: {str(e)}"
            self.printr.print(error_msg, color=LogType.ERROR)
            return error_msg, ""

    async def submit_verified_data_to_uexcorp(self) -> tuple[str, str]:
        if not self.verified_data:
            return (
                "No verified data available for submission. Please capture and verify data first.",
                "",
            )

        try:
            response = self.submit_data_to_uexcorp(self.verified_data)
            self.verified_data = None  # Clear the data after submission
            return f"Data submitted successfully: {response}", ""
        except Exception as e:
            error_msg = f"Error in submit_verified_data_to_uexcorp: {str(e)}"
            self.printr.print(error_msg, color=LogType.ERROR)
            return error_msg, ""

    def process_extracted_data(
        self, terminal_id: int, extracted_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        processed_data = {
            "id_terminal": terminal_id,
            "type": "commodity",
            "is_production": 0,
            "faction_affinity": extracted_data.get("faction_affinity", 0),
            "game_version": self.game_version,  # Use the fetched game version
            "prices": [],
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

            processed_data["prices"].append(commodity_data)

        self.validate_processed_data(processed_data)
        return processed_data

    async def update_game_version(self):
        """Fetch the current game version from the /commodities_prices endpoint"""
        try:
            url = f"{self.api_url}/commodities_prices"
            response = await self._fetch_uex_data(url)
            if response and len(response) > 0:
                self.game_version = response[0].get("game_version")
                self.printr.print(
                    f"Updated game version: {self.game_version}", color=LogType.INFO
                )
            else:
                self.printr.print("Failed to fetch game version", color=LogType.WARNING)
        except Exception as e:
            self.printr.print(f"Error fetching game version: {e}", color=LogType.ERROR)

    def validate_processed_data(self, processed_data: Dict[str, Any]):
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

    async def find_commodity_id(self, commodity_name: str) -> int | None:
        """
        Find the commodity ID using a fuzzy name match.

        Args:
            commodity_name (str): The name of the commodity to search for.

        Returns:
            int | None: The ID of the commodity if found, None otherwise.
        """
        url = f"{self.uexcorp_api_url}/commodities"
        params = {"commodity_name": commodity_name}

        try:
            response = await self._fetch_uex_data(url, params)
            if response and len(response) > 0:
                return response[0]["id"]
        except Exception as e:
            await self._print(f"Error finding commodity ID: {e}")

        return None

    def get_base64_screenshot(self, screenshot: str) -> str:
        return base64.b64encode(screenshot.encode()).decode("utf-8")

    async def get_terminal_id(self, terminal_name: str) -> int | None:
        """
        Get the terminal ID using a fuzzy name match.

        Args:
            terminal_name (str): The name of the terminal to search for.

        Returns:
            int | None: The ID of the terminal if found, None otherwise.
        """
        url = f"{self.uexcorp_api_url}/terminals"
        params = {"name": terminal_name}

        try:
            response = await self._fetch_uex_data(url, params)
            if response and len(response) > 0:
                return response[0]["id"]
        except Exception as e:
            await self._print(f"Error getting terminal ID: {e}")

        return None

    async def _fetch_uex_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        """
        Fetches data from the specified endpoint.

        Args:
            endpoint (str): The API endpoint to fetch data from.
            params (Optional[dict[str, any]]): Optional parameters to include in the request.

        Returns:
            list[dict[str, any]]: The fetched data as a list of dictionaries.
        """
        url = f"{endpoint}"
        await self._print(f"Fetching data from {url} with params {params}...", True)

        request_count = 1
        timeout_error = False
        requests_error = False

        while request_count == 1 or (
            request_count <= (self.uexcorp_api_timeout_retries + 1) and timeout_error
        ):
            if requests_error:
                await self._print(f"Retrying request #{request_count}...", True)
                requests_error = False

            timeout_error = False
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=(self.uexcorp_api_timeout * request_count),
                    headers=self._get_header(),
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                await self._print(f"Error while retrieving data from {url}: {e}")
                requests_error = True
                if isinstance(e, requests.exceptions.Timeout):
                    timeout_error = True
            request_count += 1

        if requests_error:
            return []

        response_json = response.json()
        if "status" not in response_json or response_json["status"] != "ok":
            await self._print(f"Error while retrieving data from {url}")
            return []

        return response_json.get("data", [])

    def submit_data_to_uexcorp(self, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"secret_key": self.api_key}
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.uexcorp_api_url}/data_submit",
                    json=data,
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                if attempt == max_retries - 1:
                    raise
                self.printr.print(
                    f"Request failed, retrying ({attempt + 1}/{max_retries}): {str(e)}",
                    color=LogType.WARNING,
                )
                time.sleep(2**attempt)  # Exponential backoff

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

    def ensure_data_loaded(self):
        if not self.commodities or not self.terminals:
            self._load_data()

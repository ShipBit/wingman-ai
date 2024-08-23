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
            "api_url", "https://uexcorp.space/api/2.0/data_submit"
        )
        self.max_retries = self.config.custom_properties.get("max_retries", 3)
        self.retry_delay = self.config.custom_properties.get("retry_delay", 2)
        self.ensure_data_loaded()
        self.api_key = self.secret_keeper.retrieve(
            requester=self.name,
            key="uexcorp",
            prompt_if_missing=True,
        )

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
        return errors

    def get_tools(self) -> List[tuple[str, Dict]]:
        return [
            (
                "capture_and_submit_terminal_data",
                {
                    "type": "function",
                    "function": {
                        "name": "capture_and_submit_terminal_data",
                        "description": "Capture a screenshot of a Star Citizen commodity terminal, extract data, and submit to UEX Corp",
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
            )
        ]

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any]
    ) -> tuple[str, str]:
        if tool_name == "capture_and_submit_terminal_data":
            return await self.capture_and_submit_terminal_data(**parameters)
        return "", ""

    async def capture_screenshot(self) -> str:
        auto_screenshot_skill = self.wingman.get_skill("auto_screenshot")
        return await auto_screenshot_skill.take_screenshot(
            "Capturing commodity terminal"
        )

    async def extract_data_from_screenshot(self, screenshot: str) -> Dict[str, Any]:
        vision_ai_skill = self.wingman.get_skill("vision_ai")
        prompt = """
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
            "game_version": string,
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
        extracted_data = await vision_ai_skill.analyse_image(screenshot, prompt)
        try:
            return json.loads(extracted_data)
        except json.JSONDecodeError:
            raise ValueError("Failed to parse structured data from Vision AI output")

    def process_extracted_data(
        self, terminal_id: int, extracted_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        processed_data = {
            "id_terminal": terminal_id,
            "type": "commodity",
            "is_production": 0,
            "faction_affinity": extracted_data.get("faction_affinity", 0),
            "game_version": extracted_data.get("game_version", self.get_game_version()),
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

    def find_commodity_id(self, name: str) -> Optional[int]:
        best_match = difflib.get_close_matches(
            name, [c["name"] for c in self.commodities], n=1, cutoff=0.8
        )
        if best_match:
            matched_commodity = next(
                c for c in self.commodities if c["name"] == best_match[0]
            )
            return matched_commodity["id"]
        return None

    def get_game_version(self) -> str:
        # TODO: Implement dynamic game version retrieval
        return "3.23.1"

    def get_base64_screenshot(self, screenshot: str) -> str:
        return base64.b64encode(screenshot.encode()).decode("utf-8")

    async def get_terminal_id(self, location_description: str) -> int:
        terminal_descriptions = [
            f"{t['nickname']} at {t['star_system_name']} - {t['planet_name'] or t['moon_name'] or t['orbit_name']}"
            for t in self.terminals
        ]

        prompt = f"""
        Find the best matching terminal for this description: '{location_description}'.
        Here are the available terminals:
        {json.dumps(terminal_descriptions)}
        Return only the index of the best matching terminal (0-based).
        """

        terminal_index = await self.llm_call([{"role": "user", "content": prompt}])

        try:
            index = int(terminal_index.strip())
            return self.terminals[index]["id"]
        except (ValueError, IndexError):
            raise ValueError(
                f"Failed to find a matching terminal for: {location_description}"
            )

    def submit_data_to_uexcorp(self, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"secret_key": self.api_key}
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, json=data, headers=headers, timeout=10
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

    async def capture_and_submit_terminal_data(
        self, location_description: str
    ) -> tuple[str, str]:
        try:
            terminal_id = await self.get_terminal_id(location_description)
            screenshot = await self.capture_screenshot()
            extracted_data = await self.extract_data_from_screenshot(screenshot)
            processed_data = self.process_extracted_data(terminal_id, extracted_data)
            processed_data["screenshot"] = self.get_base64_screenshot(screenshot)

            response = self.submit_data_to_uexcorp(processed_data)
            return f"Data submitted successfully: {response}", ""
        except Exception as e:
            error_msg = f"Error in capture_and_submit_terminal_data: {str(e)}"
            self.printr.print(error_msg, color=LogType.ERROR)
            return error_msg, ""

    def ensure_data_loaded(self):
        if not self.commodities or not self.terminals:
            self._load_data()

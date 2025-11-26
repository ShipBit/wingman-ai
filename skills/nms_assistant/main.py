import requests
from typing import TYPE_CHECKING
from api.enums import LogType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill, tool
import asyncio

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

API_BASE_URL = "https://api.nmsassistant.com"


class NMSAssistant(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    async def request_api(self, endpoint: str) -> dict:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"API request failed to {API_BASE_URL}{endpoint}, status code: {response.status_code}.",
                    color=LogType.INFO,
                )
            return {}

    async def parse_nms_assistant_api_response(self, api_response) -> dict:
        def extract_app_ids(data):
            app_ids = []
            for entry in data:
                app_ids.append(entry["appId"])
                for input_item in entry["inputs"]:
                    app_ids.append(input_item["appId"])
                app_ids.append(entry["output"]["appId"])
            return app_ids

        app_ids = extract_app_ids(api_response)

        async def fetch_item_name(app_id: str) -> str:
            data = await self.request_api(f"/ItemInfo/{app_id}/en")
            return data.get("name", "Unknown")

        tasks = [fetch_item_name(item) for item in app_ids]
        results = await asyncio.gather(*tasks)
        return {item: name for item, name in zip(app_ids, results)}

    async def check_if_appId_is_valid(self, appId, languageCode) -> bool:
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Checking if appID {appId} is valid before proceeding.",
                color=LogType.INFO,
            )
        check_response = await self.request_api(f"/ItemInfo/{appId}/{languageCode}")
        if check_response and check_response != {}:
            return True
        else:
            return False

    @tool(
        name="get_release_info",
        description="Fetch release information from No Man's Sky website. Use for questions about NMS updates, patches, version info, or latest releases.",
        wait_response=True,
    )
    async def get_release_info(self) -> str:
        """Fetch release information from No Man's Sky website."""
        data = await self.request_api("/HelloGames/Release")
        return str(data) if data else "Operation failed."

    @tool(
        name="get_news",
        description="Fetch news from No Man's Sky website. Use for NMS announcements, Hello Games news, or game-related updates.",
        wait_response=True,
    )
    async def get_news(self) -> str:
        """Fetch news from No Man's Sky website."""
        data = await self.request_api("/HelloGames/News")
        return str(data) if data else "Operation failed."

    @tool(
        name="get_community_mission_info",
        description="Fetch current community mission information.",
        wait_response=True,
    )
    async def get_community_mission_info(self) -> str:
        """Fetch current community mission information."""
        data = await self.request_api("/HelloGames/CommunityMission")
        return str(data) if data else "Operation failed."

    @tool(
        name="get_latest_expedition_info",
        description="Fetch latest expedition information.",
        wait_response=True,
    )
    async def get_latest_expedition_info(self) -> str:
        """Fetch latest expedition information."""
        data = await self.request_api("/HelloGames/Expedition")
        return str(data) if data else "Operation failed."

    @tool(
        name="get_item_info_by_name",
        description="Fetch No Man's Sky game item details. Use when user asks about crafting materials, resources, blueprints, or any in-game item properties.",
        wait_response=True,
    )
    async def get_item_info_by_name(self, name: str, languageCode: str) -> str:
        """
        Args:
            name: The name of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        data = await self.request_api(f"/ItemInfo/Name/{name}/{languageCode}")
        return str(data) if data else "Operation failed."

    @tool(
        name="get_extra_item_info",
        description="Fetch extra item details using appId.",
        wait_response=True,
    )
    async def get_extra_item_info(self, appId: str, languageCode: str) -> str:
        """
        Args:
            appId: The appId of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        app_id_found = await self.check_if_appId_is_valid(appId, languageCode)
        if not app_id_found:
            name_check = await self.request_api(
                f"/ItemInfo/Name/{appId}/{languageCode}"
            )
            appId = name_check.get("appId") if name_check else appId
        data = await self.request_api(
            f"/ItemInfo/ExtraProperties/{appId}/{languageCode}"
        )
        return str(data) if data else "Operation failed."

    @tool(
        name="get_refiner_recipes_by_input",
        description="Fetch NMS refiner recipes by input item. Use when user asks 'what can I make with X?' or wants to know refining options for materials.",
        wait_response=True,
    )
    async def get_refiner_recipes_by_input(self, appId: str, languageCode: str) -> str:
        """
        Args:
            appId: The appId of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        app_id_found = await self.check_if_appId_is_valid(appId, languageCode)
        if not app_id_found:
            name_check = await self.request_api(
                f"/ItemInfo/Name/{appId}/{languageCode}"
            )
            appId = name_check.get("appId") if name_check else appId
        data = await self.request_api(
            f"/ItemInfo/RefinerByInput/{appId}/{languageCode}"
        )
        if data:
            parsed_data = await self.parse_nms_assistant_api_response(data)
            return f"{data}; key for item names used in above data: {parsed_data}"
        return "Operation failed."

    @tool(
        name="get_refiner_recipes_by_output",
        description="Fetch NMS refiner recipes to produce a specific item. Use when user asks 'how do I make X?' or 'what's the recipe for X?'",
        wait_response=True,
    )
    async def get_refiner_recipes_by_output(self, appId: str, languageCode: str) -> str:
        """
        Args:
            appId: The appId of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        app_id_found = await self.check_if_appId_is_valid(appId, languageCode)
        if not app_id_found:
            name_check = await self.request_api(
                f"/ItemInfo/Name/{appId}/{languageCode}"
            )
            appId = name_check.get("appId") if name_check else appId
        data = await self.request_api(
            f"/ItemInfo/RefinerByOutut/{appId}/{languageCode}"
        )
        if data:
            parsed_data = await self.parse_nms_assistant_api_response(data)
            return f"{data}; key for item names used in above data: {parsed_data}"
        return "Operation failed."

    @tool(
        name="get_cooking_recipes_by_input",
        description="Fetch cooking recipes by input item using appId.",
        wait_response=True,
    )
    async def get_cooking_recipes_by_input(self, appId: str, languageCode: str) -> str:
        """
        Args:
            appId: The appId of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        app_id_found = await self.check_if_appId_is_valid(appId, languageCode)
        if not app_id_found:
            name_check = await self.request_api(
                f"/ItemInfo/Name/{appId}/{languageCode}"
            )
            appId = name_check.get("appId") if name_check else appId
        data = await self.request_api(
            f"/ItemInfo/CookingByInput/{appId}/{languageCode}"
        )
        if data:
            parsed_data = await self.parse_nms_assistant_api_response(data)
            return f"{data}; key for item names used in above data: {parsed_data}"
        return "Operation failed."

    @tool(
        name="get_cooking_recipes_by_output",
        description="Fetch cooking recipes by output item using appId.",
        wait_response=True,
    )
    async def get_cooking_recipes_by_output(self, appId: str, languageCode: str) -> str:
        """
        Args:
            appId: The appId of the item.
            languageCode: The language code (e.g., 'en' for English).
        """
        app_id_found = await self.check_if_appId_is_valid(appId, languageCode)
        if not app_id_found:
            name_check = await self.request_api(
                f"/ItemInfo/Name/{appId}/{languageCode}"
            )
            appId = name_check.get("appId") if name_check else appId
        data = await self.request_api(
            f"/ItemInfo/CookingByOutut/{appId}/{languageCode}"
        )
        if data:
            parsed_data = await self.parse_nms_assistant_api_response(data)
            return f"{data}; key for item names used in above data: {parsed_data}"
        return "Operation failed."

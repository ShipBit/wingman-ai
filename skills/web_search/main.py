import time
import math
from copy import deepcopy
from typing import TYPE_CHECKING
from duckduckgo_search import DDGS
from trafilatura import fetch_url, extract
from trafilatura.settings import DEFAULT_CONFIG
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

class WebSearch(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

        # behavior
        self.max_time = 5
        self.max_results = 5
        self.min_results = 2
        self.max_result_size = 4000

        self.trafilatura_config = deepcopy(DEFAULT_CONFIG)
        self.trafilatura_config['DEFAULT']['DOWNLOAD_TIMEOUT'] = f"{math.ceil(self.max_time/2)}"
        self.trafilatura_config['DEFAULT']['MAX_REDIRECTS '] = '3'


    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "web_search_function",
                {
                    "type": "function",
                    "function": {
                        "name": "web_search_function",
                        "description": "Searches the internet / web for the topic identified by the user or identified by the AI to answer a user question.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "search_query": {
                                    "type": "string",
                                    "description": "The topic to search the internet for.",
                                },
                                "search_type": {
                                    "type": "string",
                                    "description": "The type of search to perform.  Use 'news', if the user is looking for current events, weather, today's date, or date-related information.  Use 'general' for general detailed information about a topic.  If it is not clear what type of search the user wants, ask.",
                                    "enum": [
                                        "news",
                                        "general",
                                    ],
                                },
                            },
                            "required": ["search_query", "search_type"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = "No search results found or search failed."
        instant_response = ""

        if tool_name == "web_search_function":
            if self.settings.debug_mode:
                self.start_execution_benchmark()
                await self.printr.print_async(
                    f"Executing web_search_function with parameters: {parameters}",
                    color=LogType.INFO,
                )
            final_results = ""
            search_query = parameters.get("search_query")
            search_type = parameters.get("search_type")

            processed_results = []
            async def gather_information(result):
                title = result.get("title")
                link = result.get("url")
                if search_type == "general":
                    link = result.get("href")
                body = result.get("body")
                if link:
                    trafilatura_url = link
                    trafilatura_downloaded = fetch_url(trafilatura_url, config=self.trafilatura_config)
                    trafilatura_result = extract(trafilatura_downloaded, include_comments=False, include_tables=False)
                    if trafilatura_result:
                        processed_results.append(title + "\n" + link + "\n" + trafilatura_result[:self.max_result_size])
                        if self.settings.debug_mode:
                            await self.printr.print_async(
                                f"web_search skill analyzing website at: {link} for full content using trafilatura",
                                color=LogType.INFO,
                            )
                    else:
                        processed_results.append(title + "\n" + link + "\n" + body)

            if search_type == "general":
                search_results = DDGS().text(search_query, safesearch="off", max_results=self.max_results)
            else:
                search_results = DDGS().news(search_query, safesearch="off", max_results=self.max_results)

            start_time = time.time()

            for result in search_results:
                self.threaded_execution(gather_information, result)
            
            while len(processed_results) < self.min_results and time.time() - start_time < self.max_time:
                time.sleep(0.1)

            final_results = "\n\n".join(processed_results)
            if final_results:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Final web_search skill results used as context for AI response: \n\n {final_results}",
                        color=LogType.INFO,
                    )
                function_response = final_results

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

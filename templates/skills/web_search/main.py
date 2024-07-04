import time
import math
from urllib.parse import urlparse
from copy import deepcopy
from typing import TYPE_CHECKING
from duckduckgo_search import DDGS
from trafilatura import fetch_url, extract
from trafilatura.settings import DEFAULT_CONFIG
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class WebSearch(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        # Set default and custom behavior
        self.max_time = 5
        self.max_results = 5
        self.min_results = 2
        self.max_result_size = 4000

        # Set necessary trafilatura settings to match

        # Copy default config file that comes with trafilatura
        self.trafilatura_config = deepcopy(DEFAULT_CONFIG)
        # Change download and max redirects default in config
        self.trafilatura_config["DEFAULT"][
            "DOWNLOAD_TIMEOUT"
        ] = f"{math.ceil(self.max_time/2)}"
        self.trafilatura_config["DEFAULT"]["MAX_REDIRECTS "] = "3"

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
                                    "description": "The type of search to perform.  Use 'news', if the user is looking for current events, weather, or recent news.  Use 'general' for general detailed information about a topic.  Use 'single_site' if the user has specified one particular web page that they want you to review, and then use the 'single_site_url' parameter to identify the web page.  If it is not clear what type of search the user wants, ask.",
                                    "enum": [
                                        "news",
                                        "general",
                                        "single_site",
                                    ],
                                },
                                "single_site_url": {
                                    "type": "string",
                                    "description": "If the user wants to search a single website, the specific site url that they want to search, formatted as a proper url.",
                                },
                            },
                            "required": ["search_query", "search_type"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

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
            site_url = parameters.get("single_site_url")

            # Since site_url is not a required parameter, it is possible the AI may not to include it even when using single site type, and instead put the web address in the query field; check if that is the case.
            if not site_url and search_type == "single_site":
                try:
                    urlparse(search_query)
                    site_url = search_query
                except ValueError:
                    await self.printr.print_async(
                        "Tried single site search but no valid url to search.",
                        color=LogType.INFO,
                    )

            processed_results = []

            async def gather_information(result):
                title = result.get("title")
                link = result.get("url")
                if search_type == "general":
                    link = result.get("href")
                body = result.get("body")

                # If doing a deep dive on a single site get as much content as possible
                if search_type == "single_site":
                    self.max_result_size = 20000
                else:
                    self.max_result_size = 4000
                # If a link is in search results or identified by the user, then use trafilatura to download its content and extract the content to text
                if link:
                    trafilatura_url = link
                    trafilatura_downloaded = fetch_url(
                        trafilatura_url, config=self.trafilatura_config
                    )
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"web_search skill analyzing website at: {link} for full content using trafilatura",
                            color=LogType.INFO,
                        )
                    trafilatura_result = extract(
                        trafilatura_downloaded,
                        include_comments=False,
                        include_tables=False,
                    )
                    if trafilatura_result:
                        processed_results.append(
                            title
                            + "\n"
                            + link
                            + "\n"
                            + trafilatura_result[: self.max_result_size]
                        )

                    else:
                        if self.settings.debug_mode:
                            await self.printr.print_async(
                                f"web_search skill could not extract results from website at: {link} for full content using trafilatura",
                                color=LogType.INFO,
                            )
                        processed_results.append(title + "\n" + link + "\n" + body)

            if search_type == "general":
                self.min_results = 2
                self.max_time = 5
                search_results = DDGS().text(
                    search_query, safesearch="off", max_results=self.max_results
                )
            elif search_type == "news":
                self.min_results = 2
                self.max_time = 5
                search_results = DDGS().news(
                    search_query, safesearch="off", max_results=self.max_results
                )
            else:
                search_results = [
                    {"url": site_url, "title": "Site Requested", "body": "None found"}
                ]
                self.min_results = 1
                self.max_time = 30

            self.trafilatura_config["DEFAULT"][
                "DOWNLOAD_TIMEOUT"
            ] = f"{math.ceil(self.max_time/2)}"

            start_time = time.time()

            for result in search_results:
                self.threaded_execution(gather_information, result)

            while (
                len(processed_results) < self.min_results
                and time.time() - start_time < self.max_time
            ):
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

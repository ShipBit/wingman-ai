import time
import math
from urllib.parse import urlparse
from copy import deepcopy
from typing import TYPE_CHECKING, Literal, Optional
from duckduckgo_search import DDGS
from trafilatura import fetch_url, extract
from trafilatura.settings import DEFAULT_CONFIG
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from skills.skill_base import Skill, tool

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

        # Results collection for threaded execution
        self._processed_results: list[str] = []

    async def _gather_information(
        self,
        result: dict,
        search_type: str,
        max_result_size: int,
    ) -> None:
        """Extract content from a search result. Used in threaded execution."""
        title = result.get("title", "")
        link = result.get("url") if search_type != "general" else result.get("href")
        body = result.get("body", "")

        if link:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"web_search skill analyzing website at: {link} for full content using trafilatura",
                    color=LogType.INFO,
                )

            downloaded = fetch_url(link, config=self.trafilatura_config)
            trafilatura_result = extract(
                downloaded,
                include_comments=False,
                include_tables=False,
            )

            if trafilatura_result:
                self._processed_results.append(
                    f"{title}\n{link}\n{trafilatura_result[:max_result_size]}"
                )
            else:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"web_search skill could not extract results from website at: {link}",
                        color=LogType.INFO,
                    )
                self._processed_results.append(f"{title}\n{link}\n{body}")

    @tool(
        name="web_search_function",
        description="""Searches the internet using DuckDuckGo for current information.

        WHEN TO USE:
        - User says 'Search the web for...', 'Search the internet for...', 'Look up...'
        - User asks about current events, news, weather, or recent developments
        - Questions requiring up-to-date information beyond training knowledge
        - Topics needing real-time or specific factual data

        Supports news searches, general web searches, and single-site searches.""",
        wait_response=True,
    )
    async def web_search_function(
        self,
        search_query: str,
        search_type: Literal["news", "general", "single_site"],
        single_site_url: Optional[str] = None,
    ) -> str:
        """
        Performs a web search using DuckDuckGo.

        Args:
            search_query: The topic to search the internet for.
            search_type: The type of search - 'news' for current events/weather/news,
                        'general' for detailed information, 'single_site' for a specific page.
            single_site_url: If search_type is 'single_site', the specific URL to search.
        """
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"WebSearch: executing search with query '{search_query}', type '{search_type}'",
                color=LogType.INFO,
            )

        # Reset results collection
        self._processed_results = []

        # Handle single_site_url fallback from query
        site_url = single_site_url
        if not site_url and search_type == "single_site":
            try:
                urlparse(search_query)
                site_url = search_query
            except ValueError:
                await self.printr.print_async(
                    "Tried single site search but no valid url to search.",
                    color=LogType.INFO,
                )

        # Configure based on search type
        if search_type == "single_site":
            max_result_size = 20000
            self.min_results = 1
            self.max_time = 30
            search_results = [
                {"url": site_url, "title": "Site Requested", "body": "None found"}
            ]
        else:
            max_result_size = 4000
            self.min_results = 2
            self.max_time = 5

            if search_type == "general":
                search_results = DDGS().text(
                    search_query, safesearch="off", max_results=self.max_results
                )
            else:  # news
                search_results = DDGS().news(
                    search_query, safesearch="off", max_results=self.max_results
                )

        # Update trafilatura timeout
        self.trafilatura_config["DEFAULT"][
            "DOWNLOAD_TIMEOUT"
        ] = f"{math.ceil(self.max_time/2)}"

        # Process results in parallel using threaded execution
        start_time = time.time()

        for result in search_results:
            self.threaded_execution(
                self._gather_information,
                result,
                search_type,
                max_result_size,
            )

        # Wait for minimum results or timeout
        while (
            len(self._processed_results) < self.min_results
            and time.time() - start_time < self.max_time
        ):
            time.sleep(0.1)

        final_results = "\n\n".join(self._processed_results)

        if final_results:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"WebSearch: final results used as context for AI response: \n\n {final_results}",
                    color=LogType.INFO,
                )
            return final_results

        return "No search results found or search failed."

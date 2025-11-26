from typing import TYPE_CHECKING, Optional
from googlesearch import search
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig
from skills.skill_base import Skill, tool
from trafilatura import fetch_url, extract
from trafilatura.meta import reset_caches
from trafilatura.settings import DEFAULT_CONFIG
from copy import deepcopy

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

# Copy default config file that comes with trafilatura
trafilatura_config = deepcopy(DEFAULT_CONFIG)
# Change download and max redirects default in config
trafilatura_config["DEFAULT"]["DOWNLOAD_TIMEOUT"] = "10"
trafilatura_config["DEFAULT"]["MAX_REDIRECTS "] = "3"


class GoogleSearch(Skill):
    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def _extract_content_from_url(self, url: str) -> str:
        """Extract content from a URL using trafilatura."""
        if self.settings.debug_mode:
            await self.printr.print_async(
                f"googlesearch skill analyzing website at: {url} for full content using trafilatura.",
                color=LogType.INFO,
            )

        downloaded = fetch_url(url, config=trafilatura_config)
        result = extract(
            downloaded,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=False,
            include_images=False,
            include_formatting=True,
            favor_recall=True,
            url=url,
        )

        if result:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Trafilatura result for {url}: {result}.",
                    color=LogType.INFO,
                )
            return f"website: {url}\ncontent: {result}"
        else:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"google_search skill could not extract results from website at: {url}",
                    color=LogType.INFO,
                )
            return f"website: {url}\ncontent: None able to be extracted"

    @tool(
        name="perform_google_search",
        description="""Searches Google for information and extracts content from results.

        WHEN TO USE:
        - User says 'Search the web for...', 'Google...', 'Look up...'
        - User asks about current events, recent news, or developments
        - Questions requiring up-to-date information beyond training knowledge
        - Topics needing real-time or specific factual data
        - 'What is the latest news about...'""",
    )
    async def perform_google_search(
        self,
        query: str,
        lang: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """Performs a Google search and extracts content from results."""
        num_results = 3
        unique = True
        lang = lang or "en"
        results = []

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"GoogleSearchSkill: executing search with query '{query}'",
                color=LogType.INFO,
            )

        try:
            results = list(
                search(
                    query,
                    num_results=num_results,
                    unique=unique,
                    lang=lang,
                    region=region,
                    safe=None,
                )
            )
        except Exception as e:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"googlesearch skill problem with search: {e}",
                    color=LogType.INFO,
                )

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"googlesearch skill found results: {results}",
                color=LogType.INFO,
            )

        # Process each result
        processed_results = []
        for url in results:
            content = await self._extract_content_from_url(url)
            processed_results.append(content)

        final_results = "\n\n".join(processed_results)
        function_response = f"Results for web query '{query}' (each website found and content for that website): {final_results}"

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Final Results for {query}: {final_results}.",
                color=LogType.INFO,
            )

        reset_caches()
        return function_response

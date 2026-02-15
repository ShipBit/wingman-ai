import random
import requests
import json
import re

from services.printr import Printr
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class LoreManager(FunctionManager):
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Searches Galactapedia lore (ingame world information), provides news, and summarizes articles in detail."
    MANAGER_CAPABILITIES = [
        "Search Galactapedia by topic",
        "Fetch current lore news",
        "Summarize individual Galactapedia articles in detail",
    ]

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.wiki_base_url = "https://api.star-citizen.wiki/api/v2/galactapedia"
        self.current_call_identifier = None

    def get_context_mapping(self) -> AIContext:
        # Returns the context this manager is associated to. TTS-freundlicher kurzer Prompt.
        return AIContext.CORA

    def register_functions(self, function_register):
        # TTS-freundliche Beschreibungen
        function_register[self.search_information_in_galactapedia.__name__] = self.search_information_in_galactapedia
        function_register[self.get_news_of_the_day.__name__] = self.get_news_of_the_day
        function_register[self.request_information_from_galactapedia_entry_url.__name__] = self.request_information_from_galactapedia_entry_url

    def get_function_prompt(self):
        # Aus einem mehrzeiligen Prompt wurde ein einzeiliger TTS-freundlicher Text ohne Formatierungen
        return (
            "When asked for Star Citizen game world lore not related to trade, you can call: "
            + self.get_news_of_the_day.__name__
            + " if the user wants the latest news, "
            + self.search_information_in_galactapedia.__name__
            + " if the user asks about specific lore topics, and "
            + self.request_information_from_galactapedia_entry_url.__name__
            + " if the user wants information from a related article. Never reveal technical details in your summary. "
            + "Write out numbers fully in text. For example, instead of 2438, say in the year twothousand fourhundred and thirtyeight."
        )

    def get_function_tools(self):
        # Auf kompakte, TTS-freundliche Beschreibungen gekürzt
        return [
            {
                "type": "function",
                "function": {
                    "name": self.search_information_in_galactapedia.__name__,
                    "description": "Searches for lore in the galactapedia by a given topic or term.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Best matching term in the user's question.",
                            }
                        },
                        "required": ["search_term"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.get_news_of_the_day.__name__,
                    "description": "Retrieves the latest galactapedia entry as a news item.",
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.request_information_from_galactapedia_entry_url.__name__,
                    "description": "Requests detailed information from a galactapedia entry URL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "galactapedia_entry_url": {
                                "type": "string",
                                "description": "URL of the galactapedia entry to get information from.",
                            },
                            "call_identifier": {
                                "type": "integer",
                                "description": "Call identifier from the previous search function.",
                            },
                        },
                        "required": ["galactapedia_entry_url", "call_identifier"],
                    },
                },
            },
        ]

    # def cora_start_information(self):
    #     # Prompt-Text TTS-freundlich
    #     result = self.get_news_of_the_day({})
    #     if not result.get("success", False):
    #         return ""
    #     result["additional_instructions"] = (
    #         "Give the user a concise summary of the description field only. Any other information is not relevant. "
    #         "Do not mention URLs or technical details. Speak in a TTS-friendly format."
    #     )
    #     return {"news_of_the_day": result}

    def get_news_of_the_day(self, function_args):
        print_debug(f"{self.get_news_of_the_day.__name__} called.")
        printr.print(f"Executing function '{self.get_news_of_the_day.__name__}'.", tags="info")

        with requests.Session() as session:
            session.headers.update({"accept": "application/json", "Content-Type": "application/json"})
            try:
                response = session.get(url=f"{self.wiki_base_url}?limit=1&page=1", timeout=5)
                response.raise_for_status()
                data = response.json()
                total_pages = data.get("meta", {}).get("last_page", 0)
                if total_pages == 0:
                    raise ValueError("Total pages not found.")

                random_page = random.randint(1, total_pages)
                random_page_response = session.get(url=f"{self.wiki_base_url}?limit=1&page={random_page}", timeout=5)
                random_page_response.raise_for_status()
                random_page_data = random_page_response.json()

                api_url = random_page_data.get("data", [{}])[0].get("api_url")
                if not api_url:
                    raise ValueError("API URL not found in the random page data.")

                result = self.request_information_from_galactapedia_entry_url(
                    session=session,
                    function_args={
                        "galactapedia_entry_url": api_url,
                        "call_identifier": self.current_call_identifier,
                    },
                )
                if not result.get("success", False):
                    return result

                # TTS-freundlicher Zusatz
                result["additional_instructions"] = (
                    "Based on the article, create a short headline news summary. " + result["additional_instructions"]
                )
                printr.print(f"News of the day: {json.dumps(result, indent=2)}", tags="info")
                return result

            except (requests.exceptions.RequestException, ValueError) as e:
                print_debug(f"{self.get_news_of_the_day.__name__} Error: {str(e)}")
                printr.print(f"News of the day: Error: {str(e)}", tags="error")
                return {
                    "success": False,
                    "additional_instructions": (
                        "Currently no access to the intergalactic news network. Provide a short, TTS-friendly summary "
                        "of any interesting Star Citizen lore you know."
                    ),
                }

    def search_information_in_galactapedia(self, function_args):
        search_url = f"{self.wiki_base_url}/search"
        search_term = function_args.get("search_term", "")
        print_debug(f"{self.search_information_in_galactapedia.__name__} called with '{search_term}'")
        printr.print(
            f"Executing function '{self.search_information_in_galactapedia.__name__}' with search term '{search_term}'.",
            tags="info",
        )

        with requests.Session() as session:
            session.headers.update(
                {
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                }
            )
            try:
                search_response = session.post(search_url, json={"query": search_term}, timeout=5)
                search_response.raise_for_status()
                search_data = search_response.json()
                results = search_data.get("data", [])

                if not results:
                    printr.print(f"No galactapedia matches for '{search_term}'.", tags="info")
                    return {
                        "success": False,
                        "additional_instructions": (
                            "Answer the user with general knowledge. Inform that you cannot cite galactapedia."
                        ),
                    }

                self.current_call_identifier = random.randint(0, 1000000)
                number_of_results = len(results)

                if number_of_results == 1:
                    api_url = results[0].get("api_url")
                    result = self.request_information_from_galactapedia_entry_url(
                        session=session,
                        function_args={
                            "galactapedia_entry_url": api_url,
                            "call_identifier": self.current_call_identifier,
                        },
                    )
                    printr.print(
                        f"Found a single article for the topic. {json.dumps(result, indent=2)}", tags="info"
                    )
                    return result

                articles = []
                for i in range(min(number_of_results, 10)):
                    entry = results[i]
                    articles.append({
                        "title": entry.get("title"),
                        "type": entry.get("type"),
                        "galactapedia_entry_url": entry.get("api_url"),
                    })

                # TTS-freundlicher Text
                result = {
                    "success": True,
                    "additional_instructions": (
                        "Multiple galactapedia entries found. Ask the user which article is of interest. "
                        "Mention only the titles in a TTS-friendly sentence. For example: Worueber moechtest Du "
                        "mehr Informationen: ArcCorp the company or ArcCorp the planet? If the user picks one, "
                        "call the function again with the correct galactapedia_entry_url and the call_identifier."
                    ),
                    "found_articles": articles,
                    "call_identifier": self.current_call_identifier,
                }
                printr.print(f"Found multiple articles. {json.dumps(result, indent=2)}", tags="info")
                return result

            except requests.exceptions.RequestException as e:
                if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 404:
                    printr.print("No entry found for the search term.", tags="info")
                    return {
                        "success": False,
                        "additional_instructions": (
                            f"No entry found for the search term '{search_term}'. Provide general info if possible, "
                            "and inform the user that galactapedia has no data for that. If you have no info, "
                            "suggest rephrasing or alternative search terms."
                        ),
                        "error": str(e),
                    }
                print_debug(f"{self.search_information_in_galactapedia.__name__} exception: {str(e)}")
                printr.print(f"Error searching '{search_term}': {str(e)}", tags="info")
                return {
                    "success": False,
                    "additional_instructions": "Galactapedia is currently unavailable, please try again later.",
                    "error": str(e),
                }

    def request_information_from_galactapedia_entry_url(self, function_args, session=None):
        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                }
            )

        api_url = function_args.get("galactapedia_entry_url", "")
        call_identifier = function_args.get("call_identifier", None)
        printr.print(
            f"Executing function '{self.request_information_from_galactapedia_entry_url.__name__}' for URL: {api_url}.",
            tags="info",
        )

        if self.current_call_identifier != call_identifier:
            return {
                "success": False,
                "additional_instructions": (
                    "A valid call_identifier is required. Ask the user which article they want to see, "
                    "then call the appropriate function."
                ),
            }

        # Regex-Check vereinfacht beibehalten, TTS-freundlicher Fehlertext
        if not re.match(
            r"^https:\/\/api\.star-citizen\.wiki\/api\/v2\/galactapedia\/",
            api_url[: api_url.find("/galactapedia/") + len("/galactapedia/")],
        ):
            printr.print(f"Invalid URL: {api_url}", tags="error")
            return {
                "success": False,
                "additional_instructions": "Not allowed to request information from this URL.",
            }

        print_debug(f"{self.request_information_from_galactapedia_entry_url.__name__} with API URL: {api_url}")

        try:
            api_response = session.get(api_url, timeout=5)
            api_response.raise_for_status()
            api_data = api_response.json()

            result = {
                "subject_title": api_data["data"]["title"],
                "subject_type": api_data["data"]["type"],
                "description": api_data["data"]["translations"]["en_EN"],
                "additional_information": [
                    {"name": prop["name"], "value": prop["value"]}
                    for prop in api_data["data"]["properties"]
                ],
                "related_articles": [
                    {
                        "title": article["title"],
                        "galactapedia_entry_url": article["api_url"]
                    }
                    for article in api_data["data"]["related_articles"]
                ],
            }

            printr.print(f"Galactapedia info: {json.dumps(result, indent=2)}", tags="info")

            # TTS-freundliche Prompts
            if api_data["data"]["related_articles"]:
                self.current_call_identifier = random.randint(0, 1000000)
                return {
                    "success": True,
                    "additional_instructions": (
                        "Information retrieved. Give the user a TTS-friendly summary of the description. "
                        "Offer details only if asked. If there are related articles, mention their titles. "
                        "If the user wants more info, call this function again with the new call_identifier."
                    ),
                    "result": result,
                    "call_identifier": self.current_call_identifier,
                }

            self.current_call_identifier = None
            return {
                "success": True,
                "additional_instructions": (
                    "Information retrieved. Give the user a TTS-friendly summary of the description. "
                    "Only provide more details if asked."
                ),
                "result": result,
            }

        except requests.exceptions.RequestException as e:
            print_debug(f"{self.request_information_from_galactapedia_entry_url.__name__} exception: {str(e)}")
            printr.print(f"Error requesting galactapedia info: {str(e)}", tags="info")
            return {
                "success": False,
                "additional_instructions": "Could not retrieve galactapedia information. Please try again later.",
                "error": str(e),
            }


if __name__ == "__main__":
    lm = LoreManager({}, {})
    print("Subclasses of FunctionManager:", FunctionManager.__subclasses__())
    print(lm.get_news_of_the_day({}))

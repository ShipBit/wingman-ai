import os
import json
import random
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Tuple
import yaml
import aiohttp
from aiohttp import ClientError
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.benchmark import Benchmark
from services.file import get_writable_dir
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman

DEFAULT_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Access-Control-Allow-Origin": "http://localhost",
    "Access-Control-Allow-Methods": "*",
    "Access-Control-Allow-Headers": "*",
}


class APIRequest(Skill):
    """Skill for making API requests."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        self.use_default_headers = False
        self.default_headers = DEFAULT_HEADERS
        self.max_retries = 1
        self.request_timeout = 5
        self.retry_delay = 5
        self.api_keys_dictionary = self.get_api_keys()

        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.use_default_headers = self.retrieve_custom_property_value(
            "use_default_headers", errors
        )

        self.max_retries = self.retrieve_custom_property_value("max_retries", errors)
        self.request_timeout = self.retrieve_custom_property_value(
            "request_timeout", errors
        )
        self.retry_delay = self.retrieve_custom_property_value("retry_delay", errors)

        return errors

    # Retrieve api key aliases in user api key file
    def get_api_keys(self) -> dict:
        api_key_holder = os.path.join(
            get_writable_dir("files"), "api_request_key_holder.yaml"
        )
        # If no key holder file is present yet, create it
        if not os.path.isfile(api_key_holder):
            os.makedirs(os.path.dirname(api_key_holder), exist_ok=True)
            with open(api_key_holder, "w", encoding="utf-8") as file:
                pass
        # Open key holder file to read stored API keys
        with open(api_key_holder, "r", encoding="UTF-8") as stream:
            try:
                parsed = yaml.safe_load(stream)
                if isinstance(
                    parsed, dict
                ):  # Ensure the parsed content is a dictionary
                    return parsed  # Return the dictionary of alias/keys
            except Exception as e:
                return {}

    # Prepare and send API request using parameters provided by LLM response to function call
    async def _send_api_request(self, parameters: Dict[str, Any]) -> str:
        """Send an API request with the specified parameters."""
        # Get headers from LLM, check whether they are a dictionary, if not at least let user know in debug mode.
        headers = parameters.get("headers")
        if headers and isinstance(headers, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Validated that headers returned from LLM is a dictionary.",
                    color=LogType.INFO,
                )
        elif headers:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Headers returned from LLM is not a dictionary.  Type is {type(headers)}",
                    color=LogType.INFO,
                )
        else:
            headers = {}

        # If using default headers, add those to AI generated headers
        if self.use_default_headers:
            headers.update(
                self.default_headers
            )  # Defaults will override AI-generated if necessary
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Default headers being used for API call: {headers}",
                    color=LogType.INFO,
                )

        # Get params, check whether they are a dictionary, if not, at least let user know in debug mode.
        params = parameters.get("params")
        if params and isinstance(params, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Validated that params returned from LLM is a dictionary.",
                    color=LogType.INFO,
                )
        elif params:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Params returned from LLM is not a dictionary.  Type is {type(params)}",
                    color=LogType.INFO,
                )
        else:
            params = {}

        # Get body of request.  First check to see if LLM returned a "data" field, and if so, whether data is a dictionary, if not, at least let the user know in debug mode.
        body = parameters.get("data")
        if body and isinstance(body, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Validated that data returned from LLM is a dictionary.",
                    color=LogType.INFO,
                )
        elif body:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Data returned from LLM is not a dictionary.  Type is {type(body)}",
                    color=LogType.INFO,
                )
        # 'data' was not present in parameters, so check if 'body' was provided instead.  If so, check whether body is a dictionary, and if not, at least let the user know in debug mode.
        else:
            body = parameters.get("body")
            if body and isinstance(body, dict):
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Validated that body returned from LLM is a dictionary.",
                        color=LogType.INFO,
                    )
            elif body:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Body returned from LLM is not a dictionary.  Type is {type(body)}",
                        color=LogType.INFO,
                    )
            else:
                body = {}  # Should this be None instead?

        # However we got the body for the request, try turning it into the valid json that aiohttp session.request expects for data field
        try:
            data = json.dumps(body)
        except:

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Cannot convert data into valid json: {data}.",
                )
            data = json.dumps(
                {}
            )  # Just send an empty dictionary if everything else failed

        # Try request up to max numner of retries
        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(
                        method=parameters["method"],
                        url=parameters["url"],
                        headers=headers,
                        params=params,
                        data=data,
                        timeout=self.request_timeout,
                    ) as response:
                        response.raise_for_status()

                        # Default to treating content as text if Content-Type is not specified
                        content_type = response.headers.get("Content-Type", "").lower()
                        if "application/json" in content_type:
                            return await response.text()
                        elif any(
                            x in content_type
                            for x in [
                                "application/octet-stream",
                                "application/",
                                "audio/mpeg",
                                "audio/wav",
                                "audio/ogg",
                                "image/jpeg",
                                "image/png",
                                "video/mp4",
                                "application/pdf",
                            ]
                        ):
                            file_content = await response.read()

                            # Determine appropriate file extension and name
                            if "audio/mpeg" in content_type:
                                file_extension = ".mp3"
                            elif "audio/wav" in content_type:
                                file_extension = ".wav"
                            elif "audio/ogg" in content_type:
                                file_extension = ".ogg"
                            elif "image/jpeg" in content_type:
                                file_extension = ".jpg"
                            elif "image/png" in content_type:
                                file_extension = ".png"
                            elif "video/mp4" in content_type:
                                file_extension = ".mp4"
                            elif "application/pdf" in content_type:
                                file_extension = ".pdf"
                            else:
                                file_extension = ".file"
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_name = f"downloaded_file_{timestamp}{file_extension}"  # Use a default name or extract it from response headers if available

                            if "Content-Disposition" in response.headers:
                                disposition = response.headers["Content-Disposition"]
                                if "filename=" in disposition:
                                    file_name = disposition.split("filename=")[1].strip(
                                        '"'
                                    )

                            files_directory = get_writable_dir("files")
                            file_path = os.path.join(files_directory, file_name)
                            with open(file_path, "wb") as file:
                                file.write(file_content)

                            return f"File returned from API saved as {file_path}"
                        else:
                            return await response.text()
            except (ClientError, asyncio.TimeoutError) as e:
                if attempt <= self.max_retries:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Retrying API request due to: {e}.",
                            color=LogType.INFO,
                        )
                    delay = self.retry_delay * (2 ** (attempt - 1)) + random.uniform(
                        0, 0.1 * self.retry_delay
                    )
                    await asyncio.sleep(delay)
                else:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Error with api request: {e}.",
                            color=LogType.INFO,
                        )
                    return f"Error, could not complete API request. Exception was: {e}."
            except Exception as e:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Error with api request: {e}.",
                        color=LogType.INFO,
                    )
                return f"Error, could not complete API request.  Reason was {e}."

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        return True

    def get_tools(self) -> list[Tuple[str, Dict[str, Any]]]:
        # Ensure api_keys_dictionary is populated, if not use placeholder
        if not self.api_keys_dictionary:
            self.api_keys_dictionary = {"Service": "API_key"}

        return [
            (
                "send_api_request",
                {
                    "type": "function",
                    "function": {
                        "name": "send_api_request",
                        "description": "Send an API request with the specified method, headers, parameters, and body. Return the response back.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "The URL for the API request.",
                                },
                                "method": {
                                    "type": "string",
                                    "description": "The HTTP method (GET, POST, PUT, PATCH, DELETE, etc.).",
                                },
                                "headers": {
                                    "type": "object",
                                    "description": "Headers for the API request.",
                                },
                                "params": {
                                    "type": "object",
                                    "description": "URL parameters for the API request.",
                                },
                                "data": {
                                    "type": "object",
                                    "description": "Body or payload for the API request.",
                                },
                            },
                            "required": ["url", "method"],
                        },
                    },
                },
            ),
            (
                "get_api_key",
                {
                    "type": "function",
                    "function": {
                        "name": "get_api_key",
                        "description": "Obtain the API key needed for an API request.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "api_key_alias": {
                                    "type": "string",
                                    "description": "The API key needed.",
                                    "enum": list(self.api_keys_dictionary.keys()),
                                },
                            },
                            "required": ["api_key_alias"],
                        },
                    },
                },
            ),
        ]

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any], benchmark: Benchmark
    ) -> Tuple[str, str]:
        function_response = "Error with API request, could not complete."
        instant_response = ""

        if tool_name in ["send_api_request", "get_api_key"]:
            benchmark.start_snapshot(f"API Request: {tool_name}")

            if self.settings.debug_mode:
                message = f"API Request: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            if tool_name == "send_api_request":
                try:
                    function_response = await self._send_api_request(parameters)
                except Exception as e:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Unknown error with API call  {e}",
                            color=LogType.INFO,
                        )
            elif tool_name == "get_api_key":
                alias = parameters.get("api_key_alias", "Not found")
                key = self.api_keys_dictionary.get(alias, None)
                if key is not None and key != "API_key":
                    function_response = f"{alias} API key is: {key}"
                else:
                    function_response = (
                        f"Error. Could not retrieve {alias} API key. Not found."
                    )

            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Response from {tool_name}: {function_response}",
                    color=LogType.INFO,
                )
            benchmark.finish_snapshot()

        return function_response, instant_response

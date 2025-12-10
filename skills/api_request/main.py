import os
import json
import random
import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
import yaml
import aiohttp
from aiohttp import ClientError
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

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

# Content-Type to file extension mapping
CONTENT_TYPE_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "video/mp4": ".mp4",
    "application/pdf": ".pdf",
}

# Content types that should be saved as binary files
BINARY_CONTENT_TYPES = [
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


class APIRequest(Skill):
    """Skill for making API requests."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        self.default_headers = DEFAULT_HEADERS

        super().__init__(config=config, settings=settings, wingman=wingman)
        self.api_keys_dictionary = self.get_api_keys()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.retrieve_custom_property_value("use_default_headers", errors)
        self.retrieve_custom_property_value("max_retries", errors)
        self.retrieve_custom_property_value("request_timeout", errors)
        self.retrieve_custom_property_value("retry_delay", errors)

        return errors

    def _get_use_default_headers(self) -> bool:
        """Get use_default_headers property value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("use_default_headers", errors)

    def _get_max_retries(self) -> int:
        """Get max_retries property value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("max_retries", errors)

    def _get_request_timeout(self) -> int:
        """Get request_timeout property value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("request_timeout", errors)

    def _get_retry_delay(self) -> int:
        """Get retry_delay property value just-in-time."""
        errors = []
        return self.retrieve_custom_property_value("retry_delay", errors)

    # Retrieve api key aliases in user api key file
    def get_api_keys(self) -> dict:
        api_key_holder = os.path.join(
            self.get_generated_files_dir(), "api_request_key_holder.yaml"
        )
        # If no key holder file is present yet, create it
        if not os.path.isfile(api_key_holder):
            os.makedirs(os.path.dirname(api_key_holder), exist_ok=True)
            with open(api_key_holder, "w", encoding="utf-8") as _file:
                pass
        # Open key holder file to read stored API keys
        with open(api_key_holder, "r", encoding="UTF-8") as stream:
            try:
                parsed = yaml.safe_load(stream)
                if isinstance(
                    parsed, dict
                ):  # Ensure the parsed content is a dictionary
                    return parsed  # Return the dictionary of alias/keys
            except Exception:
                return {}
        return {}

    async def _send_api_request(self, parameters: Dict[str, Any]) -> str:
        """Send an API request with the specified parameters."""
        # Validate and prepare headers
        headers = parameters.get("headers", {})
        if not isinstance(headers, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Headers is not a dictionary. Type is {type(headers)}. Using empty dict.",
                    color=LogType.INFO,
                )
            headers = {}

        # Merge with default headers if configured
        if self._get_use_default_headers():
            merged_headers = {**headers, **self.default_headers}
            headers = merged_headers
            if self.settings.debug_mode:
                await self.printr.print_async(
                    "Default headers merged for API call.",
                    color=LogType.INFO,
                )

        # Validate and prepare params
        params = parameters.get("params", {})
        if not isinstance(params, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Params is not a dictionary. Type is {type(params)}. Using empty dict.",
                    color=LogType.INFO,
                )
            params = {}

        # Validate and prepare request body
        body = parameters.get("data", {})
        if not isinstance(body, dict):
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Data is not a dictionary. Type is {type(body)}. Using empty dict.",
                    color=LogType.INFO,
                )
            body = {}

        # Serialize body to JSON
        try:
            data = json.dumps(body)
        except (TypeError, ValueError) as e:
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"Cannot convert data to JSON: {e}. Using empty object.",
                    color=LogType.WARNING,
                )
            data = json.dumps({})

        # Try request up to max number of retries
        max_retries = self._get_max_retries()
        for attempt in range(1, max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(
                        method=parameters["method"],
                        url=parameters["url"],
                        headers=headers,
                        params=params,
                        data=data,
                        timeout=self._get_request_timeout(),
                    ) as response:
                        response.raise_for_status()
                        return await self._process_response(response)

            except (ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Retrying API request (attempt {attempt}/{max_retries}) due to: {e}",
                            color=LogType.INFO,
                        )
                    retry_delay = self._get_retry_delay()
                    delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(
                        0, 0.1 * retry_delay
                    )
                    await asyncio.sleep(delay)
                else:
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"API request failed after {max_retries} attempts: {e}",
                            color=LogType.WARNING,
                        )
                    return f"Error, could not complete API request. Exception was: {e}."
            except Exception as e:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Unexpected error with API request: {e}",
                        color=LogType.WARNING,
                    )
                return f"Error, could not complete API request. Reason was {e}."

        return "Error, could not complete API request after all retries."

    async def _process_response(self, response: aiohttp.ClientResponse) -> str:
        """Process API response based on content type."""
        content_type = response.headers.get("Content-Type", "").lower()

        # Handle JSON responses
        if "application/json" in content_type:
            return await response.text()

        # Handle binary content types
        if any(ct in content_type for ct in BINARY_CONTENT_TYPES):
            return await self._save_binary_response(response, content_type)

        # Default to text response
        return await response.text()

    async def _save_binary_response(
        self, response: aiohttp.ClientResponse, content_type: str
    ) -> str:
        """Save binary response content to a file."""
        file_content = await response.read()

        # Determine file extension from content type
        file_extension = ".file"
        for ct, ext in CONTENT_TYPE_EXTENSIONS.items():
            if ct in content_type:
                file_extension = ext
                break

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"downloaded_file_{timestamp}{file_extension}"

        # Try to extract filename from Content-Disposition header
        if "Content-Disposition" in response.headers:
            disposition = response.headers["Content-Disposition"]
            if "filename=" in disposition:
                file_name = disposition.split("filename=")[1].strip('"')

        # Save file
        files_directory = self.get_generated_files_dir()
        file_path = os.path.join(files_directory, file_name)
        with open(file_path, "wb") as file:
            file.write(file_content)

        return f"File returned from API saved as {file_path}"

    @tool(
        name="list_api_keys",
        description="List all available API key aliases. Use this to discover what API keys are configured before making authenticated API requests.",
        wait_response=True,
    )
    async def list_api_keys(self) -> str:
        """List all available API key aliases."""
        if not self.api_keys_dictionary:
            return "No API keys configured. Add keys to files/api_request_key_holder.yaml in the format 'alias: your_api_key'."
        aliases = list(self.api_keys_dictionary.keys())
        return f"Available API key aliases: {', '.join(aliases)}"

    @tool(
        name="get_api_key",
        description="Retrieve a stored API key by its alias name. Use list_api_keys first to discover available aliases. Use this before making API calls that require authentication.",
        wait_response=True,
    )
    async def get_api_key(self, api_key_alias: str) -> str:
        """Get an API key by alias from the stored keys."""
        key = self.api_keys_dictionary.get(api_key_alias, None)
        if key is not None:
            return f"{api_key_alias} API key is: {key}"
        available = (
            list(self.api_keys_dictionary.keys()) if self.api_keys_dictionary else []
        )
        hint = f" Available aliases: {', '.join(available)}" if available else ""
        return f"Error. Could not retrieve '{api_key_alias}' API key. Not found.{hint}"

    @tool(
        name="send_api_request",
        description="Send an HTTP API request with specified method, headers, parameters, and body. Use for calling external APIs, web services, REST endpoints, or webhooks.",
        wait_response=True,
    )
    async def send_api_request(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send an API request and return the response."""
        parameters = {
            "url": url,
            "method": method,
            "headers": headers or {},
            "params": params or {},
            "data": data or {},
        }
        return await self._send_api_request(parameters)

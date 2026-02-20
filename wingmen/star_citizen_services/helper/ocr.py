import os
import datetime
import base64
from io import BytesIO
import json
import re
import traceback

import cv2
from PIL import Image
import requests

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

from wingmen.star_citizen_services.overlay import StarCitizenOverlay


DEBUG = False
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class _ResponseWrapper:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class OCR:
    def __init__(
        self,
        data_dir,
        extraction_instructions,
        overlay: StarCitizenOverlay,
        config=None,
        secret_keeper=None,
        requester_name="OCR",
        open_ai_model=None,
        openai_api_key=None,
        gemini_api_key=None,
        openai_base_url=None,
    ):
        self.extraction_instructions = extraction_instructions
        self.data_dir = data_dir
        self.overlay = overlay
        self.config = config or {}
        self.secret_keeper = secret_keeper
        self.requester_name = requester_name

        self.openai_model = self._resolve_vision_model(open_ai_model)
        self.openai_api_key = self._resolve_openai_api_key(openai_api_key)
        self.gemini_api_key = self._resolve_gemini_api_key(gemini_api_key)
        self.openai_base_url = self._resolve_openai_base_url(openai_base_url)
        self._gemini_client = None
        self.max_output_tokens = int(self.config.get("vision-max-output-tokens", 2500))
        self.retry_max_output_tokens = int(
            self.config.get(
                "vision-retry-max-output-tokens",
                max(self.max_output_tokens * 2, 5000),
            )
        )

    def _resolve_vision_model(self, explicit_model):
        if explicit_model:
            return explicit_model
        configured_model = self.config.get("open-ai-vision-model")
        if configured_model:
            return configured_model
        return "gpt-4.1-mini"

    def _resolve_openai_api_key(self, explicit_key):
        if explicit_key:
            return explicit_key
        if not self.secret_keeper:
            return None
        return self.secret_keeper.retrieve(
            requester=self.requester_name,
            key="openai",
            friendly_key_name="OpenAI API key",
            prompt_if_missing=False,
        )

    def _resolve_gemini_api_key(self, explicit_key):
        if explicit_key:
            return explicit_key
        if not self.secret_keeper:
            return None
        gemini_key = self.secret_keeper.retrieve(
            requester=self.requester_name,
            key="gemini",
            friendly_key_name="Gemini API key",
            prompt_if_missing=False,
        )
        if gemini_key:
            return gemini_key
        return self.secret_keeper.retrieve(
            requester=self.requester_name,
            key="google_search_api",
            friendly_key_name="Google API key",
            prompt_if_missing=False,
        )

    def _resolve_openai_base_url(self, explicit_base_url):
        if explicit_base_url:
            return explicit_base_url.rstrip("/")
        configured_base_url = self.config.get("openai", {}).get("base_url")
        if configured_base_url:
            return configured_base_url.rstrip("/")
        return "https://api.openai.com"

    def _get_vision_provider(self):
        if str(self.openai_model).lower().startswith("gemini"):
            return "gemini"
        return "openai"

    def _extract_message_content(self, response_data):
        provider = self._get_vision_provider()
        if provider == "gemini":
            candidates = response_data.get("candidates", [])
            if not candidates:
                return "", None
            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
            return "\n".join(part for part in text_parts if part), first_candidate.get("finishReason")

        choices = response_data.get("choices", [])
        if not choices:
            return "", None
        first_choice = choices[0]
        return first_choice.get("message", {}).get("content", ""), first_choice.get("finish_reason")

    def _get_openai_chat_completions_url(self):
        if self.openai_base_url.endswith("/v1"):
            return f"{self.openai_base_url}/chat/completions"
        return f"{self.openai_base_url}/v1/chat/completions"

    def _call_openai_vision(self, img_str, max_output_tokens):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_api_key}",
        }
        payload = {
            "model": self.openai_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.extraction_instructions},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_str}"},
                        },
                    ],
                }
            ],
            "max_completion_tokens": max_output_tokens,
        }
        response = requests.post(
            self._get_openai_chat_completions_url(), headers=headers, json=payload, timeout=300
        )
        return response

    def _call_gemini_vision(self, img_str, max_output_tokens):
        if genai is not None and genai_types is not None:
            try:
                if self._gemini_client is None:
                    self._gemini_client = genai.Client(api_key=self.gemini_api_key)

                sdk_response = self._gemini_client.models.generate_content(
                    model=self.openai_model,
                    contents=[
                        genai_types.Part.from_bytes(
                            data=base64.b64decode(img_str),
                            mime_type="image/jpeg",
                        ),
                        self.extraction_instructions,
                    ],
                    config=genai_types.GenerateContentConfig(max_output_tokens=max_output_tokens),
                )
                normalized_payload = self._normalize_gemini_sdk_response(sdk_response)
                return _ResponseWrapper(status_code=200, payload=normalized_payload)
            except BaseException as e:
                print_debug(f"Gemini SDK call failed, falling back to REST API. Error: {e}")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": self.extraction_instructions},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": img_str,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"maxOutputTokens": max_output_tokens},
        }
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.openai_model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.gemini_api_key,
            },
            json=payload,
            timeout=300,
        )
        return response

    def _normalize_gemini_sdk_response(self, sdk_response):
        if hasattr(sdk_response, "model_dump"):
            try:
                payload = sdk_response.model_dump(exclude_none=True)
                if isinstance(payload, dict):
                    return payload
            except BaseException:
                pass

        response_text = getattr(sdk_response, "text", "") or ""
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": response_text,
                            }
                        ]
                    }
                }
            ]
        }

    def _extract_first_balanced_json(self, text):
        start_positions = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
        if not start_positions:
            return None

        start = min(start_positions)
        stack = []
        in_string = False
        is_escaped = False
        matching = {"{": "}", "[": "]"}

        for idx in range(start, len(text)):
            char = text[idx]

            if in_string:
                if is_escaped:
                    is_escaped = False
                elif char == "\\":
                    is_escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in matching:
                stack.append(char)
            elif char in ("}", "]"):
                if not stack:
                    return None
                opener = stack.pop()
                if matching[opener] != char:
                    return None
                if not stack:
                    return text[start : idx + 1]
        return None

    def _candidate_json_texts(self, message_content):
        candidates = []

        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", message_content, flags=re.IGNORECASE)
        for block in fenced_blocks:
            candidates.append(block.strip())

        split_blocks = message_content.split("```")
        if len(split_blocks) >= 2:
            for block in split_blocks[1::2]:
                text = block.strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
                candidates.append(text)

        candidates.append(message_content.strip())
        return [candidate for candidate in candidates if candidate]

    def _parse_json_from_message_content(self, message_content):
        last_error = "Unknown JSON parsing error."
        for candidate in self._candidate_json_texts(message_content):
            normalized = candidate.strip()
            if normalized.lower().startswith("json"):
                normalized = normalized[4:].strip()

            for attempt in (normalized, self._extract_first_balanced_json(normalized)):
                if not attempt:
                    continue
                try:
                    return json.loads(attempt), None
                except json.JSONDecodeError as e:
                    last_error = str(e)
        return None, last_error

    def _extract_error_for_logging(self, response):
        try:
            error_payload = response.json()
        except ValueError:
            return response.text

        if self._get_vision_provider() == "gemini":
            return error_payload.get("error", {}).get("status", "unknown")
        return error_payload.get("error", {}).get("type", "unknown")

    def _normalize_message_content(self, message_content):
        if isinstance(message_content, str):
            return message_content
        if isinstance(message_content, list):
            text_parts = [
                block.get("text", "")
                for block in message_content
                if isinstance(block, dict) and block.get("text")
            ]
            return "\n".join(text_parts)
        return json.dumps(message_content)

    def get_screenshot_texts(self, image, *subdirectories, **filename_placeholders):
        if image is None:
            print("ERROR: No screenshot provided. ")
            return "No screenshot provided. ", False
        
        gray_screenshot = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        subdir_path = "/".join(subdirectories)
        # Process placeholders in the filename
        placeholder_part = "_".join(f"{key}-{value}" for key, value in filename_placeholders.items())

        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")  # Format: YearMonthDay_HourMinuteSecond_Milliseconds

        is_test = TEST
        if "test" in filename_placeholders.keys() and is_test is False:
            is_test = filename_placeholders["test"]

        img_str = None
        response = None
        finish_reason = None
        try:

            if not is_test:

                pil_img = Image.fromarray(gray_screenshot)

                # Einen BytesIO-Buffer für das Bild erstellen
                buffered = BytesIO()

                # Das PIL-Bild im Buffer als JPEG speichern
                pil_img.save(buffered, format="JPEG")

                # Base64-String aus dem Buffer generieren
                img_str = base64.b64encode(buffered.getvalue()).decode()

                self.overlay.display_overlay_text(f"Analysing screenshot for text extraction", display_duration=30000)
                provider = self._get_vision_provider()
                print_debug(f"Calling {provider} vision for text extraction")

                if provider == "gemini":
                    if not self.gemini_api_key:
                        return "Gemini API key is missing in secrets.yaml (key: gemini).", False
                    response = self._call_gemini_vision(img_str, max_output_tokens=self.max_output_tokens)
                else:
                    if not self.openai_api_key:
                        return "OpenAI API key is missing in secrets.yaml (key: openai).", False
                    response = self._call_openai_vision(img_str, max_output_tokens=self.max_output_tokens)

                if response.status_code != 200:
                    error_text = self._extract_error_for_logging(response)
                    print(f'request error: {error_text}. Check the file {subdir_path} for details.')
                    self.save_debug_data(subdir_path, placeholder_part, timestamp, img_str, response)
                    return "Error calling vision model.", False
                
                response_data = response.json()
                message_content, finish_reason = self._extract_message_content(response_data)
                message_content = self._normalize_message_content(message_content)
                
                # Check if content is empty (can happen with reasoning models hitting token limit)
                if not message_content or message_content.strip() == "":
                    print(f"Vision model returned empty content. Finish reason: {finish_reason}")
                    if finish_reason in {"length", "MAX_TOKENS"}:
                        print("Token limit reached. Consider increasing max_completion_tokens or using a non-reasoning model.")
                    self.save_debug_data(subdir_path, placeholder_part, timestamp, img_str, response)
                    return "Vision model returned empty response (possibly due to token limit).", False
            else:
                # Read JSON data from a file
                path = os.path.join(self.data_dir, 'examples', subdir_path)
                if not os.path.exists(path):
                    os.makedirs(path)

                filename = f'open_ai_full_response_{placeholder_part}.json'
                full_path = os.path.normpath(os.path.join(path, filename))
                with open(full_path, 'r', encoding="UTF-8") as file:
                    message_content, _ = self._extract_message_content(json.load(file))
                    message_content = self._normalize_message_content(message_content)

            if "error" in json.dumps(message_content).lower():
                if img_str and response is not None:
                    self.save_debug_data(subdir_path, placeholder_part, timestamp, img_str, response)
                return f"Unable to analyse screenshot (maybe cropping error). {json.dumps(message_content)} ", False

            retrieved_text, parse_error = self._parse_json_from_message_content(message_content)
            if retrieved_text is None and finish_reason in {"length", "MAX_TOKENS"} and not is_test:
                print(
                    f"Vision response was truncated (finish reason: {finish_reason}). "
                    f"Retrying with max output tokens={self.retry_max_output_tokens}."
                )
                provider = self._get_vision_provider()
                if provider == "gemini":
                    response = self._call_gemini_vision(
                        img_str, max_output_tokens=self.retry_max_output_tokens
                    )
                else:
                    response = self._call_openai_vision(
                        img_str, max_output_tokens=self.retry_max_output_tokens
                    )

                if response.status_code == 200:
                    retry_payload = response.json()
                    message_content, finish_reason = self._extract_message_content(retry_payload)
                    message_content = self._normalize_message_content(message_content)
                    retrieved_text, parse_error = self._parse_json_from_message_content(message_content)

            if retrieved_text is None:
                if img_str and response is not None:
                    self.save_debug_data(subdir_path, placeholder_part, timestamp, img_str, response)
                return (
                    "Invalid response format from vision model. "
                    f"JSON could not be parsed: {parse_error}",
                    False,
                )

            if DEBUG:
                self.save_debug_data(subdir_path, placeholder_part, timestamp, img_str, response)

                path = os.path.join(self.data_dir, 'debug_data', subdir_path)
                if not os.path.exists(path):
                    os.makedirs(path)

                filename = f'extracted_open_ai_text_{placeholder_part}_{timestamp}.json'
                full_path = os.path.normpath(os.path.join(path, filename))
                with open(full_path, 'w', encoding="UTF-8") as file:
                    json.dump(retrieved_text, file, indent=4)

            return retrieved_text, True
        except BaseException as e:
            if DEBUG:
                traceback.print_exc()
            else:
                print(f"OCR exception during screenshot analysis: {e}")
            return "Some exception raised during screenshot analysis", False

    def save_debug_data(self, subdir_path, placeholder_part, timestamp, img_str, response):
        path = os.path.join(self.data_dir, 'debug_data', subdir_path)
                    
        if not os.path.exists(path):
            os.makedirs(path)

        img_path = os.path.join(path, f"vision_payload_image_{placeholder_part}_{timestamp}.jpg")
        with open(img_path, 'wb') as f:
            f.write(base64.b64decode(img_str))

        # Create the full path and filename
        filename = f"open_ai_full_response_{placeholder_part}_{timestamp}.json"
        full_path = os.path.normpath(os.path.join(path, filename))
        
        # Write JSON data to a file
        with open(full_path, 'w', encoding="UTF-8") as file:
            try:
                json.dump(response.json(), file, indent=4)
            except ValueError:
                json.dump({"raw_response": response.text}, file, indent=4)
        return filename

    def get_screenshotfile_texts(self, image_path, *subdirectories, **filename_placeholders):
        screenshot = cv2.imread(image_path)

        return self.get_screenshot_texts(screenshot, *subdirectories, **filename_placeholders)
        

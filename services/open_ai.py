import re
import os
import time
import csv
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from openai import OpenAI, APIStatusError, AzureOpenAI
from services.printr import Printr

printr = Printr()

@dataclass
class AzureConfig:
    api_key: str
    api_base_url: str
    api_version: str
    deployment_name: str

@dataclass
class STTConfig:
    api_key: str = None
    local: bool = False
    stt_provider: str = "openai"
    stt_model: str = "tts-1"
    organization: str | None = None
    base_url: str | None = None
    azure_config: AzureConfig | None = None

PERFORMANCE_CSV_PATH = os.path.join("debug_data", "stt", "performance.csv")

class OpenAi:
    _MAX_TTS_INPUT_CHARS = 4000

    def __init__(
        self,
        api_key: str | None,
        stt_config: STTConfig,
        organization: str | None = None,
        base_url: str | None = None,
    ):
        self.stt_config = stt_config
        self.api_key = api_key

        self.client = None
        if api_key:
            self.client = OpenAI(
                api_key=api_key,
                organization=organization,
                base_url=base_url,
            )
        self.last_error_type = None
        self.last_error_message = None
        self.local_whisper_model = None
        self.local_model_name = None
        self.use_local_default = self.stt_config.local

        self.stt_client = None

        # Whisper und torch nur importieren, wenn lokal genutzt werden soll
        if self.use_local_default:
            try:
                import whisper
                import torch
                WHISPER_AVAILABLE = True
                if torch.cuda.is_available():
                    device = "cuda"
                    print(f"CUDA Available on GPU: {torch.cuda.get_device_name(0)}")
                else:
                    device = "cpu"
                    print("CUDA not available. Using CPU.")
                printr.print(f"Versuche, lokales Whisper Modell zu laden: {self.stt_config.stt_model}...")
                self.local_whisper_model = whisper.load_model(self.stt_config.stt_model, device=device)
                self.local_model_name = self.stt_config.stt_model
                printr.print(f"Lokales Modell '{self.local_model_name}' erfolgreich geladen.")
                self._whisper_device = device
                self._whisper_available = True
                return
            except ImportError:
                self._whisper_available = False
                self.local_whisper_model = None
                self.use_local_default = False
                printr.print_warn("Lokales Whisper Modul nicht gefunden. Lokale Transkription ist nicht verfügbar.")
                printr.print_warn("Installiere es mit: pip install -U openai-whisper")
            except Exception as e:
                printr.print(f"Fehler beim Laden des lokalen Modells '{self.stt_config.stt_model}': {e}", tags="err")
                self.local_whisper_model = None
                self.use_local_default = False

        if self.stt_config.stt_provider == "openai":
            if not self.client:
                printr.print("OpenAI STT provider selected but OpenAI API key is missing.", tags="err")
                return
            self.stt_client = self.client
            return

        if self.stt_config.stt_provider == "azure":
            azure_config = self.stt_config.azure_config
            if azure_config:
                self.stt_client = AzureOpenAI(
                    api_key=azure_config.api_key,
                    azure_endpoint=azure_config.api_base_url,
                    api_version=azure_config.api_version,
                    azure_deployment=azure_config.deployment_name,
                )
                return
            else:
                printr.print("Azure Konfiguration nicht gefunden. ", tags="err")

        if self.stt_config.stt_provider == "groq":
            self.stt_client = OpenAI(
                api_key=self.stt_config.api_key,
                base_url=self.stt_config.base_url
            )
            return

    def _log_performance(self, provider: str, model: str, duration: float, character_count: int = 0):
        try:
            log_dir = os.path.dirname(PERFORMANCE_CSV_PATH)
            os.makedirs(log_dir, exist_ok=True)

            file_exists = os.path.isfile(PERFORMANCE_CSV_PATH)
            with open(PERFORMANCE_CSV_PATH, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['sst_provider', 'model', 'duration_seconds', 'character_count']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                writer.writerow({
                    'sst_provider': provider,
                    'model': model,
                    'duration_seconds': round(duration, 4),
                    'character_count': character_count
                })

        except Exception as e:
            printr.print(f"Fehler beim Schreiben der Performance-CSV: {e}", tags="err")

    def transcribe(
        self,
        filename: str,
        response_format: str = "json",
        **params,
    ):
        if not os.path.exists(filename):
            printr.print(f"Audiodatei nicht gefunden: {filename}", tags="err")
            return None

        start_time = None

        if self.use_local_default:
            try:
                local_whisper_params = {}
                if 'language' in params:
                    local_whisper_params['language'] = params['language']

                start_time = time.time()
                result = self.local_whisper_model.transcribe(filename, **local_whisper_params)
                end_time = time.time()
                duration = end_time - start_time

                self._log_performance(
                    provider=self.stt_config.stt_provider, 
                    model=self.stt_config.stt_model, 
                    duration=duration,
                    character_count=len(result.get("text", ""))
                )

                if response_format == "text":
                    return result.get("text", "")
                else:
                    return SimpleNamespace(text=result.get("text", ""))

            except Exception as e:
                printr.print(f"Fehler bei der lokalen Transkription: {e}", tags="err")
                return None

        else:
            try:
                with open(filename, "rb") as audio_input:
                    start_time = time.time()
                    transcript = self.stt_client.audio.transcriptions.create(
                        model=self.stt_config.stt_model,
                        file=audio_input,
                        response_format=response_format,
                        **params,
                    )
                    end_time = time.time()
                    duration = end_time - start_time

                    self._log_performance(
                        provider=self.stt_config.stt_provider, 
                        model=self.stt_config.stt_model, 
                        duration=duration,
                        character_count=len(transcript.text)
                    )

                    return transcript

            except APIStatusError as e:
                self._handle_api_error(e)
                return None
            except UnicodeEncodeError:
                self._handle_key_error()
                return None
            except Exception as e:
                printr.print(f"Unerwarteter Fehler bei der Remote-Transkription ({self.stt_config.stt_provider}): {e}", tags="err")
                traceback.print_exc()
                return None

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
        azure_config: AzureConfig | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        reasoning_effort: str | None = None,
    ):
        if not model:
            model = "gpt-3.5-turbo-1106"

        client = self.client
        api_type = "OpenAI"

        if azure_config:
            api_type = "Azure"
            try:
                client = AzureOpenAI(
                    api_key=azure_config.api_key,
                    azure_endpoint=azure_config.api_base_url,
                    api_version=azure_config.api_version,
                    azure_deployment=azure_config.deployment_name,
                )
            except Exception as e:
                printr.print(f"Fehler beim Initialisieren des Azure Clients: {e}", tags="err")
                return None
        elif api_key:
            api_type = "OpenAI-compatible"
            try:
                client = OpenAI(
                    api_key=api_key,
                    organization=organization,
                    base_url=base_url,
                )
            except Exception as e:
                printr.print(f"Fehler beim Initialisieren des Clients ({api_type}): {e}", tags="err")
                return None

        if not client:
            printr.print("Kein API Client verfügbar. Bitte API-Schlüssel/Provider-Konfiguration prüfen.", tags="err")
            return None

        self.last_error_type = None
        self.last_error_message = None

        try:
            messages_to_send = self._sanitize_messages_for_tool_call_sequence(messages)
            if len(messages_to_send) != len(messages):
                printr.print(
                    "Sanitized message history before API call to repair tool-call sequence.",
                    tags="warn",
                )
            completion_kwargs = {
                "stream": stream,
                "messages": messages_to_send,
                "model": model,
            }
            if tools:
                completion_kwargs["tools"] = tools
                completion_kwargs["tool_choice"] = "auto"
            if reasoning_effort:
                completion_kwargs["reasoning_effort"] = reasoning_effort

            completion = client.chat.completions.create(**completion_kwargs)
            return completion
        except APIStatusError as e:
            if not tools and self._is_tool_call_without_tools_error(e):
                retry_completion = self._retry_without_tools_instruction(
                    client, completion_kwargs
                )
                if retry_completion is not None:
                    return retry_completion
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None
        except Exception as e:
            printr.print(f"Unerwarteter Fehler bei der Chat Completion mit {api_type}: {e}", tags="err")
            return None

    @staticmethod
    def _is_tool_call_without_tools_error(api_error: APIStatusError) -> bool:
        message = (getattr(api_error, "message", "") or "").lower()
        if "tool choice is none, but model called a tool" in message:
            return True

        try:
            error_json = api_error.response.json()
            error_obj = (error_json or {}).get("error", {})
            error_message = (error_obj.get("message", "") or "").lower()
            error_code = (error_obj.get("code", "") or "").lower()
            return (
                "tool choice is none, but model called a tool" in error_message
                or error_code == "tool_use_failed"
            )
        except Exception:
            return False

    def _retry_without_tools_instruction(self, client, completion_kwargs):
        try:
            original_messages = completion_kwargs.get("messages", [])
            retry_messages = [
                {
                    "role": "system",
                    "content": (
                        "You must not call any tools or functions. "
                        "Respond only with plain text."
                    ),
                }
            ]
            retry_messages.extend(original_messages)
            retry_kwargs = completion_kwargs.copy()
            retry_kwargs["messages"] = retry_messages
            return client.chat.completions.create(**retry_kwargs)
        except Exception:
            return None

    def speak(self, 
              text: str, 
              model: str = "tts-1", 
              voice: str = "nova",
              voice_instruction: str = "",
              player_language: str = "de_DE",):
        try:
            if not voice:
                voice = "nova"

            text = self._sanitize_tts_input(text)
            if not text:
                printr.print_warn("TTS skipped because input text is empty after sanitization.")
                return None

            client_to_use = self.client

            # Ensure voice_instruction is a string
            if voice_instruction is None:
                voice_instruction = ""

            if model == "gpt-4o-mini-tts":
                voice_instruction += f" Please speak in {player_language}."
                response = client_to_use.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=text,
                    instructions=voice_instruction
                )
            else:
                response = client_to_use.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=text,
                )
            return response
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None
        except Exception as e:
            printr.print(f"Unerwarteter Fehler bei der Sprachgenerierung: {e}", tags="err")
            traceback.print_exc()
            return None

    @staticmethod
    def _get_message_role(message):
        if isinstance(message, Mapping):
            return message.get("role")
        return getattr(message, "role", None)

    @staticmethod
    def _get_message_tool_calls(message):
        if isinstance(message, Mapping):
            return message.get("tool_calls")
        return getattr(message, "tool_calls", None)

    @staticmethod
    def _get_tool_call_id(tool_call):
        if isinstance(tool_call, Mapping):
            return tool_call.get("id")
        return getattr(tool_call, "id", None)

    @staticmethod
    def _get_message_tool_call_id(message):
        if isinstance(message, Mapping):
            return message.get("tool_call_id")
        return getattr(message, "tool_call_id", None)

    def _sanitize_messages_for_tool_call_sequence(self, messages):
        """
        Sanitizes a sequence of chat messages to ensure proper pairing between assistant tool calls and corresponding tool responses.
        Args:
            messages (list): A list of chat message dictionaries, each containing information such as role and tool call data.
        Returns:
            list: A sanitized list of messages where:
                - Assistant messages with tool calls are only included if all expected tool responses follow and match their tool call IDs.
                - Tool messages not attached to a valid assistant tool-call block are skipped.
                - Orphaned or incomplete assistant tool calls and their immediate tool blocks are removed.
                - All other messages are preserved.
        The function iterates through the message sequence, grouping assistant tool calls with their corresponding tool responses, and discards any incomplete or orphaned tool call sequences to maintain message integrity.
        """
        if not isinstance(messages, list):
            return messages

        sanitized = []
        i = 0
        total = len(messages)

        while i < total:
            message = messages[i]
            role = self._get_message_role(message)

            if role == "assistant":
                tool_calls = self._get_message_tool_calls(message) or []
                expected_ids = {
                    str(call_id)
                    for call_id in (
                        self._get_tool_call_id(tool_call) for tool_call in tool_calls
                    )
                    if call_id
                }

                if not expected_ids:
                    sanitized.append(message)
                    i += 1
                    continue

                j = i + 1
                collected_tool_messages = []
                collected_ids = set()
                while j < total and self._get_message_role(messages[j]) == "tool":
                    tool_message = messages[j]
                    tool_call_id = self._get_message_tool_call_id(tool_message)
                    if tool_call_id is not None:
                        normalized_id = str(tool_call_id)
                        if normalized_id in expected_ids:
                            collected_tool_messages.append(tool_message)
                            collected_ids.add(normalized_id)
                    j += 1

                if expected_ids.issubset(collected_ids):
                    sanitized.append(message)
                    sanitized.extend(collected_tool_messages)
                # If incomplete, drop the dangling assistant call and its immediate tool block.
                i = j
                continue

            if role == "tool":
                # Orphan tool messages are skipped unless attached to a valid assistant tool-call block above.
                i += 1
                continue

            sanitized.append(message)
            i += 1

        return sanitized

    def _sanitize_tts_input(self, text: str, max_chars: int | None = None) -> str:
        if text is None:
            return ""

        if not isinstance(text, str):
            text = str(text)

        normalized = " ".join(text.split()).strip()
        if not normalized:
            return ""

        hard_limit = max_chars or self._MAX_TTS_INPUT_CHARS
        if len(normalized) <= hard_limit:
            return normalized

        truncated = normalized[:hard_limit]
        cut_candidates = [
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
            truncated.rfind(", "),
            truncated.rfind(" "),
        ]
        cut = max(cut_candidates)
        if cut > int(hard_limit * 0.6):
            truncated = truncated[:cut].strip()
        else:
            truncated = truncated.strip()

        return f"{truncated} ..."

    def _handle_key_error(self):
        printr.print(
            "Der angegebene OpenAI API-Schlüssel ist ungültig oder fehlt. Bitte prüfe die GUI-Einstellungen oder 'secrets.yaml'.",
            tags="err"
        )

    def _handle_api_error(self, api_response: APIStatusError):
        traceback.print_exc()
        printr.print(
            f"Die API meldete den Fehlercode {api_response.status_code} ({api_response.type})",
            tags="err"
        )
        message = api_response.message
        self.last_error_type = None
        self.last_error_message = None
        try:
            error_details = api_response.response.json()
            if isinstance(error_details, dict) and 'error' in error_details:
                if isinstance(error_details['error'], dict) and 'message' in error_details['error']:
                    message = error_details['error']['message']
                elif isinstance(error_details['error'], str):
                    message = error_details['error']
        except Exception:
            traceback.print_exc()
            pass

        m = re.search(
            r"'message': (?P<quote>['\"])(?P<message>.+?)(?P=quote)",
            str(api_response),
        )
        if m:
            extracted_message = m["message"].replace(". ", ".\n")
            printr.print(f"API-Nachricht: {extracted_message}", tags="err")
        elif message:
            printr.print(f"API-Nachricht: {message}", tags="err")
        else:
            printr.print("Die API lieferte keine weiteren Informationen.", tags="err")

        if message:
            self.last_error_message = message
            normalized_message = message.lower()
            if "tool_calls" in normalized_message and "must be followed by tool messages" in normalized_message:
                self.last_error_type = "tool_call_sequence"

        if api_response.status_code == 401:
            printr.print("Authentifizierungsproblem. Überprüfe deinen API-Schlüssel.", tags="err")
        elif api_response.status_code == 404:
            printr.print("Modell nicht verfügbar oder Endpunkt falsch (insbesondere bei Azure).", tags="err")
        elif api_response.status_code == 429:
            printr.print("Ratenlimit oder Kontingent überschritten.", tags="err")

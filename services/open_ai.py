import re
import os
import time
import csv
import traceback
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
    def __init__(
        self,
        api_key: str,
        stt_config: STTConfig,
        organization: str | None = None,
        base_url: str | None = None,
    ):
        self.stt_config = stt_config
        self.api_key = api_key

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
            self.stt_client = self.client
            return

        if self.stt_config.stt_provider == "azure":
            azure_config = self.stt_config.azure_config
            if azure_config:
                self.sst_client = AzureOpenAI(
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

        self.last_error_type = None
        self.last_error_message = None

        try:
            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model,
                    tools=tools,
                    tool_choice="auto",
                )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:
            self._handle_key_error()
            return None
        except Exception as e:
            printr.print(f"Unerwarteter Fehler bei der Chat Completion mit {api_type}: {e}", tags="err")
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
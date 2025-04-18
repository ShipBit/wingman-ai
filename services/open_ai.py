import re
import os
import time # Hinzugefügt für Zeitmessung
import csv  # Hinzugefügt für CSV-Handling
import traceback
from dataclasses import dataclass
from types import SimpleNamespace
import whisper
import torch

from openai import OpenAI, APIStatusError, AzureOpenAI
from services.printr import Printr

printr = Printr()  # Annahme: Printr ist global oder wird hier instanziiert

# Versuche, Whisper zu importieren. Gib eine Warnung aus, wenn es nicht installiert ist.
try:
    import whisper
    WHISPER_AVAILABLE = True
    if torch.cuda.is_available():
        device = "cuda"
        print(f"CUDA Available on GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = "cpu"
        print("CUDA not available. Using CPU.")
except ImportError:
    whisper = None
    WHISPER_AVAILABLE = False
    printr.print_warn("Lokales Whisper Modul nicht gefunden. Lokale Transkription ist nicht verfügbar.")
    printr.print_warn("Installiere es mit: pip install -U openai-whisper")


@dataclass
class AzureConfig:
    api_key: str
    api_base_url: str
    api_version: str
    deployment_name: str

@dataclass
class STTConfig:
    api_key: str = None
    local: bool = False  # Standardwert für lokale Nutzung
    stt_provider: str = "openai"  # Standardanbieter
    stt_model: str = "tts-1"  # Standardmodell für TTS
    organization: str | None = None
    base_url: str | None = None
    azure_config: AzureConfig | None = None

# Pfad für die Performance-CSV-Datei
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
        self.local_whisper_model = None
        self.local_model_name = None # Name des geladenen lokalen Modells speichern
        self.use_local_default = self.stt_config.local # Standardverhalten speichern

        self.stt_client = None

        if self.use_local_default:
            if WHISPER_AVAILABLE:
                printr.print(f"Versuche, lokales Whisper Modell zu laden: {self.stt_config.stt_model}...")
                try:
                    # Hier könntest du optional 'device="cuda"' hinzufügen, wenn eine GPU verfügbar ist
                    self.local_whisper_model = whisper.load_model(self.stt_config.stt_model, device=device)
                    self.local_model_name = self.stt_config.stt_model  # Namen speichern
                    printr.print(f"Lokales Modell '{self.local_model_name}' erfolgreich geladen.")
                    return
                except Exception as e:
                    printr.print(f"Fehler beim Laden des lokalen Modells '{self.stt_config.stt_model}': {e}", tags="err")
                    self.local_whisper_model = None  # Sicherstellen, dass es None ist bei Fehler
                    self.use_local_default = False  # Lokale Nutzung deaktivieren, wenn Laden fehlschlägt
            else:
                # Warnung wurde bereits oben ausgegeben
                self.use_local_default = False  # Lokale Nutzung ist nicht möglich
        
        if self.stt_config.stt_provider == "openai":
            self.stt_client = self.client
            return
        
        if self.stt_config.stt_provider == "azure":
            # Azure Konfiguration aus dem STT-Config-Datensatz extrahieren
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
        """Schreibt die Transkriptionsperformance in eine CSV-Datei."""
        # --- Punkt 5: CSV-Pfad prüfen und ggf. anlegen ---
        try:
            log_dir = os.path.dirname(PERFORMANCE_CSV_PATH)
            os.makedirs(log_dir, exist_ok=True)

            # --- Punkt 6 & 7: CSV wachsen lassen und Daten schreiben ---
            file_exists = os.path.isfile(PERFORMANCE_CSV_PATH)
            with open(PERFORMANCE_CSV_PATH, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['sst_provider', 'model', 'duration_seconds', 'character_count']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()  # Schreibe Header nur, wenn Datei neu ist

                writer.writerow({
                    'sst_provider': provider,
                    'model': model,
                    'duration_seconds': round(duration, 4), # Runde auf 4 Nachkommastellen
                    'character_count': character_count
                })
            # printr.print(f"Performance-Daten geloggt: {provider}, {model}, {duration:.4f}s", tags="info") # Optional: Bestätigung ausgeben

        except Exception as e:
            printr.print(f"Fehler beim Schreiben der Performance-CSV: {e}", tags="err")

    def transcribe(
        self,
        filename: str,
        response_format: str = "json",
        **params,
    ):
        """
        Transkribiert eine Audiodatei entweder über die OpenAI/Azure API oder lokal mit Whisper.
        Misst die Dauer und loggt die Performance.
        """
        if not os.path.exists(filename):
            printr.print(f"Audiodatei nicht gefunden: {filename}", tags="err")
            return None

        start_time = None # Initialisieren für den Fall eines frühen Fehlers

        if self.use_local_default:
            try:
                local_whisper_params = {}
                if 'language' in params:
                    local_whisper_params['language'] = params['language']
                # Füge hier weitere unterstützte Parameter hinzu, falls nötig

                # --- Punkt 4: Zeitmessung Start (Lokal) ---
                start_time = time.time()
                result = self.local_whisper_model.transcribe(filename, **local_whisper_params)
                # --- Punkt 4: Zeitmessung Ende (Lokal) ---
                end_time = time.time()
                duration = end_time - start_time

                # --- Punkt 5, 6, 7: Performance loggen (Lokal) ---
                self._log_performance(
                    provider=self.stt_config.stt_provider, 
                    model=self.stt_config.stt_model, 
                    duration=duration,
                    character_count=len(result.get("text", ""))
                )

                # Gib das Ergebnis in einem konsistenten Format zurück
                if response_format == "text":
                    return result.get("text", "")
                else:
                    # Erstelle ein SimpleNamespace, das dem API-Ergebnis ähnelt
                    return SimpleNamespace(text=result.get("text", ""))

            except Exception as e:
                printr.print(f"Fehler bei der lokalen Transkription: {e}", tags="err")
                # Optional: Zeit loggen, auch wenn fehlgeschlagen? Eher nicht sinnvoll für Performance-Vergleich.
                return None

        else:
            # --- Remote Transkription ---
            try:
                with open(filename, "rb") as audio_input:
                    # --- Punkt 4: Zeitmessung Start (Remote) ---
                    start_time = time.time()
                    transcript = self.stt_client.audio.transcriptions.create(
                        model=self.stt_config.stt_model,  # Hier das API-Modell (z.B. whisper-1) übergeben
                        file=audio_input,
                        response_format=response_format,
                        **params,
                    )
                    # --- Punkt 4: Zeitmessung Ende (Remote) ---
                    end_time = time.time()
                    duration = end_time - start_time

                    # --- Punkt 5, 6, 7: Performance loggen (Remote) ---
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
            model = "gpt-3.5-turbo-1106"  # Oder ein anderes Standardmodell

        client = self.client
        api_type = "OpenAI"  # Für Logging

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
        # else Block für OpenAI API Aufruf
        # Wichtiger Hinweis: Der folgende else-Block war in deinem Originalcode nicht korrekt eingerückt
        # und würde nur ausgeführt, wenn KEINE Azure-Konfiguration vorliegt. Ich gehe davon aus,
        # dass der API-Aufruf *immer* stattfinden soll, entweder mit dem Azure-Client oder dem Standard-OpenAI-Client.
        # Ich korrigiere die Einrückung hier.
        # else: # Dieser else-Block ist wahrscheinlich nicht gewollt, wenn der Code danach immer laufen soll.
        try:
            # Verwende den zuvor bestimmten Client (entweder Standard oder Azure)
            if not tools:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model, # Bei Azure wird hier der Deployment-Name erwartet, wenn der AzureClient genutzt wird
                )
            else:
                completion = client.chat.completions.create(
                    stream=stream,
                    messages=messages,
                    model=model, # Bei Azure wird hier der Deployment-Name erwartet
                    tools=tools,
                    tool_choice="auto",
                )
            return completion
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:  # unwahrscheinlich mit Client > 1.0
            self._handle_key_error()
            return None
        except Exception as e:
            # Verwende api_type für die Fehlermeldung
            printr.print(f"Unerwarteter Fehler bei der Chat Completion mit {api_type}: {e}", tags="err")
            return None

    def speak(self, text: str, model: str = "tts-1", voice: str = "nova"):
        # Hinweis: Diese Methode verwendet *immer* die Remote API (OpenAI),
        # da lokales TTS nicht Teil von Whisper ist. Azure TTS wäre eine separate Implementierung.
        try:
            if not voice:
                voice = "nova"
            # Prüfen, ob Azure TTS verwendet werden soll (falls du das später hinzufügst)
            # Aktuell wird immer der Standard OpenAI Client verwendet.
            # if azure_config and hasattr(azure_config, 'tts_deployment_name'): # Beispiel für zukünftige Erweiterung
            #     # Erstelle Azure TTS Client...
            #     pass
            # else:
            #     client_to_use = self.client # Standard OpenAI

            client_to_use = self.client # Vorerst immer OpenAI

            response = client_to_use.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
            )
            # response ist ein StreamingBody, der direkt in eine Datei geschrieben werden kann
            # z.B. response.stream_to_file("output.mp3")
            return response
        except APIStatusError as e:
            self._handle_api_error(e)
            return None
        except UnicodeEncodeError:  # unwahrscheinlich mit Client > 1.0
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

        if api_response.status_code == 401:
            printr.print("Authentifizierungsproblem. Überprüfe deinen API-Schlüssel.", tags="err")
        elif api_response.status_code == 404:
            printr.print("Modell nicht verfügbar oder Endpunkt falsch (insbesondere bei Azure).", tags="err")
        elif api_response.status_code == 429:
            printr.print("Ratenlimit oder Kontingent überschritten.", tags="err")
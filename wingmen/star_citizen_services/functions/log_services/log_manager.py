import json
import os
import traceback
import uuid
from datetime import datetime, timezone


from services.printr import Printr
from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext

# Beispielhafter Prompt für Zusammenfassungen
LOG_ENTRY_PROMPT = """
Du bist ein Assistent, der Log-Daten-Einträge aus dem Spiel Star Citizen überprüfst und überarbeitet.
Du erhälst die log daten als JSON object. Unveränderliche Informationen sind im Feld 'current_context_logs' enthalten. Du überarbeitest nur den Eintrag 'new_log_entry' und gibst nur diesen zurück.
1. Gebe ein erweitertes sowie korrigiertes JSON Object zurück. Ohne Kommentare oder zusätzliche Informationen und ohne Codeblöcke (```)
2. Aus dem Feld 'notes' sowie aus dem bisherigen Kontext extrahierst Du Informationen um den 'log_type' zu bestimmen, den 'event_type' sowie um das 'data'-Objekt zu erstellen.
Vorherige Werte werden in 'existing_log_types' und 'existing_event_types' bereitgestellt. Verwende diese bevorzugt, aber erstelle neue, wenn sinnvoll.
3. Aus dem Kontext der aktuellen Session (ältere log-einträge), kannst Du den zu überarbeitenden Eintrag besser verstehen und ggfs. anpassen.
4. Du achtest darauf keine Informationen zu erfinden, sondern vorhandene Informationen zu überprüfen und ggfls. zu korrigieren andhand des Kontexts.
5. Orientiere Dich an vergangene Struktur vergangener Einträge um eine konsistente Struktur des neuen Log-Eintrags zu gewährleisten.
6. Wenn Du das 'data' Objekt erstellst, überarbeite den 'notes' Eintrag, damit dieser keine redundanten informationen enthält.
7. Um das 'data' Objekt zu erstellen, halte Dich an folgende Beispiele sowie an die Struktur der bisherigen Einträge.

Beispiele für 'data' basierend auf 'event_type':

1. 
log_type: "MINING"
event_type: "START_SESSION"
structured_data: {
    "start_location": "Brio's Breaker Yard",
    "ship": "Prospector",
    "direction": "Mining Area 141"
}

2. 
log_type: "MINING"
event_type: "FOUND_DEPOSIT"
structured_data: {
    "deposit_type": "Felsig-Deposit",
    "quantity": 3
}

3. 
log_type: "MINING"
event_type: "SCAN_DEPOSIT"
structured_data: {
    "deposit_type": "Felsig-Deposit",
    "mass_kg": 4480,
    "composition_percent": {
        "Bexalit": 32,
        "Copper": 43
    }
}

4. 
log_type: "MINING"
event_type: "STOP_SESSION"
structured_data: {
    "end_location": "CRU-L1",
    "cargo_scu": {
        "Agricium": 12,
        "Laranite": 20
    }
}

Beispielantworten die ich erwarte:

{
    "timestamp": "2025-01-05T10:29:51Z",
    "log_type": "MINING",
    "event_type": "START_SESSION",
    "location": "Daymar",
    "notes": "Beginn einer Mining-Session auf Daymar.",
    "session_id": "session-1234",
    "data": {
        "start_location": "Brio's Breaker Yard",
        "ship": "Prospector",
        "direction": "Mining Area 141"
    }
}

oder

{
    "timestamp": "2025-01-05T10:34:14Z",
    "log_type": "MINING",
    "event_type": "FOUND_DEPOSIT",
    "location": "Daymar",
    "notes": "",
    "session_id": "session-1234",
    "data": {
        "deposit_type": "Felsig-Deposit",
        "quantity": 3
    }
}

oder

{
    "timestamp": "2025-01-05T10:35:42Z",
    "type": "MINING",
    "event_type": "SCAN_DEPOSIT",
    "location": "Daymar",
    "notes": "Zweiter Stein gefunden mit 32% Bexalid und 43% Kupfer, Masse von 4480. Versuch es nochmal.",
    "session_id": "session-1234",
    "data": {
        "deposit_type": "Felsig-Deposit",
        "mass_kg": 4480,
        "composition_percent": {
            "Bexalit": 32,
            "Copper": 43
        }
    }
}

"""

SUMMERIZE_PROMPT = """
            Du bist ein Assistent, der Log-Daten-Einträge aus dem Spiel Star Citizen zusammenfasst.
            Hintergrund ist, dass für den Spieler wichtige Gedächtnis-Informationen bereitgestellt werden sollen. 
            Diese müssen ultrakompakt sein. Sie sind nicht für den Menschen gedacht, sondern für ein Modell, welches daraus wiederrum
            Text für den Spieler generieren kann. Hierfür erstellst Du ein JSON-Objekt, welches die wichtigsten Informationen enthält.
            1. Erstelle aus allen Einträgen ein einzelnes JSON-Objekt, welches die wichtigsten Informationen enthält.
            2. Achte darauf, dass die Informationen so kompakt wie möglich sind, aber dennoch alle wichtigen Details enthalten.
            3. Vermeide redundante Informationen und fasse Informationen zusammen, wenn möglich.
            4. Achte darauf, dass Du keine Jahresinformationen angibst.
            5. Achte darauf, dass Zahlen immer in Ziffern geschrieben werden.
            6. Wenn Du aus den Informationen herauskristallisieren kannst, dass mehrere unterschiedliche 'Memory'-Einträge 
            erstellst werden sollten, da diese semantisch zu unterschiedlich sind um sie in einem Eintrag zusammenzufassen, ist das OK.
            Beispiel: Es gibt Einträge, die sich auf 'Mining' beziehen und Einträge, die sich auf 'Trading' beziehen, dann könnte es
            sinnvoll sein, zwei separate 'Memory'-Einträge zu erstellen.
            7. Notes should only contain the key facts of all entries, without duplicating information found in other fields.
            8. Ein Memory-Eintrag könnte wie folgt aussehen:
            {
                "time_start": "2025-01-05T10:35:42Z",
                "time_end": "2025-01-05T10:35:42Z",
                "log_type": "MEMORY",
                "session_id": "session-1234",
                "locations": "Daymar, CRU-L1, Brio's Breaker Yard, Mining Area 141",
                "memory_type": "MINING",
                "notes": "4h session, bad experience, lots of rocks, not much valuable ore",
                "data": {
                    "refinery": {
                        "work_orders": 2,
                        "location": "CRU-L1",
                        "total_cost": 1000,
                    }
                    "raw_selling": 1,
                    "raw_benefit": 1000,
                    "total_cargo_scu": 150,
                    "total_valuable_materials_found_scu: {
                        "Bexalit": 32,
                        "Taranite": 43,
                        "Gold": 25,
                        "Copper": 12,
                    },
                    "rock_compositions": {
                        [
                            "rock: {
                                "mass_kg": 4480,
                                "composition_percent": {
                                    "Bexalit": 32,
                                    "Copper": 43
                                }
                            },
                            "rock: {
                                "mass_kg": 4480,
                                "composition_percent": {
                                    "Taranite": 32,
                                    "Titanium": 43
                                }
                            }
                        
                        ]
                    }
                }
            }
            9. Orientiere Dich auch an älteren Memory-Einträgen um eine konsistente Struktur zu gewährleisten.
        """

DEBUG = True
printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class AdvancedGenericLogManager(FunctionManager):
    """
    Ein erweiterter Log-Manager, der:
    1) Alle Logs dauerhaft in 'full_logs' speichert (Datei bleibt vollständig).
    2) Eine In-Memory-Liste 'recent_logs' mit bis zu 100 Einträgen hält (aktuelles Wissen).
    3) Zusammenfassungen in 'summaries' speichert, sobald Daten älter sind oder man Filter-Abfragen stellt.
    4) Standardmäßig bei 'list_logs' nur die letzten 100 Einträge (recent_logs) zurückgibt,
       es sei denn, man möchte explizit ältere / zusammengefasste Logs oder Filter.
    5) Grenzen checkt (max. 100 Einträge / 10.000 Zeichen in-memory).
       Wird dies überschritten, werden die ältesten Einträge in-memory zusammengefasst
       und als "MEMORY"-Log in 'summaries' abgelegt. Die Datei mit 'full_logs' bleibt unverändert.

    Datei-Struktur (Beispiel):
    {
      "full_logs": [...],
      "summaries": {
        "custom_summaries": [...],  # Manuell erstellte Zusammenfassungen via build_summary
        "memory_summaries": [...],  # Automatisch erstellte Zusammenfassungen (ältere in-memory Logs)
      }
    }
    """
    MANAGER_CONTEXT = AIContext.CORA
    MANAGER_DESCRIPTION = "Persistent session logbook with filtered queries and automatic/custom summaries."
    MANAGER_CAPABILITIES = [
        "Create log entries and split sessions",
        "Retrieve logs filtered or in full",
        "Generate and store summaries from logs",
    ]

    MAX_LOG_ENTRIES = 100          # maximal 100 Einträge in recent_logs
    MAX_LOG_CHARACTERS = 10000     # maximal 10.000 Zeichen als JSON in-memory

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        self.config = config

        # Pfad zur JSON-Datei, in der wir alles speichern
        self.log_file_path = config.get("AdvancedGenericLogManager", {}).get("log_file_path", "star_citizen_data/logs/log_memories.json")

        # Aktuelle Spielversion
        self.current_game_version = config.get("sc-keybind-mappings", {}).get("sc_channel_version", "UNSET_VERSION")
        self.current_play_session = f"session-{uuid.uuid4()}"  # Eindeutige Session-ID

        # Datei laden oder neu anlegen
        self.full_logs = []  # Alle jemals erstellten Logs
        self.summaries = {
            "custom_summaries": [],   # vom Nutzer/dir erstellte Filter-Zusammenfassungen
            "memory_summaries": []    # automatisches Zusammenfassen bei Limit-Überschreitungen
        }
        if os.path.exists(self.log_file_path):
            self._load_from_file()

        # Die letzten 100 Einträge für aktives "Wissen"
        # => Holen wir aus full_logs (Ende), wenn vorhandene Logs < 100, dann eben alle.
        self.recent_logs = self.full_logs[-self.MAX_LOG_ENTRIES:]

    def get_context_mapping(self) -> AIContext:
        """
        Verortet diesen Manager im CORA-Kontext.
        """
        return AIContext.CORA

    def register_functions(self, function_register):
        """
        Hier registrieren wir die Funktionen,
        die Cora via ChatGPT-Funktion-Calling aufrufen kann.
        """
        function_register[self.add_log_entry.__name__] = self.add_log_entry
        function_register[self.get_logs_entries.__name__] = self.get_logs_entries
        function_register[self.build_log_entry_summary.__name__] = self.build_log_entry_summary

    def get_function_prompt(self):
        """
        Beschreibt, wie Cora diese Funktionen nutzen kann.
        """
        return (
            "Du kannst jederzeit wichtige Information ins Logbuch eintragen:\n"
            f"- '{self.add_log_entry.__name__}': Rufe diese Funktion auf, wenn ein neuer Log-Eintrag erstellt werden soll. \n"
            f"- '{self.get_logs_entries.__name__}': Gibt Log-Einträge zurück, standardmäßig die letzten 100.\n"
            "                Mit Filtern (z.B. log_type, version, session) können gezielt Einträge abgefragt werden.\n"
            f"- '{self.build_log_entry_summary.__name__}': Erzeugt eine Zusammenfassung aus dem Log-Buch zu bestimmten Filter-Kriterien (z.B. alle Mining-Logs).\n"
        )

    def get_function_tools(self):
        """
        OpenAI-Function-Signaturen für die oben genannten Methoden.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": self.add_log_entry.__name__,
                    "description": "Speichert einen neuen Log-Eintrag (mit automatisch gesetztem Zeitstempel).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_session": {
                                "type": "boolean",
                                "description": "Wenn true, wird dieser und folgende Log-Einträge mit einer neuen Session-ID versehen. Setze dies nur auf Wunsch des Spielers. Optional."
                            },
                            "notes": {
                                "type": "string",
                                "description": "Informationen die ins Logbuch eingetragen werden sollen. Pflichtfeld."
                            }
                        },
                        "required": ["notes"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.get_logs_entries.__name__,
                    "description": (
                        "Gibt Log-Einträge zurück. Standardmäßig nur die letzten 100 (in-memory). "
                        "Über Filter kann man ältere Einträge anfragen (dann ggf. als Zusammenfassung)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "log_type": {
                                "type": "string",
                                "description": "Filter nach Log-Type. Optional.",
                                "enum": self._get_log_types()
                            },
                            "session": {
                                "type": "boolean",
                                "description": "Wenn true, werden Einträge zur aktuellen Session zurückgegeben. Optional."
                            },
                            "fetch_full": {
                                "type": "boolean",
                                "description": "Wenn True, werden ALLE Logs berücksichtigt. Nutze dies nur in Kombination mit einem Filter."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": self.build_log_entry_summary.__name__,
                    "description": (
                        "Erzeugt eine Zusammenfassung bestimmter Logs. "
                        "Wird in 'summaries.custom_summaries' gespeichert."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "log_type": {
                                "type": "string",
                                "description": "Filter nach Log-Type. Optional.",
                                "enum": self._get_log_types() + [None]
                            },
                            "session": {
                                "type": "boolean",
                                "description": "Wenn True, wird eine Zusammenfassung der aktuellen Session gemacht. Optional."
                            }
                        }
                    }
                }
            }
        ]

    # ----------------------------------------------------------------
    # Öffentliche Funktionen, die via ChatGPT-Funktionen aufgerufen werden können
    # ----------------------------------------------------------------

    def add_log_entry(self, args):
        """
        Speichert einen neuen Log-Eintrag, automatisch mit Zeitstempel.
        """
        printr.print(f"Executing function '{self.add_log_entry.__name__}' with params:\n {json.dumps(args, indent=2)}", tags="info")

        notes = args.get("notes")
        new_session = args.get("new_session", False)
        if new_session:
            self.current_play_session = f"session-{uuid.uuid4()}"

        new_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "log_id": f"log-{uuid.uuid4()}",
            "game_version": self.current_game_version,
            "session_id": self.current_play_session,
            "log_type": "",
            "event_type": "",
            "notes": notes,
            "data": {}
        }

        session_logs = self._filter_logs(self.full_logs, sessionId=self.current_play_session)

        user_prompt = {
            "current_context_logs": session_logs,
            "new_log_entry": new_entry,
            "existing_log_types": self._get_log_types(),
            "existing_event_types": self._get_event_types()
        }
        completion = self.ask_ai(
            LOG_ENTRY_PROMPT,
            user_prompt=json.dumps(user_prompt, ensure_ascii=False),
            max_tokens=1024,
            llm_call="log_entry_enrichment",
        )

        new_entry = self._extract_json_response(completion)

        # In vollem Log speichern (Datei bleibt immer intakt)
        self.full_logs.append(new_entry)

        # Auch in der in-memory-Liste (aktuelles Wissen)
        self.recent_logs.append(new_entry)

        # Check, ob wir die 100 Einträge in-memory überschreiten
        if len(self.recent_logs) > self.MAX_LOG_ENTRIES:
            self._consolidate_memory_logs()

        # Persistieren (full_logs + summaries) in Datei
        self._persist_to_file()

        printr.print(f"Stored\n {json.dumps(new_entry, indent=2)}", tags="info")

        return {
            "success": True,
            "message": "Antworte nur: 'Eintrag hinzugefügt.'",
        }

    def get_logs_entries(self, args):
        """
        Gibt Logs zurück. Standardmäßig nur die letzten 100 (recent_logs).
        Kann Filter enthalten:
            - log_type
            - game_version
            - older_than (Datum)
        Wenn fetch_full=True, liefert alle Logs (full_logs) – kann sehr groß sein.
        Ansonsten, wenn Logs älter als was in memory ist, kann es sein,
        dass wir nur Summaries zurückgeben.
        """
        printr.print(f"Executing function '{self.get_logs_entries.__name__}' with params:\n {json.dumps(args, indent=2)}.", tags="info")
        log_type = args.get("log_type", None)
        game_version = args.get("game_version", self.current_game_version)
        sessionId = self.current_play_session if args.get("session", False) else None

        fetch_full = args.get("fetch_full", False)

        if not fetch_full:
            # Wir geben nur recent_logs oder gefilterte Ausschnitte davon zurück
            filtered = self._filter_logs(self.recent_logs, log_type, game_version, sessionId)
            return {
                "success": True,
                "logs_returned": len(filtered),
                "logs": filtered,
                "message": (
                    "Fasse die Logs narrativ und ohne Formatierung zusammen, sodass sie gut für eine TTS-Engine ausgesprochen werden können, "
                    "damit der Spieler einen Überblick bekommt, ohne zu sehr ins Detail zu gehen. "
                    "Achte auf die Ansprache, da Du die Informationen dem Spieler präsentierst. "
                    "Kristallisiere die wichtigsten Eckdaten zusammen. Gehe nicht zu sehr in die zeitlichen Details, insbesondere gebe keine Jahreszahlen an. "
                    "Frage nach, ob mehr Details benötigt werden."
                )
            }
        # fetch_full => sehr große Menge an Logs!
        # Wir holen ALLE aus full_logs (und filtern optional)
        filtered = self._filter_logs(self.full_logs, log_type, game_version, sessionId)
        return {
            "success": True,
            "logs_returned": len(filtered),
            "logs": filtered,
            "message": (
                "Du hast ALLE Logs angefordert. "
                "Hinweis: Ältere In-Memory-Logs wurden zu MEMORY-Einträgen zusammengefasst. "
                "Formuliere diese aus, ohne neue Details zu erfinden."
            )
        }

    def build_log_entry_summary(self, args):
        """
        Erstellt eine Zusammenfassung (z.B. aller MINING-Logs) und speichert sie in
        'summaries.custom_summaries'.
        Filter: log_type, game_version, older_than
        """
        printr.print(f"Executing function '{self.build_log_entry_summary.__name__}' with params:\n {json.dumps(args, indent=2)}.", tags="info")
        log_type = args.get("log_type", None)
        sessionId = self.current_play_session if args.get("session", False) else None

        # Filter aus full_logs
        relevant_logs = self._filter_logs(self.full_logs, log_type=log_type, sessionId=sessionId)
        if not relevant_logs:
            return {
                "success": False,
                "summary": "",
                "message": "Keine passenden Logs zum Zusammenfassen gefunden."
            }

        # per OpenAI zusammenfassen
        summary_logs = {}
        try:
            summary_logs = self._openai_summarize_logs(relevant_logs)
        except Exception as e:
            print(f"Error in Zusammenfassung: {e}")
            print(traceback.format_exc(e))

        self.summaries["custom_summaries"].append(summary_logs)
        self._persist_to_file()

        printr.print(f"Summary:\n{json.dumps(summary_logs, indent=2)}", tags="info")
        response = {
            "success": True,
            "summary": summary_logs,
            "message": "Zusammenfassung gespeichert",
            "additional_instructions": (
                "Fasse die Zusammenfassung narrativ zusammen, sodass sie gut für eine TTS-Engine ausgesprochen werden kann, "
                "damit der Spieler einen Überblick bekommt, ohne zu sehr ins Detail zu gehen. "
                "Achte auf die Ansprache, da Du die Informationen dem Spieler präsentierst. "
                "Gebe keine Jahreszahlen an."
            )
        }

        return json.dumps(response, ensure_ascii=False)

    # ----------------------------------------------------------------
    # Interne Hilfsfunktionen
    # ----------------------------------------------------------------

    def _get_log_types(self):
        """
        Gibt eine Liste von einzigartigen Log-Typen zurück.
        """
        return list(set([log.get("log_type") for log in self.full_logs]))
    
    def _get_event_types(self):
        """
        Gibt eine Liste von einzigartigen Log-Typen zurück.
        """
        return list(set([log.get("event_type") for log in self.full_logs]))
    
    def _get_log_versions(self):
        """
        Gibt eine Liste von einzigartigen Spielversionen zurück.
        """
        return list(set([log.get("game_version") for log in self.full_logs]))
    
    def _filter_logs(self, logs_list, log_type=None, game_version=None, sessionId=None):
        """
        Hilfsfunktion, um die übergebene Liste von Logs nach log_type,
        game_version und older_than_dt zu filtern.
        """
        result = []
        for log_item in logs_list:
            if log_type and log_item.get("log_type") != log_type:
                continue
            if game_version and log_item.get("game_version") != game_version:
                continue
            if sessionId and log_item.get("session_id") == sessionId:
                continue
            result.append(log_item)
        return result

    def _char_count_exceeds_limit(self):
        """
        Prüft, ob die JSON-Repräsentation von recent_logs die MAX_LOG_CHARACTERS übersteigt.
        """
        as_json = json.dumps(self.recent_logs, ensure_ascii=False)
        return len(as_json) > self.MAX_LOG_CHARACTERS

    def _consolidate_memory_logs(self):
        """
        Logik:
        1) Aus full_logs nehmen wir alle Einträge, die nicht von der aktuellen Session sind.
        2) Aus den Full logs holen wir jeweils die Einträge für diese Sessions.
        3) Wir fassen diese zusammen. 
        4) Aus den Full logs entfernen wir die Einträge, die wir zusammengefasst haben.
        5) Wir fügen die Zusammenfassung in die summaries hinzu.
        6) Aus den recent_logs entfernen wir die zusammengefassten Einträge und fügen die Zusammenfassung an den Anfang.
        """
        entries_to_summaries = []
        for log in self.full_logs[:]: # Kopie der Liste erstellen, um während der Iteration Elemente zu entfernen
            if log["session_id"] != self.current_play_session:
                entries_to_summaries.append(log)
                self.full_logs.remove(log)

        try:
            memory_logs = self._openai_summarize_logs(entries_to_summaries)
            self.summaries["memory_summaries"].append(memory_logs)
        except Exception as e:
            print("Fehler bei Zusammenfassung von Log-Buch-Einträgen: {e}")
            print(traceback.print_exc(e))
    
        # Wir werden aus dem kurzzeitgedeächtnis 50% der Einträge entfernen und durch die Zusammenfassung ersetzen
        cutoff = len(self.recent_logs) // 2

        self.recent_logs = self.full_logs[:cutoff]  # Die ersten 50% der Einträge behalten
        
    def _openai_summarize_logs(self, log_entries):
        """
        Ruft OpenAI auf, um die übergebenen Log-Einträge (log_entries) zu einem knappen
        Text zu komprimieren.
        """
        user_prompt = {
            "logs_to_summarize": log_entries,
        }
        completion = self.ask_ai(
            SUMMERIZE_PROMPT,
            user_prompt=json.dumps(user_prompt, ensure_ascii=False),
            max_tokens=4096,
            llm_call="log_summary",
        )

        new_entry = self._extract_json_response(completion)
        
        print_debug(f"OpenAI completion: {new_entry}")

        return new_entry

    def _extract_json_response(self, completion):
        raw_answer = completion.choices[0].message.content.strip()

        # Falls das Modell Backticks für Codeblöcke verwendet:
        if raw_answer.startswith("```json"):
            # Entferne leading ```json und trailing ```
            raw_answer = raw_answer.split("```json", 1)[-1]
        if raw_answer.endswith("```"):
            raw_answer = raw_answer.rsplit("```", 1)[0]
        return json.loads(raw_answer)

    def _load_from_file(self):
        """
        Lädt 'full_logs' und 'summaries' aus der JSON-Datei, falls vorhanden.
        """
        try:
            with open(self.log_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.full_logs = data.get("full_logs", [])
                self.summaries = data.get("summaries", {
                    "custom_summaries": [],
                    "memory_summaries": []
                })
        except Exception as e:
            print(f"[WARN] Datei '{self.log_file_path}' konnte nicht geladen werden: {e}")

    def _persist_to_file(self):
        """
        Schreibt full_logs und summaries in die Datei.
        """
        # Verzeichnis extrahieren und ggf. anlegen
        directory = os.path.dirname(self.log_file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        data = {
            "full_logs": self.full_logs,
            "summaries": self.summaries
        }
        try:
            with open(self.log_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] Konnte Datei '{self.log_file_path}' nicht speichern: {e}")

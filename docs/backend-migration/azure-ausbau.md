# Azure raus, vollständig

Ab v3 ist Azure in Wingman kein unterstützter Anbieter mehr — weder als
Backend für Wingman Pro noch als externer Anbieter, den ein Nutzer mit eigenem
Konto einträgt. Wenn dieser Plan abgearbeitet ist, soll in Core und Client
keine Spur von Azure mehr sein.

## Warum das geht

Es gibt kein Szenario, in dem eine Installation beide Backends können muss:

* **2.1.1-Kunden** bleiben auf dem alten Azure-Backend. Ihr Client hat gar
  keinen Updater, der sie auf v3 ziehen könnte.
* **v3-Tester** bekommen 3.2.0 über den `unstable`-Kanal und sind damit auf dem
  neuen Backend.
* Der öffentliche v3-Release kommt erst, wenn v3 fertig ist — dann wechseln
  alle auf einmal.

Rückwärtskompatibilität ist also keine Anforderung. Zwei Wege parallel zu
pflegen kostet nur Aufwand und erzeugt Fehler: das kaputte Account-Menü vom
11.09. kam genau daher, dass eine Bedingung auf ein MSAL-Objekt zeigte, das im
neuen Weg nie existiert.

## Umfang, gemessen am 2026-09-11

| | |
|---|---|
| Core | 210 Zeilen Python in 23 Dateien, 5 Zeilen in den Config-Vorlagen |
| Client | 354 Zeilen, davon 25 Dateien generierte API-Modelle |
| Abhängigkeiten | `@azure/msal-browser` (Client), `azure-cognitiveservices-speech` (Core, **14 MB**) |

Die 25 generierten Client-Modelle verschwinden von allein, sobald Core sauber
ist und der Client neu generiert wird.

## Vier Dinge heißen „Azure", nur drei sind dasselbe

1. **Wingman Pro über B2C und MSAL** — der Login. Ersetzt durch Supabase.
2. **Azure OpenAI als eigener Anbieter** — für Nutzer mit eigenem Azure-Konto.
3. **Azure Speech als TTS und STT** — Stimmen und Spracherkennung.
4. **Azure Speech für die Sprachaktivierung** — `speechsdk.SpeechRecognizer`
   in `wingman_core.py`, kontinuierliche Erkennung.

Punkt 4 ist keine Backend-Anbindung, sondern eine laufende Funktion. Der
Ersatz ist schon da und sogar Standard: **Parakeet**, dazu whispercpp und
fasterwhisper, alle lokal. Der Ausbau kostet also keine Fähigkeit, er entfernt
eine Cloud-Abhängigkeit — und nimmt 14 MB samt einer nativen Bibliothek aus
dem Build, die bei Windows- und macOS-Paketen Sonderbehandlung braucht.

**Was Nutzer wirklich verlieren:** die Azure-exklusiven Stimmen. Die werden
ohnehin schon migriert (Azure-Stimme → OpenAI-Stimme gleichen Geschlechts,
`migration_316_to_320.py`).

## Drei Fallen

### Die Migrationen müssen Azure weiter lesen können

Ein 2.1.1-Nutzer durchläuft irgendwann die ganze Migrationskette bis 3.2. Die
Migrationen arbeiten auf rohen Dicts, nicht auf den Enums — sie überleben das
Löschen der Enums also. Aber die Zeichenketten `"azure"`, `"azure_speech"`
müssen in den Migrationen **stehenbleiben**, sonst erkennt 316→320 die alten
Werte nicht mehr und schreibt sie nicht um.

**Azure verschwindet aus dem laufenden Code, nicht aus der Umzugslogik.**

### `voice_activation.azure.region` hat schon einmal Core lahmgelegt

Am 10.09. hat ein Regex das Feld aus der Vorlage entfernt und Core startete
nicht mehr. Die Migration muss das Feld aus bestehenden Configs entfernen,
**bevor** der Code es nicht mehr erwartet — sonst trifft es jeden Tester beim
Update.

### Nutzer mit eigenen Azure-Keys brauchen ein Ziel

Wer heute Azure OpenAI oder Azure Speech eingetragen hat, landet sonst auf
einem Anbieter, den es nicht mehr gibt. Die Migration schreibt sie auf
`openai` um und schreibt es ins Migrationsprotokoll, so wie es die
Stimmenzuordnung schon tut.

## Reihenfolge

Fünf Etappen, jede für sich lauffähig und einzeln testbar. Nicht in einem
Rutsch: ein halb ausgebautes Core startet nicht.

1. **Client: MSAL raus.** `authService.ts`, `authConfig.ts`,
   `@azure/msal-browser`. Risikoärmste Etappe — der MSAL-Pfad wird im neuen
   Backend ohnehin nie ausgeführt.
2. **Core: Azure als KI-Anbieter raus.** Azure OpenAI in `providers/open_ai.py`,
   `AzureInstanceConfig`, `AzureApiVersion`, TTS- und STT-Konfiguration.
3. **Core: Speech-SDK und Sprachaktivierung raus.** Hier fallen die 14 MB und
   die native Abhängigkeit aus `build.py` und `build_macos.py`.
4. **Migration 316→320 erweitern**, damit alte Configs vollständig
   umgeschrieben werden: Anbieter, Stimmen, `voice_activation.azure`.
5. **Client: API-Modelle neu generieren**, Azure-Oberfläche raus
   (`AzureVoiceSelection`, `AzureInstanceConfig`, `AzureSpeechLanguagesSelection`).

Nach jeder Etappe: Core starten und prüfen, dass Anmeldung, Frage und
Sprachausgabe laufen.

## Was dabei mit erledigt wird

Aus Simons Test vom 11.09., alles Folgen derselben Ursache — die
Anbieterauswahl im Client kennt das neue Backend noch nicht:

* **LLM-Auswahl zeigt nur `default`** und der Picker öffnet nicht.
* **STT-Auswahl zeigt Azure Speech** statt der echten Optionen des Backends.
* **TTS-Auswahl zeigt Azure TTS.**

Diese drei Auswahlfelder werden in Etappe 5 gegen das ersetzt, was
`/api/v1/models` und `/api/v1/voices` tatsächlich liefern.

## Alle fünf Etappen erledigt, 2026-09-11

Gemessen: **null Azure-Treffer** in Core und Client. Die 57 in
`services/migrations/` bleiben, wie geplant — das ist die Umzugslogik.

| | |
|---|---|
| Core | 745 Zeilen weg, 363 dazu, 21 Dateien |
| Client | 1482 Zeilen weg, 354 dazu, 67 Dateien |
| Zusammen | **netto rund 1500 Zeilen weniger** |

Entfernt: `@azure/msal-browser`, `azure-cognitiveservices-speech` (14 MB samt
nativer Bibliothek aus beiden Build-Skripten), `authService.ts`,
`authConfig.ts`, `RegionPrompt.svelte`, `AzureVoiceSelection`,
`AzureInstanceConfig`, `OpenAiAzure` mit vier Adaptern, alle Azure-Enums und
-Configs, 25 Übersetzungstexte je Sprache, das Anbieterlogo.

### Was dabei sonst noch aufgefallen ist

**Zwölf Core-Routen waren nie registriert.** Die Handler existierten, die
Registrierung fehlte — der Client rief also Methoden auf, die sein generierter
Code nicht hatte. Betroffen: die acht „Verbindung testen"-Knöpfe in den
Einstellungen, `enhance-backstory`, die beiden ElevenLabs-Endpunkte und
`/models/wingman-pro`. Letzteres war **die Ursache für die leere Modellauswahl**
— ich hatte die Route am 10.09. versehentlich zusammen mit der Regions-Route
gelöscht. Alle zwölf sind jetzt verdrahtet.

**Der „Azure-Workaround" beim Ton war keiner.** `get_azure_workaround_gain_boost`
gleicht die Lautstärke gestreamter PCM-Audios aus — PocketTTS, Inworld, OpenAI
und das Wingman-Backend nutzen ihn alle. Hätte man ihn mit Azure entfernt, wären
sämtliche Radio-Effekte zu leise geworden. Heißt jetzt `get_streaming_gain_boost`.

**Die Sprachliste lag unter `azure`.** `voice_activation.azure.languages` steuert
die Auto-Erkennung der Cloud-Transkription und hat mit Azure nichts zu tun. Sie
liegt jetzt unter `voice_activation.languages` und `wingman_pro.languages`; die
Migration trägt sie mit. Die Sprachauswahl im Client leitet ihre Optionen nicht
mehr aus Azure-Stimmen ab, sondern nutzt BCP-47-Tags, deren Namen `Intl.DisplayNames`
in der eingestellten Sprache liefert.

**Ein bereits migriertes Config-Verzeichnis heilt sich nicht.** Der
Vorlagen-Abgleich (`backfill_from_template`) läuft nur *während* einer
Migration. Wer schon auf `3_2_0` war, bevor ein Feld dazukam, startet nicht mehr
— genau das ist beim Test passiert. Für echte Tester unkritisch, die kommen von
3.1.6 und durchlaufen den Abgleich. Falls wir später wieder Pflichtfelder
ergänzen: daran denken.

## Erledigt

* **11.09.** Inworld-TTS antwortete mit 502. Ursache: Inworld verlangt eine
  `modelId`, Core schickt keine — es kennt nur die Stimme. Das Backend setzt
  jetzt `inworld-tts-2-flash` als Standard, das Modell, aus dem unser
  Zeichenpreis gerechnet ist. Gültige Alternativen, gemessen: `inworld-tts-1`,
  `inworld-tts-1-max`, `inworld-tts-2`. Nebenbei: ein 400 von Inworld wird
  nicht mehr als „vorübergehend nicht verfügbar" gemeldet — das schickte den
  Leser an die falsche Stelle.

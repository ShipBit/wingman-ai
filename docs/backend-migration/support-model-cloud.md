# Support-Modell: lokales Qwen3.5-2B durch ein Gateway-Modell ersetzen?

Stand: 2026-09-12. Alle Zahlen unten sind gemessen, nicht geschätzt: die
Kandidaten liefen über das Vercel AI Gateway durch dieselben Prompts, dieselben
Sampling-Werte und denselben Scorer wie die lokale Eval-Suite.

Anlass: Tester melden, dass das lokale Support-Modell zu viel Hardware kostet.

## 1. Wo das Support-Modell benutzt wird

Alles läuft über `LocalAiService.support()` (`services/local_ai_service.py`).
Sieben Aufrufstellen:

| Stelle | Aufgabe | Preset | Häufigkeit |
|---|---|---|---|
| `services/conversation_condenser.py:340, 532, 593` | Gespräch zusammenfassen, bei Überlänge stückweise + Merge | BALANCED | bei 70 % der Support-Kapazität, plus Sicherheitskappe über die Nachrichtenzahl |
| `services/persistent_memory.py:306, 351` | Fakten + Session-Summary als JSON extrahieren | PRECISE | beim Beenden des Wingman, beim Zurücksetzen des Verlaufs, und im Condense |
| `services/tool_response_cache.py:237, 276` | Tool-Antworten über 4000 Token eindampfen | PRECISE | pro großer Tool-Antwort, bis zu 30 Chunks |
| `wingman_core.py:2061` | Begrüßung beim Sessionstart | BALANCED / CREATIVE | 1× pro Session |
| `wingman_core.py:2957` | Playground im Client (Lab) | frei | nur manuell |
| `services/skill_local_ai.py:263` | `self.wingman.local_ai.generate()` für Skills | frei | kein mitgeliefertes Skill nutzt es; Dritt-Skills schon |
| `LocalAiService.embed()` → `services/persistent_memory.py` | Embeddings für die Vektor-DB | — | pro gespeichertem Fakt und pro Recall |

Der Embed-Pfad ist ein **eigener** llama-server-Prozess mit eigenem Modell
(`providers/llama_cpp_provider.py`: `_support_process` und `_embed_process`).
Support und Embeddings lassen sich also getrennt umstellen.

## 2. Was das lokal kostet

- `Qwen3.5-2B-Q4_K_M.gguf`, 1,28 GB Datei, dauerhaft geladen
- `nomic-embed-text-v1.5.f16.gguf`, 250 MB, zweiter Prozess, ebenfalls dauerhaft
- `gpu_backend: cpu` ist der Default (`templates/configs/settings.yaml`), das
  heißt: jeder Support-Call belegt CPU-Threads neben dem Spiel
- `n_ctx: 4096` — daher das Chunking in allen drei großen Aufrufstellen

Der Löwenanteil ist das Support-Modell. Der Embed-Server ist ein Sechstel davon.

## 3. Messung

### 3.1 Vorauswahl: 8 kurze Fälle, davon 2 deutsche

`evals/memory_extraction_cases.py` plus zwei selbst geschriebene deutsche Fälle
(Fakten über mehrere Turns, und Smalltalk ohne Fakten).

| Modell | bestanden | Median |
|---|---|---|
| google/gemini-2.5-flash-lite | 8/8 | 521 ms |
| amazon/nova-micro | 8/8 | 538 ms |
| mistral/ministral-3b | 8/8 | 517 ms |
| alibaba/qwen3.7-flash | 8/8 | 1300 ms |
| zai/glm-4.7-flash | 8/8 | 1328 ms |
| openai/gpt-oss-20b | 8/8 | 1278 ms |
| alibaba/qwen3.5-flash | 8/8 | 928 ms |
| zai/glm-5.3-flash | 8/8 | 923 ms |
| mistral/ministral-8b | 8/8 | 1203 ms |
| google/gemma-4-31b-it | 8/8 | 3790 ms |
| deepseek/deepseek-v4-flash-0731 | 8/8 | 2537 ms |
| nvidia/nemotron-3.5-lightning | 7/8 | 451 ms |
| openai/gpt-4.1-nano | 7/8 | 925 ms |
| openai/gpt-5-nano | 5/8 | 1083 ms |
| inception/mercury-2.5 | 5/8 | 1736 ms |

gpt-4.1-nano fällt an genau einer Stelle durch: es speichert im deutschen Fall
"Bei New Babbage geparkt" als dauerhaften Fakt. Der Prompt verbietet Orte
ausdrücklich, auch auf Deutsch.

### 3.2 Hauptmessung: die 7 realistischen Szenarien der Memory-Suite

`evals/memory_suite/scenarios.py`, 2 Durchläufe pro Szenario, Scoring mit
`evals/memory_suite/metrics.py` (0,6 × Recall + 0,3 × Precision + 0,1 × Dedup).
Direkt vergleichbar mit dem lokalen Referenzlauf in
`evals/memory_suite/results/results.json`.

| Modell | Score | Recall | Precision | Median | p90 | $/Extraktion | $/M in/out |
|---|---|---|---|---|---|---|---|
| zai/glm-4.7-flash | **0,982** | 1,000 | 0,988 | 1571 ms | 2020 ms | 0,000107 | 0,07 / 0,40 |
| google/gemini-2.5-flash-lite | 0,980 | 1,000 | 0,980 | **696 ms** | 852 ms | 0,000143 | 0,10 / 0,40 |
| alibaba/qwen3.7-flash | 0,974 | 0,991 | 0,980 | 1876 ms | 2711 ms | **0,000044** | 0,03 / 0,13 |
| mistral/ministral-3b | 0,974 | 1,000 | 0,962 | 895 ms | 1442 ms | 0,000117 | 0,10 / 0,10 |
| openai/gpt-oss-20b | 0,949 | 1,000 | 0,879 | 1706 ms | 2143 ms | 0,000086 | 0,05 / 0,20 |
| amazon/nova-micro | 0,948 | 0,943 | 0,988 | 757 ms | 930 ms | 0,000048 | 0,035 / 0,14 |
| nvidia/nemotron-3.5-lightning | 0,946 | 1,000 | 0,867 | 590 ms | 834 ms | 0,000075 | 0,05 / 0,20 |
| **lokal Qwen3.5-2B (Referenz)** | **0,893** | **0,845** | 1,000 | — | — | 0 | — |
| openai/gpt-4.1-nano | 0,870 | 0,899 | 0,817 | 1376 ms | 2245 ms | 0,000139 | 0,10 / 0,40 |

Zwei Dinge stechen heraus:

- Der Schwachpunkt des 2B ist **Recall**: 0,845. Es vergisst Fakten in langen
  Sessions (`sc_long_session` 0,625, `sc_va_marathon` 0,709). Fünf der sieben
  Kandidaten holen 1,000. Das ist genau die Sorte Fehler, die Nutzer merken:
  "der Wingman hat vergessen, dass ich eine Cutlass habe."
- gpt-4.1-nano liegt **unter** dem lokalen Modell. Es ist eins unserer
  Chat-Modelle — das Argument "wir haben doch schon ein günstiges Modell im
  Plan" trägt hier also nicht.

Beim deutschen Szenario erreichen alle bis auf gpt-4.1-nano (0,906) und
nemotron (0,982) glatt 1,000.

Zwei Durchläufe pro Szenario sind wenig. Ein Kontrolllauf von nova-micro kam auf
0,963 statt 0,948 — rund 0,02 Streuung ist Rauschen, kein Unterschied. Für eine
Entscheidung zwischen zwei Modellen innerhalb dieser Spanne mehr Durchläufe
fahren.

### 3.3 Die beiden teuren Aufgaben, in realistischer Größe

Condense auf dem längsten Szenario, Tool-Komprimierung auf einer
78.667-Token-Handelstabelle in der Form, die uexcorp liefert:

| Modell | Condense | Tool-Antwort (78k Token) |
|---|---|---|
| google/gemini-2.5-flash-lite | 0,00035 $, 2,3 s | 0,0112 $, 5,0 s |
| alibaba/qwen3.7-flash | 0,00011 $, 5,8 s | 0,0032 $, 17,4 s |
| amazon/nova-micro | 0,00010 $, 1,9 s | 0,0036 $, 9,0 s |

Eine solche Tool-Antwort ist heute lokal der schlimmste Fall: 4000er-Kontext,
400-Token-Chunks, Kappe bei 30 Chunks. In der Cloud ist es **ein** Aufruf.

### 3.4 Was ein schwerer Monat kostet

Angenommen 30 Sessions im Monat, pro Session 1 Begrüßung, 3 Condense,
2 Extraktionen und 2 große Tool-Antworten:

- gemini-2.5-flash-lite: rund **0,73 $** im Monat, davon 0,67 $ allein die
  Tool-Antworten
- qwen3.7-flash: rund **0,21 $**

Der Posten, der zählt, sind also die Tool-Antworten, nicht Gedächtnis und
Zusammenfassung. Wer uexcorp nicht nutzt, landet bei ein paar Cent.

## 4. Empfehlung

**Default: `google/gemini-2.5-flash-lite`.** Score 0,980 bei 696 ms Median, das
ist mehr als doppelt so schnell wie glm-4.7-flash bei praktisch gleicher
Qualität. Es ist das einzige Feld im Vergleich mit einer EU-Region, und wir
fahren im Chat schon `google/gemini-2.5-flash` — ein Anbieter weniger.

**Sparvariante: `alibaba/qwen3.7-flash`**, dreimal günstiger bei 0,974. Kostet
Latenz (p90 2,7 s), was bei Hintergrundarbeit egal ist, bei der gesprochenen
Begrüßung aber auffällt.

**Bestwert: `zai/glm-4.7-flash`** mit 0,982. Der Vorsprung vor gemini ist mit
0,002 nicht messbar echt, der Latenznachteil mit 875 ms Median schon.

Bei allen dreien muss `reasoning_effort: "none"` mitgeschickt werden. Ohne das
denkt qwen3.7-flash 106 Token lang über die Hauptstadt von Frankreich nach —
und der Katalog des Gateways meldet für dieses Modell `reasoning_options: null`,
also *nicht* abschaltbar. Die Angabe stimmt nicht; gemessen funktioniert es.
Für den Filter in /admin heißt das: `reasoning_optional` ist nicht verlässlich.

## 5. Was dafür im Code passieren muss

Nicht trivial, aber überschaubar. Die Reihenfolge ist die Reihenfolge des
Risikos.

1. **Der Condense-Trigger hängt am Kontextfenster des Support-Modells.**
   `ConversationCondenser.get_support_capacity()` fragt
   `local_ai_service.get_token_budget()`, und kondensiert bei 70 % davon. Mit
   einem Modell, das 1 Mio. Token kann, löst das nie mehr aus — und der
   Gesprächsverlauf läuft stattdessen dem *Chat*-Modell über. Der Schwellwert
   muss eine eigene Zahl werden, unabhängig vom Support-Modell.
2. **Chunking wird überflüssig, bleibt aber nötig.** Die Merge-Pfade in
   Condenser, Tool-Cache und Memory dürfen nicht weg — sie tragen den lokalen
   Fall weiter. Sie laufen mit großem Kontext nur nicht mehr an.
3. **Embeddings bleiben lokal.** Ein Wechsel des Embed-Modells macht jeden
   gespeicherten Vektor ungültig, weil er in einem anderen Raum liegt. Die
   Vektor-DB bleibt also, und mit ihr der kleine Embed-Server — 250 MB statt
   1,5 GB. Wenn wir das später doch wollen, braucht es einen Reindex-Lauf.
4. **`run_locally: bool` muss ein dritter Modus werden.** Heute ist es ein
   Schalter lokal/remote (`api/interface.py:1242`), im Client eine
   SegmentedControl mit zwei Feldern. Braucht Config-Migration und einen
   Eintrag im Sanitizer, sonst läuft eine alte Config in einen Pydantic-Fehler.
5. **Free-Nutzer haben keinen Cloud-Zugang.** Für sie bleibt lokal der Default,
   inklusive Modell-Download. Der Cloud-Modus ist ein Angebot für Pro und
   Ultra, kein Ersatz.
6. **Offline und Quota brauchen einen Rückfall.** Ohne Netz oder über dem Limit
   darf die Faktenextraktion nicht die Session mitreißen — entweder still
   überspringen oder auf lokal zurückfallen, falls die Modelle da sind.
7. **Datenschutz.** Der Cloud-Modus schickt Gesprächsinhalte an uns. Wer ein
   lokales Chat-Modell fährt, tut das heute bewusst; für den darf das nicht
   still angeschaltet werden. Also opt-in.
8. **Backend: fester Rollen-Alias statt frei wählbarem Modell.** Ein
   `model_routes`-Eintrag mit `alias = 'support'` pro Plan, analog zu `stt` und
   `tts` in `src/lib/server/quota.ts`. Sonst kann ein Nutzer seine
   Hintergrundarbeit auf einem teuren Modell laufen lassen. Die Abrechnung
   selbst läuft schon: `/api/v1/chat/completions` misst mit.
9. **Skill-Doku.** `skills/MIGRATING-TO-V3.md` nennt `local_ai.summarize()`
   ausdrücklich "free". Stimmt im Cloud-Modus nicht mehr.

## 6. Reproduzieren

`evals/gateway_support_models.py` — braucht `AI_GATEWAY_API_KEY` in der
Umgebung. Ohne Argumente läuft die Vorauswahl, mit `--suite` die sieben
Szenarien, mit `--cost` die beiden großen Aufgaben.

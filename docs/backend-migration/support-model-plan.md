# Support-Modell in die Cloud — Umsetzungsplan

Entscheidungen vom 2026-09-12 (Simon):

- Drei Tabs im Client: **Cloud** (Default) / **Lokal** / **Eigener Server**. Der
  bestehende Remote-llama.cpp-Modus bleibt.
- **Free bekommt eine eigene Support-Lane** und ein kleines Token-Limit. Free
  soll Wingman mit dem echten Modell ausprobieren können.
- **Alle** bestehenden Nutzer werden auf Cloud umgestellt, auch Free.
- Beim Start wird **nichts mehr automatisch heruntergeladen**. Der Download
  passiert erst, wenn jemand auf Lokal schaltet.
- Kondensier-Schwelle wird `min(fester Wert, Kapazität des Modells)`, im
  Cloud-Modus großzügiger.
- Im Dashboard je Plan eine Support-Lane zum Reinziehen.

Nicht Teil dieser Änderung: Free auch **Chat** geben und dafür den Trial im
Pro-Tarif streichen. Das ist eine eigene Änderung am Abo-Trichter.

## Backend (wingman-backend)

1. Migration A: `alter type usage_modality add value 'support'` — muss allein in
   einer Datei stehen, ein neuer Enum-Wert ist in derselben Transaktion noch
   nicht benutzbar.
2. Migration B: `plan_models.role` (`chat` | `support`, Default `chat`),
   Default-Index auf `(plan, role)`, `set_plan_models()` bekommt `p_role`,
   Support-Lanes für free/pro/ultra, Token-Limit für free.
3. `quota.ts`: `Modality` um `support`, `planModels(plan, role)`, Support-Zweig
   in `decide()` — Lane wie bei Chat, aber ohne Downgrade.
4. `POST /api/v1/support/completions` — neu, kein Streaming, `reasoning_effort:
   none`, Verbrauch als `support`.
5. `GET /api/v1/models` liefert zusätzlich `support: { default, models }`.
6. `/api/admin/plan-models` mit `role`; Admin-Seite bekommt Support-Lanes.

## Core (wingman-ai)

7. `api/enums.py`: `LocalAiMode` (`cloud` | `local` | `server`).
8. `api/interface.py`: `LlamaCppSettings.mode` ersetzt `run_locally`,
   `support_cloud_model: str` dazu. Embeddings folgen dem Modus: bei `server`
   remote, sonst lokal.
9. `providers/wingman_support.py`: Support-Aufrufe über das Abo-Backend.
10. `local_ai_service.py`: Routing nach Modus, Token-Budget für Cloud.
11. `conversation_condenser.py`: `min(CONDENSE_MAX_TOKENS[modus], Kapazität)`.
12. `wingman_core.py`: Auto-Download beim Start raus, Cloud-Provider verdrahten,
    Endpunkt für die Support-Modell-Liste.
13. Migration 3.1.6 → 3.2.0 setzt `mode: cloud`, Sanitizer deckt den Enum ab.
14. `templates/configs/settings.yaml`, `skills/MIGRATING-TO-V3.md` ("free").

## Client (wingman-client)

15. `LlamaCppSettings.svelte`: drei Tabs, Modellauswahl im Cloud-Modus,
    Download-Knopf nur im Lokal-Modus.
16. Generiertes API-Modell neu ziehen, Texte in allen vier Sprachen.

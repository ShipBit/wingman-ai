text
I have everything I can get from live pages (the session's WebSearch budget is now exhausted; all remaining facts below come from direct WebFetch of the vendors' own pages). Final report follows.

# AI Gateway Research: Requesty vs. Eden AI (all facts fetched live 2026-09-09)

## 1. Requesty (requesty.ai)

### Pricing
- **Free tier:** "The full platform, on free models", "200 requests per day", no credit card. Includes routing, caching/fallbacks, spend tracking, EU data residency.
- **Pay-as-you-go:** "5% markup" — "A model that costs $10 per 1M tokens from OpenAI costs $10.50 through Requesty." "No per-seat pricing, no minimum spend. You pay for what your application spends, plus 5%." Includes spend limits/budget caps, EU residency, email support.
- **BYOK:** Enterprise page: "The gateway costs 5% on model cost, or 0% with your own provider keys." (BYOK docs page itself is silent on fees.)
- **Enterprise:** "Custom"; SSO (Okta/Azure AD/Google Workspace), full RBAC + audit logs, service accounts, custom SLAs. "99.99% uptime" claim.
- **Free starting credits:** Quickstart says "New accounts include free credits to start routing immediately" — dollar amount not stated on any Requesty page I fetched. A "$10" figure appeared only in a search snippet: **UNVERIFIED**.
- **Credits:** prepaid credits with auto top-up (from search summary of requesty.ai pages); minimum top-up / expiry: not documented on pages fetched — **UNVERIFIED**.
- **Log retention:** Security + privacy pages: "When logging is enabled, data is stored encrypted within the EU for up to 30 days." Zero Data Retention is available "per key, or org-wide on written request"; once ZDR is enabled, disabling requires contacting support. Usage metadata (model, tokens, cost, latency) is always kept.

### Per-end-user budgets / limits
- **No budgets keyed on end-user metadata.** Spend Limits doc: limits exist per API key / service account, monthly only ("Each API key or service account can have its own monthly spend cap"). No daily limits, no user_id-scoped limits, no "downgrade after X usage" feature.
- Enforcement is hard: Cost Tracking doc: "new requests for that key are blocked until the next billing period."
- "Users" and "Groups" in Requesty are **organization members** (your staff), not app end users. Per-member monthly limits and group budgets ("Group Budget mode" requires emailing support@requesty.ai) exist, but they don't map to your subscribers.
- **Workaround:** one API key per end user via Management API: `POST /v1/manage/apikey` with `name`, `monthly_limit` (decimal), `permissions`; `POST /v1/manage/apikey/{id}/limit` with `monthly_limit`. Only a monthly cap; no daily. Cap on number of keys per org: not documented.
- Rate limiting: "Requesty does not limit how many requests you send per minute, it limits how many can be in flight at the same time."
- Spending alerts: thresholds per org/user/group/API key, webhook (JSON/Slack/Teams), notification only, "no automatic enforcement actions."

### Fallback / alias / remapping
- **Fallback Policies:** created in dashboard (Routing Policies → Create Policy → Fallback), ordered chain, drag to reorder; referenced in requests as `model: "policy/your-policy-name"`. Triggers: "timeout, rate limit, error, etc."; 0–10 retries with exponential backoff + jitter. "You only pay for successful requests."
- **Load Balancing Policies:** same `policy/<name>` mechanism, weighted; "Changing weights will re-distribute traffic" without client changes.
- This `policy/<name>` indirection is effectively your **central model alias**: you can edit the chain in the UI and clients keep sending the same name. Management API overview mentions `/manage-policy/` for programmatic policy management (individual endpoint docs not listed in llms.txt — **partially verified**).
- No standalone "custom alias name → model" feature documented. "Dedicated Models" are Requesty-provided prefixes (e.g. `coding/`), not user-defined.
- Approved Models / Access Lists: org allowlist, overridable per group or per API key ("If the API key has an access list, use it…"). No remapping.

### Usage reporting & export
- Request metadata via `extra_body: {"requesty": {"user_id": "...", "trace_id": "...", "tags": [...], "extra": {...}}}` — "Per-user cost attribution (external user IDs set in request metadata)". Also `X-Requesty-<Name>` headers (e.g. `X-Requesty-Customer`).
- Dashboard: filter/group by Model, Provider, User, Member, API Key, custom metadata; "Export to CSV or PDF".
- API: `GET /v1/manage/org/usage` (and per-key `/apikey/{id}/usage`) with `start`, `end`, `resolution` (hour/day/month), `group_by` incl. `user_id`, `api_key_id`, `model_used`, `extra.<field>`. Response: spend, tokens, and request counts split by completions/embedding/image/speech/transcription. **Gotcha:** "The date range cannot exceed 100 days."
- Every chat response `usage` includes a `cost` field (USD).

### Audio & image
- **TTS:** `POST /v1/audio/speech` — OpenAI models only (`openai/gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`), 11 voices, max 4096 chars, SSE streaming only on gpt-4o-mini-tts.
- **STT:** `POST /v1/audio/transcriptions` — `openai/gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `whisper-1` (and `mistral/voxtral-mini-latest` referenced for verbose_json); 32 MB max upload; formats flac/mp3/mp4/mpeg/mpga/m4a/ogg/wav/webm.
- **Image gen:** `/v1/images/generations`, `/v1/images/edits` (OpenAI format) — `azure/openai/gpt-image-1`, `gpt-image-1.5`, Vertex Gemini image models.
- **Streaming + tools:** SSE for all major providers; "Streaming function calls and arguments" supported; `stream_options: {"include_usage": true}` needed for cost in stream. `/v1/models` exposes `supports_tool_calling`, `supports_vision`, pricing tiers.

### Hosting & EU
- Managed only. Enterprise FAQ: "Self-hosting is not offered at this time." (An AWS Marketplace listing claims "Deployable in VPC, on-prem, or air-gapped" — contradicts the vendor's own page; **UNVERIFIED**.)
- EU endpoint `https://router.eu.requesty.ai/v1`, Frankfurt AWS eu-central-1; "All processing and storage by Requesty stays in the EU." Warning: EU endpoint covers Requesty's layer only; model inference stays EU only if you pick EU models (`bedrock/...@eu-central-1`, `vertex/...@eu`, Azure francecentral/swedencentral, Mistral). Org setting can restrict serving regions to EU/US/APAC (global domain then rejected).
- GDPR: "DPA signed on request, any spend." SOC 2 Type II: "Programme in progress."

### Gotchas
- No per-end-user budget without one-key-per-user; no daily caps; no auto-downgrade.
- TTS is OpenAI-only; STT nearly so.
- 100-day window on usage API; 30-day log retention.
- Group Budget mode needs support ticket.

### Sources (all fetched 2026-09-09)
https://www.requesty.ai/pricing · https://www.requesty.ai/enterprise · https://www.requesty.ai/security · https://www.requesty.ai/privacy · https://docs.requesty.ai/llms.txt · https://docs.requesty.ai/quickstart.md · https://docs.requesty.ai/features/api-limits.md · https://docs.requesty.ai/features/fallback-policies · https://docs.requesty.ai/features/load-balancing-policies.md · https://docs.requesty.ai/features/request-metadata · https://docs.requesty.ai/features/analytics-headers.md · https://docs.requesty.ai/features/cost-tracking.md · https://docs.requesty.ai/features/usage-analytics · https://docs.requesty.ai/features/performance-monitoring.md · https://docs.requesty.ai/features/users.md · https://docs.requesty.ai/features/groups.md · https://docs.requesty.ai/features/alerts.md · https://docs.requesty.ai/features/approved-models.md · https://docs.requesty.ai/features/dedicated-models.md · https://docs.requesty.ai/features/service-accounts.md · https://docs.requesty.ai/features/mcp-user-keys.md · https://docs.requesty.ai/features/bring-your-own-keys · https://docs.requesty.ai/features/streaming · https://docs.requesty.ai/features/eu-routing · https://docs.requesty.ai/features/compliance-report.md · https://docs.requesty.ai/features/image-generation.md · https://docs.requesty.ai/api-reference/endpoint/audio-speech-create.md · https://docs.requesty.ai/api-reference/endpoint/audio-transcriptions-create.md · https://docs.requesty.ai/api-reference/endpoint/models-list.md · https://docs.requesty.ai/api-reference/management-apis · https://docs.requesty.ai/api-reference/endpoint/manage-apikey/manage-api-key-create.md · https://docs.requesty.ai/api-reference/endpoint/manage-apikey/manage-api-key-update-limit.md · https://docs.requesty.ai/api-reference/endpoint/manage-apikey/manage-api-key-get-usage.md · https://docs.requesty.ai/api-reference/endpoint/manage-org-get-usage.md · https://www.requesty.ai/blog/best-llm-routing-platforms-compared-2026-requesty-portkey-litellm-openrouter · https://www.requesty.ai/pricing-compare

---

## 2. Eden AI (edenai.co)

### Pricing
- **Self-serve "AI API Gateway":** "You pay exactly what the underlying provider charges, plus a 5.5% platform fee" (applied at checkout). "We do not mark up provider pricing." No subscription, no API-call limits, multiple API keys, unlimited seats, chat support (48h working days).
- **Advanced AI Platform:** "Custom price"; higher rate limits, bulk discounts, "Private deployments and compliance options", SLA, custom billing, professional services.
- **Free credits:** Not stated on pricing page, plans-prices doc, buying-credits doc, or quickstart. Only a free **sandbox token** ("mock responses", no real provider calls). A "$30 free credits" figure exists only on an affiliate site: **UNVERIFIED**.
- **Rate limits (conflicting pages):** plans-prices doc: "7 requests/second, upgradable to 15 req/sec upon request"; rate-limits doc: "10 requests per second" per account, "shared across your API keys", and "the owner's rate limit is the ceiling for all members."
- **Credits:** prepaid via Stripe (cards, Apple/Google Pay, PayPal, bank transfer); auto-refill with threshold + refill amount; postpaid invoicing (30-day terms) for larger teams. Minimum top-up / expiry: not documented.
- **Retention:** default "Logs metadata for billing and analytics (timestamps, token counts, costs)"; "Does not store your request/response content" unless you enable "Log Retention" in the dashboard; async job results kept 7 days. Duration of opt-in content logs: not stated.

### Per-end-user budgets / limits — strongest point
- **Per-API-key hard budgets with periodic reset:** fields `balance` (decimal), `active_balance` (bool), `balance_reset_period` (`daily` | `weekly` | `monthly` | `none`), `balance_reset_amount`, `expire_time`. "Once it reaches $0, the token stops working." "Resets run at midnight Europe/Paris time: daily every night, weekly on Monday, monthly on the 1st."
- Create via dashboard (Settings → API Keys) or Management API: `POST https://api.edenai.run/v3/manage/keys` with a `mgmt-eden-…` key (`manage:write`); also GET/PATCH/DELETE, rotate, and `GET /manage/keys/{id}/usage`. Keys can be tagged to a `member` email.
- So: one key per subscriber = daily or monthly hard cap per end user, managed centrally. **Gotchas:** (a) creation returns 403 "Plan's key limit reached" — the actual cap number is not documented anywhere I fetched: **UNVERIFIED**; (b) account-wide rate limit is shared across all keys, so thousands of end-user keys still share ~7–10 rps unless raised; (c) budgets exclude BYOK and sandbox traffic.
- **Guardrails** (model allow/deny lists, rate limits "N/period", per-member soft budget caps daily/weekly/monthly, attachable to token/member/role): "Limited to advanced organization plans."
- No "downgrade to cheaper model after X" feature documented.

### Fallback / alias / remapping
- **Fallback:** per-request `fallbacks` array, max 3 entries, triggered on "provider outage, rate limit, error". **No central/dashboard fallback config** documented — must be sent by the client. Not supported on `/v3/images/*` ("does not support streaming, fallbacks").
- **Provider routing:** `routing.sort` = `cost` (default) | `speed` | `latency` | `exact`; `routing.allowed_providers`; model suffix form `model: "gpt-5.6-sol:latency"`. Routes between providers of the **same** model only.
- **Aliases:** provider-maintained stable aliases (`anthropic/claude-sonnet-latest`, `google/gemini-flash-latest`) with `alias_of` in `/v3/models`. **No user-defined custom aliases** documented, so no central remap without code changes.

### Usage reporting & export
- `GET /cost_management/` (`begin`, `end`, `step` 1–4 = day/week/month/year, `group_by=user`, filters `provider`, `subfeature`, `token`, `user` (member email)); `GET /manage/keys/{id}/usage/` (default last 7 days; `total_cost`, `details`, `cost_per_provider` per period). Per-end-user = per key.
- Chat API accepts `user` ("User identifier for tracking or personalization") and `metadata` fields, but no doc shows them as monitoring filters: **UNVERIFIED as attribution**.
- **No CSV/JSON export documented** (dashboard or API); build from the JSON endpoints.
- `x-edenai-metadata: enabled` header returns routing attempts/provider used.
- **Cost in response (conflict):** overview says "Every response includes a `cost` field"; chat-completions API schema lists only `usage` tokens; audio/images docs do return `cost` + `provider` (headers for TTS).

### OpenAI compatibility, streaming, tools
- Base `https://api.edenai.run/v3`; `/v3/chat/completions` OpenAI-format (plus `/v3/responses`, embeddings, Anthropic messages). `tools`, `tool_choice`, `parallel_tool_calls`, `stream`, `stream_options`, `response_format` present. Streaming is SSE with `[DONE]`; tool calls during streaming: only `finish_reason: tool_calls` mentioned, no explicit streamed-tool docs — **partially verified**. `/v3/models` has `supports_function_calling`, `supports_native_streaming`.

### Audio & image (verified multi-provider)
- **TTS:** `POST /v3/audio/speech` "OpenAI-compatible" (model/input/voice/response_format/speed/instructions/routing); no streaming mentioned. Provider list via universal-ai TTS: Amazon, Deepgram, ElevenLabs, Google, LovoAI, Microsoft, OpenAI.
- **STT:** `POST /v3/audio/transcriptions` "OpenAI-compatible" (multipart `file` or `file_id`/`file_url`; json/text/srt/vtt/verbose_json). Universal-ai STT is **async** (poll job): Amazon, AssemblyAI, Deepgram, Gladia, Google, Microsoft, OpenAI. File size limits not stated.
- **Images:** `/v3/images/generations`, `/v3/images/edits` OpenAI drop-in — Google (Gemini image, Imagen 4), OpenAI gpt-image-1 / -mini, Stability sd3.5-large, Amazon Nova Canvas.

### Hosting & EU
- Managed only; no self-host product ("open-connector" is a third-party tool that calls Eden's hosted API). "Private deployments" only via Advanced plan.
- French company (Lyon). "Secure European data centers" (provider not named). **EU endpoint** `https://api.eu.edenai.run/v3/`: "only routes requests through EU-eligible providers and models"; non-EU providers get HTTP 451 "before any provider is contacted" and "never spends credits"; Google Gemini explicitly blocked; caching region-scoped. /eu page: "Zero Data Retention", SOC 2 + ISO 27001, DPA available.

### Gotchas
- Fallbacks are client-side only; no central chain, no custom aliases.
- Shared account rate limit across all keys; key-count cap unknown.
- Guardrails/team features need Advanced (custom-priced) plan.
- No free credits documented; no CSV export.

### Sources (all fetched 2026-09-09)
https://www.edenai.co/pricing · https://www.edenai.co/docs/v3/overview/plans-prices · https://www.edenai.co/docs/v3/overview/rate-limits.md · https://www.edenai.co/docs/llms.txt · https://www.edenai.co/docs · https://www.edenai.co/docs/v3/overview/ai-gateway · https://www.edenai.co/docs/v3/quickstart/first-llm-call.md · https://www.edenai.co/docs/v3/llms/chat-completions · https://www.edenai.co/docs/api-reference/chat/chat-completions.md · https://www.edenai.co/docs/v3/llms/streaming.md · https://www.edenai.co/docs/v3/llms/listing-models.md · https://www.edenai.co/docs/v3/llms/provider-routing.md · https://www.edenai.co/docs/v3/general/fallback.md · https://www.edenai.co/docs/v3/llms/request-metadata.md · https://www.edenai.co/docs/v3/general/custom-api-keys.md · https://www.edenai.co/docs/api-reference/api-keys/create-an-api-key.md · https://www.edenai.co/docs/v3/organization/management-api.md · https://www.edenai.co/docs/v3/organization/guardrails.md · https://www.edenai.co/docs/v3/organization/users-organisation.md · https://www.edenai.co/docs/v3/general/monitoring.md · https://www.edenai.co/docs/api-reference/cost-monitoring/monitor-consumptions.md · https://www.edenai.co/docs/api-reference/usage/get-an-api-keys-usage.md · https://www.edenai.co/docs/api-reference/audio/audio-speech.md · https://www.edenai.co/docs/api-reference/audio/audio-transcriptions.md · https://www.edenai.co/docs/v3/expert-models/features/audio/tts.md · https://www.edenai.co/docs/v3/expert-models/features/audio/speech-to-text-async.md · https://www.edenai.co/docs/v3/llms/image-generation.md · https://www.edenai.co/docs/v3/general/byok.md · https://www.edenai.co/docs/v3/general/sandbox.md · https://www.edenai.co/docs/v3/general/buying-credits.md · https://www.edenai.co/docs/v3/data-governance/servers-location.md · https://www.edenai.co/docs/v3/data-governance/eu-endpoint.md · https://www.edenai.co/docs/v3/data-governance/data-retention.md · https://www.edenai.co/docs/v3/integrations/open-connector.md · https://www.edenai.co/eu

---

## Bottom line for your use case (end-user subscriptions, voice assistant)
- **Per-end-user hard budgets:** Eden AI wins (per-key `balance` + `daily`/`monthly` reset, API-managed). Requesty only offers monthly per-key caps and no daily limits.
- **Central fallback/remap without code changes:** Requesty wins (`policy/<name>` chains editable in UI). Eden AI has no central fallback or custom aliases.
- **Auto-downgrade after X usage:** neither product documents this.
- **Multi-provider STT/TTS behind one OpenAI-compatible endpoint:** Eden AI (ElevenLabs, Deepgram, Google, Azure, etc.); Requesty is OpenAI-only for audio.
- **EU:** both offer EU endpoints; Eden AI is an EU company with metadata-only default retention; Requesty stores content 30 days by default (ZDR available).
- **Fees:** Requesty 5% (0% BYOK); Eden AI 5.5%.
- Unresolved: Requesty free-credit amount, Eden AI free credits and key-count cap, Eden streamed tool calls.
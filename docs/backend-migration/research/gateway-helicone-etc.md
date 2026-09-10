text
I have what I need; nothing further depends on another fetch. Here is the report. Everything below comes from pages fetched live today (2026-09-09); my WebSearch budget ran out partway, so all facts are from WebFetch of the URLs listed, not from search snippets or memory.

# 1. Helicone AI Gateway (helicone.ai)

## Pricing (exact)
Source: https://www.helicone.ai/pricing (fetched 2026-09-09)

| Plan | Price | Included | Retention | Ingest limit | Other |
|---|---|---|---|---|---|
| Hobby | Free | "10,000 free requests/month", 1 GB storage, 1 seat, 1 org | "7 days" | "10 logs/min" | |
| Pro | $79/month | "10K free" requests then "Usage-based pricing applies"; 1 GB free storage + usage-based | "1 month" | "1,000 logs/min" | Unlimited seats, alerts/reports, HQL, 60 API calls/min |
| Team | $799/month | "10K free" requests then usage-based | "3 months" | "15,000 logs/min" | 5 orgs, SOC-2 & HIPAA, 1,000 API calls/min |
| Enterprise | Contact | custom | "Forever" / "Configurable retention" | "30,000 logs/min" | SAML SSO, on-prem, custom MSA |

- Usage-based overage rates (per request / per GB): NOT printed on the page (JS calculator only). UNVERIFIED. A third-party estimator (buildmvpfast) returned 403. A TrueFoundry blog (2026-06-26) claims Team includes 10M requests; the official page says "10K free" — treat the 10M figure as UNVERIFIED/contradicted.
- Discounts: startups (<2 yrs, <$5M) 50% off first year; students free; OSS $100 credit.

Gateway fees:
- Docs overview: "Use credits with 0% markup" / "With credits, we manage provider API keys for you." — https://docs.helicone.ai/gateway/overview (fetched 2026-09-09)
- Blog "Complete Guide to the Helicone AI Gateway" (2025-10-29): "Zero markup pricing means you pay exactly what providers charge + Stripe payment processing fee" — https://www.helicone.ai/blog/how-to-gateway
- Credits page: "0% markup", "Only standard payment processing fees apply", "No expiration dates, no provider lock-in" — but the page is still headed "Join the Waitlist" / "Be the first to know when Credits launches" — https://www.helicone.ai/credits
- Exact Stripe fee percentage, minimum top-up, auto top-up: NOT documented anywhere fetched. UNVERIFIED.
- Gotcha: the /credits page says waitlist, while the error-handling doc describes pass-through billing (PTB) as live ("Pay-as-you-go with Helicone credits"). Contradictory; confirm with Helicone before relying on PTB.

## Per-end-user budgets / rate limits
- Yes, header-based. `Helicone-RateLimit-Policy: "[quota];w=[time_window];u=[unit];s=[segment]"`. `u=cents` limits spend; `s=user` segments per `Helicone-User-Id`; `s=<property>` segments per `Helicone-Property-*`. Minimum window 60 s. Example in docs: `"500;w=3600;u=cents;s=user"` = $5/hour per user. Exceeded → 429; response headers `Helicone-RateLimit-Limit/-Remaining`. Docs show it used against `https://ai-gateway.helicone.ai`. — https://docs.helicone.ai/features/advanced-usage/custom-rate-limits, https://docs.helicone.ai/helicone-headers/header-directory (fetched 2026-09-09)
- Daily/monthly: window is arbitrary seconds, so w=86400 / w=2592000 is possible; no documented maximum window. UNVERIFIED whether long windows are supported.
- "Downgrade to cheaper model after X usage": NOT supported natively. Hard 429 only; your app would have to catch 429 and re-request a cheaper model.
- Configuration in a dashboard UI, and plan availability of rate limits: not stated in docs. UNVERIFIED (pricing page lists "Rate limits" as a Gateway feature on all plans, without detail).
- Gotcha: the policy is sent by the caller in a header. In a desktop app the client controls its own limit unless you proxy through your own backend.

## Fallbacks / aliases / remapping
- Fallbacks: automatic by model registry. Routing "Routes to the cheapest provider first. Equal-cost providers are load balanced." BYOK keys tried first, then Helicone managed keys. Failover on 429/401/400(context)/408/5xx. Model-string syntax: `gpt-4o-mini` (auto), `gpt-4o-mini/openai` (locked, no failover), `gpt-4o-mini/azure,gpt-4o-mini/openai,gpt-4o-mini` (explicit chain), `!openai,gpt-4o-mini` (exclude). — https://docs.helicone.ai/gateway/provider-routing (fetched 2026-09-09)
- PTB→BYOK fallback: "The gateway attempts PTB first, then automatically falls back to BYOK"; no BYOK + no credits → 429 "insufficient credits". — https://docs.helicone.ai/gateway/concepts/error-handling
- Central model aliasing / remapping without code change: NOT found. Only `Helicone-Model-Override` exists, and it is for cost calculation/mapping, not routing. Fallback chains live in the model string in your code. Provider keys are managed in the UI (us.helicone.ai/providers); no alias UI documented. Treat "admin-UI remapping" as not available (UNVERIFIED beyond absence in docs).

## Usage reporting & export
- `Helicone-User-Id` "Enables per-user cost analytics and usage metrics"; custom properties `Helicone-Property-*`. User REST endpoints exist: `/v1/user/metrics/query`, `/v1/user/metrics-overview/query`, `/v1/user/query`. — https://docs.helicone.ai/features/advanced-usage/custom-properties, https://docs.helicone.ai/llms.txt
- Export: `npx @helicone/export` → JSONL (default) or `--format csv`, `--start-date`, `--property k=v`, `--include-body`, `--region eu`; REST `POST /v1/request/query-clickhouse` with `request_response_rmt` filter wrapper (user id, session, properties, cost USD, tokens). — https://docs.helicone.ai/guides/cookbooks/etl
- Export is bounded by plan retention (7 d / 1 mo / 3 mo).

## Audio (STT/TTS) and image
- Live model list `GET https://ai-gateway.helicone.ai/v1/models` (fetched 2026-09-09): 113 models; owned_by = anthropic, openai, google, xai, meta-llama, moonshotai, alibaba, qwen, deepseek, mistral, zai, baidu, perplexity. Grok: grok-4, grok-4-fast-*, grok-4-1-fast-*, grok-3, grok-3-mini, grok-code-fast-1. Mistral: mistral-nemo, mistral-small, mistral-large-2411. Llama: llama-4-scout/maverick, llama-3.3-70b, llama-3.1-8b variants. Image: `gpt-image-1`, `gpt-image-1.5`. Audio (whisper/tts/transcribe): NONE. Embeddings: NONE.
- Image-gen docs: "Image generation is currently supported for Nano Banana Pro" (`gemini-3-pro-image-preview/google-ai-studio`) via the chat completions endpoint, "Support for additional providers will be added" — https://docs.helicone.ai/gateway/concepts/image-generation. (gpt-image-1 in the live list but not in docs — inconsistency.)
- Endpoints: `/v1/chat/completions` (stream, tools, tool_choice, parallel_tool_calls, response_format json_schema) and `/v1/responses` ("reasoning, tool use, and streaming", OpenAI + Anthropic). No `/v1/audio/*` on the AI Gateway in llms.txt. — https://docs.helicone.ai/rest/ai-gateway/post-v1-chat-completions, https://docs.helicone.ai/gateway/concepts/responses-api
- Conclusion: STT/TTS through the unified AI Gateway = not available. (The older proxy `gateway.helicone.ai` with `Helicone-Target-Url` can pass through any provider endpoint incl. OpenAI audio, but that is a per-provider proxy, not the unified/credits gateway — https://docs.helicone.ai/getting-started/integration-method/gateway.)

## Hosting & EU
- Cloud: `https://ai-gateway.helicone.ai` (unified gateway + credits/model registry). Observability platform is self-hostable (Docker Compose, Helm, manual, AWS). — https://docs.helicone.ai/getting-started/self-host/overview
- Separate OSS Rust gateway repo Helicone/ai-gateway (Apache-2.0, 628 stars, 494 commits, YAML routers, rate limiting "per user, team, or globally; by request count, tokens, or dollars", not marked deprecated) — https://github.com/Helicone/ai-gateway. It is a different codebase from the cloud gateway; credits/model registry are cloud-only (self-host availability of the cloud gateway UNVERIFIED).
- EU: "Choose between EU and US regions" (https://docs.helicone.ai/references/data-autonomy); "Ensure GDPR compliance by selecting between US and EU data regions" (https://docs.helicone.ai/faq/compliance); EU keys "are generated with the prefix `eu-`" (https://docs.helicone.ai/helicone-headers/helicone-auth); export CLI has `--region eu`. BUT `eu.ai-gateway.helicone.ai` does not resolve (DNS ENOTFOUND, 2026-09-09). Whether the unified AI Gateway / PTB is available in the EU region is UNVERIFIED — assume US-only for the gateway until confirmed.

## Gotchas
- Credits status contradictory (waitlist page vs. live docs). Stripe fee % undocumented.
- No STT/TTS on the unified gateway; image gen limited.
- No admin-side model aliasing; routing is in the model string.
- Per-user limits are hard 429s, client-supplied via header.
- Retention short on Hobby/Pro (7 d / 1 month) — per-user monthly reporting needs Team or your own export job.
- Could not fetch: docs.helicone.ai/ai-gateway (404), /gateway/credits (404), /references/data-residency (404), /features/advanced-usage/fallbacks (404), helicone.ai/models (JS-rendered, empty), /v1/models/multimodal (405).

# 2. Bifrost by Maxim AI (getbifrost.ai / maximhq/bifrost)

## Open source & pricing
- License: Apache 2.0; 7.9k stars; "1000+ models", "23+ providers" in README. — https://github.com/maximhq/bifrost (fetched 2026-09-09)
- Latest release: "Bifrost HTTP v2.1.1 — Sep 09" (year not shown on page; plugins v1.x same day). — https://github.com/maximhq/bifrost/releases
- getbifrost.ai 307-redirects to getmaxim.ai. Pricing page (https://getbifrost.ai/pricing = https://www.getmaxim.ai/pricing, fetched 2026-09-09): 
  - OSS: "Free Forever", "SELF-HOSTED: DOCKER | K8S | GO BINARY". Includes "Budget Management & Rate Limits with Virtual Keys", "Custom Routing Rules & Flows", "Automatic Fallbacks", "Simple and Semantic Caching", "MCP Gateway with Code Mode", "Prompt Repository (Playground)", "Custom Plugins", "Built-in Observability", "OTel Compatible Metrics & Traces".
  - Enterprise: "Custom Pricing", "ENTERPRISE READY: VPC | ON-PREM | AIR-GAPPED", "Try Bifrost Enterprise free for 14 days". Adds "Guardrails", "Cluster Mode", "Adaptive Load Balancing", "Enterprise SSO via SAML and OIDC", "Vault Support", "MCP with Federated Auth", "Log Exports", "Audit Logs", "Role-Based Access Control", "SLA-Backed Enterprise Support".
  - Badges: "GDPR", "ISO 27001", "HIPAA", "AICPA SOC". No numbers, no retention/seat limits, no EU statement.
- Enterprise license model (per instance/seat/usage) not disclosed anywhere — https://docs.getbifrost.ai/enterprise/overview, https://www.getmaxim.ai/bifrost/enterprise. UNVERIFIED.
- Maxim platform per-seat pricing ($29/$49) only found in third-party pages; getmaxim.ai/pricing shows Bifrost pricing only. UNVERIFIED.
- No per-request or percentage fees: you pay providers directly with your own keys (no pass-through billing product exists).

## Per-end-user budgets / rate limits
- Governance entity = Virtual Key (`sk-bf-*`), sent as `x-bf-vk` / `Authorization` / `x-api-key` / `x-goog-api-key` / `api-key`. Per VK: budget (`max_limit` USD, `reset_duration` 1m/1h/1d/1w/1M/1Q/1Y, `calendar_aligned` = "at calendar boundaries in UTC"), rate limits (`token_max_limit`, `request_max_limit` + own reset), provider/model allowlists (deny-by-default), expiry, team OR customer attachment. Exceeded: 402 `budget_exceeded`; 429 `token_limited` / `request_limited`. Budget overrides: "effective limit = Base budget + Override amount". Hierarchy "Customers → Teams → Virtual Keys → Provider Config", "any single budget failure blocks the request". Multiple budgets per limit (daily + monthly both enforced). — https://docs.getbifrost.ai/features/governance, /features/governance/virtual-keys, /features/governance/budget-and-limits, /features/governance/model-limits, /deployment-guides/config-json/governance (all fetched 2026-09-09)
- Configurable via Web UI, REST (`POST /api/governance/virtual-keys`, `/api/governance/model-configs`, `.../budgets/{id}/override`) or config.json.
- Per END USER: OSS pattern = create one VK per end user via API (no documented VK count limit). There is no per-request "user id" header for budgets in OSS. Enterprise-only additions: `x-bf-customer-id` / `x-bf-customer-name` headers ("only the named customer is charged, rate-limited, and recorded"), model-limit scope `user`/`access_profile`, and Access Profiles that auto-issue a per-user VK — but these target SSO/SCIM-provisioned users, not arbitrary external IDs. — /features/governance/budget-and-limits, /enterprise/access-profiles
- "Downgrade to cheaper model after X usage": YES, documented. Routing Rules (CEL) expose `budget_used`, `tokens_used`, `request` as 0–100 percentages plus `virtual_key_id/name`, `team_*`, `customer_*`, `headers[...]`, `model`, `request_type`, `complexity_tier`. Doc example: "Route to cheaper provider when budget is exhausted" with `budget_used > 90` → `groq/llama-2-70b`; scopes VirtualKey > Team > Customer > Global, first-match-wins, `chain_rule`. Configurable in "Web UI: Visual rule builder with CEL expression editor", `/api/routing/rules`, config.json. No enterprise/OSS distinction stated. — https://docs.getbifrost.ai/providers/routing-rules
- Complexity Router (embedding-based SIMPLE/MEDIUM/COMPLEX → CEL variable) also available; OSS/enterprise status not stated. — /features/governance/complexity-router

## Fallbacks / aliases / remapping
- Fallbacks: request-body `"fallbacks": ["anthropic/claude-...", "bedrock/..."]`, cross-provider; per-provider retries (`max_retries`, backoff); 429 rotates keys, 401/402/403 mark key dead; response `extra_fields.provider` shows who served. Routing rules also carry targets + fallbacks; VK-level weighted load balancing + "Automatic fallbacks". Streaming: buffers startup events (64 chunks / 256 KiB) so errors still hit retry/fallback (documented for Azure). — /features/retries-and-fallbacks, /features/fallbacks, /features/governance/routing
- Aliases: static per provider key `"aliases": {"best-model": "gpt-4o-2024-11-20"}` (config.json or `POST /api/providers/{provider}/keys`, UI implied); dynamic aliases via routing rules scoped to VK/team/customer/global; "without touching your application code"; response `extra_fields.routing_info` shows original vs resolved. — https://docs.getbifrost.ai/providers/aliasing-models
- Admin UI: yes, `http://localhost:8080` — "Visual provider setup", "Live monitoring", "Governance management - Virtual keys, usage budgets", routing rules builder, model limits. DB-backed config (SQLite/Postgres) allows live UI/API edits without restart. — /quickstart/gateway/setting-up

## Usage reporting & export
- Built-in Logs UI + `GET /api/logs` (filters: providers, models, status, objects, start/end_time, latency, tokens, min/max_cost, content_search, tool_call_names, request_id, limit/offset; returns `total_cost`, `total_tokens`) + WebSocket live stream. Documented filters do NOT include virtual key/team/customer — UNVERIFIED whether the API can filter per VK (UI/marketing claim per-VK cost breakdowns). Storage SQLite/Postgres (ClickHouse listed in one page). Retention `client_config.log_retention_days` default 365. — /features/observability/default, /features/observability, /enterprise/log-exports
- Attribution "(user ID, team, customer, business unit, virtual key) are metadata, not content" and persist even with content logging disabled. — /features/observability
- Exports: Enterprise "Log Exports" to S3/GCS only ("Azure Blob, local filesystem, and data warehouse destinations are not implemented"); OSS connectors: Prometheus, OTel, Datadog, BigQuery, Kafka, Pub/Sub, Splunk. No CSV download documented.

## Audio & image
- Endpoints: `POST /v1/audio/speech`, `POST /v1/audio/transcriptions`, `POST /v1/images/generations`, vision via chat. — https://docs.getbifrost.ai/quickstart/gateway/multimodal
- Provider matrix (https://docs.getbifrost.ai/providers/supported-providers/overview): 32 providers. OpenAI: chat/stream/embeddings/images/TTS/STT; Gemini: all incl. TTS/STT/images; Azure: all; Mistral: chat/embeddings/STT; xAI: chat/images; Anthropic: chat only; ElevenLabs: TTS+STT; Sarvam AI audio; Llama via Bedrock/Groq/Fireworks/Together/OpenRouter etc.
- OpenAI page: streaming for chat, responses, speech, transcriptions, image gen; tool calling with "multiple simultaneous tool calls". — /providers/supported-providers/openai

## Hosting & EU
- Self-host only. No managed/hosted cloud found on pricing, enterprise page, deployment overview, setting-up, or getmaxim.ai/bifrost. Deployment: Docker, npx, Helm/K8s, EKS/GKE/AKS, ECS, Cloud Run, Fly, Render, Railway; Enterprise "VPC | ON-PREM | AIR-GAPPED". — /deployment-guides/overview
- EU: no EU-specific docs; residency = wherever you deploy. trust.getmaxim.ai returned 403 (could not verify certifications). /security page covers CI/supply-chain only, silent on telemetry/data flow.
- Enterprise requires PostgreSQL 16+ ("does not support SQLite"); Cluster mode/HA is Enterprise-only → OSS = single instance.

## Gotchas
- Nothing is hosted for you: you run, patch, secure, and back up the gateway (incl. Postgres for HA).
- OSS has no HA clustering; per-user VK model means thousands of VKs — performance at that scale UNVERIFIED.
- Multi-customer header scoping, RBAC, log exports, audit logs, SSO are Enterprise (custom pricing, undisclosed).
- Logs API per-VK filtering not documented.
- Not fetchable: docs.getbifrost.ai/features/routing, /features/governance/budgets, /budgets-and-rate-limits, /customers-and-teams, /features/routing-rules, /features/governance/routing-rules (all 404), trust.getmaxim.ai (403).

# Bottom line for your use case
- Bifrost matches the functional wish-list best (per-user VK budgets daily+monthly hard limits, `budget_used > X` routing rule to a cheaper model, UI-configurable aliases/fallbacks, STT/TTS/image through one OpenAI-compatible endpoint, EU by choosing your host) but only as self-hosted OSS; no managed cloud.
- Helicone is managed and has per-user cost limits via header, fallback chains, and export, but no STT/TTS on the unified gateway, no admin-side aliasing, no "downgrade" logic, unclear credits status/fees, and the unified gateway appears US-only.

# Source list (all fetched 2026-09-09)
Helicone: https://www.helicone.ai/pricing · https://www.helicone.ai/credits · https://docs.helicone.ai/gateway/overview · https://docs.helicone.ai/gateway/provider-routing · https://docs.helicone.ai/gateway/concepts/error-handling · https://docs.helicone.ai/gateway/concepts/image-generation · https://docs.helicone.ai/gateway/concepts/responses-api · https://docs.helicone.ai/rest/ai-gateway/post-v1-chat-completions · https://docs.helicone.ai/rest/ai-gateway/get-v1models-multimodal · https://docs.helicone.ai/rest/models/get-v1public-model-registry-models · https://ai-gateway.helicone.ai/v1/models · https://docs.helicone.ai/features/advanced-usage/custom-rate-limits · https://docs.helicone.ai/features/advanced-usage/custom-properties · https://docs.helicone.ai/features/advanced-usage/user-metrics · https://docs.helicone.ai/helicone-headers/header-directory · https://docs.helicone.ai/helicone-headers/helicone-auth · https://docs.helicone.ai/references/data-autonomy · https://docs.helicone.ai/faq/compliance · https://docs.helicone.ai/guides/cookbooks/etl · https://docs.helicone.ai/getting-started/self-host/overview · https://docs.helicone.ai/getting-started/integration-method/gateway · https://docs.helicone.ai/llms.txt · https://github.com/Helicone/ai-gateway · https://www.helicone.ai/blog/how-to-gateway · https://www.helicone.ai/blog/ptb-gateway-launch · https://www.helicone.ai/blog/migration-openrouter · https://www.helicone.ai/changelog · https://www.truefoundry.com/blog/helicone-pricing (third-party)

Bifrost: https://github.com/maximhq/bifrost · https://github.com/maximhq/bifrost/releases · https://github.com/maximhq/bifrost/tree/main/docs/features · https://github.com/maximhq/bifrost/tree/main/docs/features/governance · https://getbifrost.ai/pricing · https://www.getmaxim.ai/pricing · https://www.getmaxim.ai/ · https://www.getmaxim.ai/bifrost/ · https://www.getmaxim.ai/bifrost/enterprise · https://docs.getbifrost.ai/ · https://docs.getbifrost.ai/llms.txt · https://docs.getbifrost.ai/features/governance · https://docs.getbifrost.ai/features/governance/virtual-keys · https://docs.getbifrost.ai/features/governance/budget-and-limits · https://docs.getbifrost.ai/features/governance/model-limits · https://docs.getbifrost.ai/features/governance/required-headers · https://docs.getbifrost.ai/features/governance/complexity-router · https://docs.getbifrost.ai/features/governance/routing · https://docs.getbifrost.ai/providers/routing-rules · https://docs.getbifrost.ai/providers/aliasing-models · https://docs.getbifrost.ai/features/retries-and-fallbacks · https://docs.getbifrost.ai/features/fallbacks · https://docs.getbifrost.ai/features/keys-management · https://docs.getbifrost.ai/features/observability · https://docs.getbifrost.ai/features/observability/default · https://docs.getbifrost.ai/enterprise/log-exports · https://docs.getbifrost.ai/enterprise/overview · https://docs.getbifrost.ai/enterprise/access-profiles · https://docs.getbifrost.ai/deployment-guides/overview · https://docs.getbifrost.ai/deployment-guides/config-json/governance · https://docs.getbifrost.ai/quickstart/gateway/setting-up · https://docs.getbifrost.ai/quickstart/gateway/multimodal · https://docs.getbifrost.ai/providers/supported-providers/overview · https://docs.getbifrost.ai/providers/supported-providers/openai · https://docs.getbifrost.ai/features/drop-in-replacement · https://docs.getbifrost.ai/security
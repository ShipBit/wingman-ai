text
I have enough verified material now; the remaining unknowns (TrueFoundry SaaS hosting region, log-retention days, Kong consumer limits) came back empty from the live pages, so I'll mark them UNVERIFIED rather than fetch further.

# AI Gateway research: Kong Konnect AI Gateway vs TrueFoundry AI Gateway

All facts below come from pages fetched live on 2026-09-09. Anything I could not confirm from a live page is marked UNVERIFIED. The WebSearch budget for this session was exhausted near the end; the last round used WebFetch only.

---

## 1. Kong AI Gateway / Kong Konnect

### Pricing (konghq.com/pricing, fetched 2026-09-09)

- **No permanent free tier.** The page only offers "Free trial: $0 for 30 days no credit card required". The Konnect account docs also list only two plans ("Konnect Plus" and "Konnect Enterprise") and say "A free Konnect organization is automatically deactivated after 30 days of inactivity." What happens at trial end (auto-downgrade vs. lock) is not stated - UNVERIFIED.
- **Plus** - "Charged per Gateway per month, bill monthly":
  - Control plane fees: Serverless Gateways "$25/month per control plane" (up to 5); Hybrid (self-hosted data plane) "$200/month per control plane" (up to 2); Dedicated Cloud Gateways "$500/month per control plane" + "$0.15 per GB" bandwidth, "Limited to one region per control plane" (up to 2).
  - Gateway traffic: "1 million API requests" included/month, "$200/month per additional 1 million API requests/month", hard cap "10 million API requests/month".
  - **AI Gateway model metering (the big one):** "Universal LLM API with up to 5 unique LLM models", "$100/month per model", FAQ: "AI Gateway model proxy limit: Unique LLMs proxied by AI plugins measured hourly, enforced monthly." Enterprise: "No limits".
  - Advanced Analytics: "First 1M API requests included/month", "$20 per 1M API requests above 1M", storage "10M/month", retention "14 months".
  - Support: "Email only", "2 business days".
- **Enterprise** - "Custom pricing billed annually", "No region limitations", SSO and Audit logging Enterprise-only.
- Plus AI feature list (quoted): "Token-based rate limiting and semantic caching", "PII sanitization and prompt guardrails", "LLM access control and auth", "Token-level tracking and real-time cost analytics", "Unlimited MCP server proxies".

### Per-end-user budget / rate limits

- **Yes, via `ai-rate-limiting-advanced`** (docs: "only available as part of our AI Gateway Enterprise offering" - but Plus lists "Token-based rate limiting", so it appears included in Konnect Plus; exact Plus entitlement not stated in the plugin doc - partially UNVERIFIED).
  - `config.identifier` enum: `consumer` (default), `consumer-group`, `credential`, `header`, `ip`, `path`, `service`. Per end user = one Kong Consumer per user (key-auth) or a header.
  - `config.tokens_count_strategy`: `total_tokens`, `prompt_tokens`, `completion_tokens`, `cost`. Cost formula: "(prompt_tokens x input_cost + completion_tokens x output_cost) / 1,000,000"; needs `input_cost`/`output_cost` "in the AI Proxy or AI Proxy Advanced plugin configuration, under `model.options`" ("cost per 1M tokens").
  - Windows: `window_size` "defined in seconds", multiple windows per rule; `window_type` sliding/fixed. No documented max; no daily/monthly example in docs (examples use 60 s and 3600 s). Monthly = you'd set 2592000 s - UNVERIFIED that this is supported/accurate.
  - Storage: `local`, `cluster`, `redis`. On Serverless Gateways "only the `local` config strategy is supported" (compatibility page) - i.e. counters are per node, not shared. Hard limit returns `error_code` 429 by default.
- **"Downgrade to cheaper model after X usage": not a native feature.** `ai-proxy-advanced` `failover_criteria` includes `http_429`, but the docs contain "no statement describing whether a 429 response from this rate limiting plugin triggers failover" - UNVERIFIED/likely not. A workaround would be consumer-groups with different plugin configs, which you'd have to orchestrate yourself.
- Konnect "Metering & Billing prepaid credits" (blog, July 1, 2026) is a monetization product ("When the balance hits zero, you can either block the usage automatically or allow it to go negative"); the post does not describe gateway-level per-end-user enforcement and does not state plan availability.

### Fallback, alias / remapping, admin UI

- `ai-proxy` (open source; present in github.com/Kong/kong `kong/plugins/`): FAQ says "The model name must match the one configured in `config.model.name`. If a different model is specified in the request, the plugin returns a 400 error." So remapping requires `ai-proxy-advanced`.
- `ai-proxy-advanced` (Enterprise; absent from OSS repo): `config.targets[].model.model_alias` = "The model name parameter from the request that this model should map to." Balancer algorithms: `round-robin`, `consistent-hashing`, `least-connections`, `lowest-latency`, `lowest-usage`, `semantic`, `priority`. Retries default 5; `failover_criteria`: `error, http_403, http_404, http_429, http_500, http_502, http_503, http_504, invalid_header, non_idempotent, timeout`; "Client errors don't trigger failover." Circuit breaker via `max_fails` / `fail_timeout`. On serverless "only the `memory` config strategy is supported".
- **UI:** AI Gateway 2.x (GA blog dated Sept 1, 2026) moves to an entity model: "An AI Model defines the upstream provider, model name, and routing behavior that the old AI Proxy plugin handled." Management options listed on developer.konghq.com/ai-gateway/: "AI Gateway Manager (Konnect UI) - Manage all your AI Gateway resources from Konnect", "AI Gateway API", "kongctl"; decK for self-hosted. The dedicated AI Model entity docs page 404'd, so field-level details are UNVERIFIED.
- 2.0 also adds a reusable "pricing catalog" with "pricing dimensions for text, audio, image, and video, plus cache read and cache write fields".

### Usage reporting & export

- Konnect Advanced Analytics Explorer has an "LLM Usage" datasource: Prompt/Completion/Total Tokens, Costs, LLM Latency, Request/Response Model, Provider Name; filter/group by Consumer, Application, Route, Control Plane; "Export as CSV" (current filters + time window); also API/Terraform-driven. Retention 14 months on Plus; analytics billed at "$20 per 1M API requests above 1M".

### Audio / image

- `config.route_type` enum (ai-proxy reference): `llm/v1/chat`, `llm/v1/completions`, `llm/v1/embeddings`, `llm/v1/files`, `llm/v1/batches`, `llm/v1/assistants`, `llm/v1/responses`, `realtime/v1/realtime`, `audio/v1/audio/speech`, `audio/v1/audio/transcriptions`, `audio/v1/audio/translations`, `image/v1/images/generations`, `image/v1/images/edits`, `video/v1/videos/generations`, `preserve`. Same list on ai-proxy-advanced. TTS example uses `provider: openai`, `name: tts-1`; image-gen examples exist for OpenAI and xAI. `response_streaming`: `allow | always | deny`; "Function calling" listed as supported.
- Providers (ai-proxy reference enum): anthropic, azure, bedrock, cerebras, cohere, dashscope, databricks, deepseek, gemini, huggingface, llama2, mistral, ollama, openai, vllm, xai. 2.0 adds Kimi, Microsoft Foundry, SageMaker.
- Gotcha: each audio/image model counts toward the "5 unique LLM models" / $100 per model cap on Plus (FAQ wording covers "Unique LLMs proxied by AI plugins"; whether TTS/STT models count is not spelled out - UNVERIFIED but likely).

### Hosting & EU

- Control plane geos: AU, EU, ME, US, IN, SG. "Only authentication, billing, and usage is shared between Konnect geos"; consumers, services, routes are geo-specific.
- Serverless Gateways: "V1 (US and EU regions only)", limit "100 requests per second (RPS) per gateway", "maximum payload size of 10MB", "Deployment on the same region is not guaranteed".
- Dedicated Cloud Gateways EU regions: AWS Frankfurt, Ireland, London, Paris, Zurich; Azure germanywestcentral, uksouth, northeurope, francecentral; GCP europe-west1/2/3. All nine AI plugins "supported on Dedicated Cloud Gateways".
- Hybrid = self-hosted data plane anywhere.

### Honest take for a small team

Overkill, and structurally mismatched. Kong's unit economics are built around control planes and per-model fees: a realistic stack (2 chat models + STT + TTS + image) is already at the 5-model Plus cap = $500/month before the $25-$500 control-plane fee and $200 per extra 1M requests. There is no free tier after 30 days. Per-end-user budgets require managing one Kong Consumer per subscriber and running the limits on Redis (not on the cheap serverless tier, where counters are node-local). Model remapping needs the Enterprise-labelled `ai-proxy-advanced`. On the plus side: real EU data-plane choices, CSV/API analytics, and audio/image/realtime route types are genuinely there.

Sources (all fetched 2026-09-09): https://konghq.com/pricing, https://developer.konghq.com/konnect-platform/account/, https://developer.konghq.com/ai-gateway/, https://developer.konghq.com/plugins/ai-proxy/, https://developer.konghq.com/plugins/ai-proxy/reference/, https://developer.konghq.com/plugins/ai-proxy/examples/audio-speech-openai/, https://developer.konghq.com/plugins/ai-proxy-advanced/, https://developer.konghq.com/plugins/ai-proxy-advanced/reference/, https://developer.konghq.com/plugins/ai-rate-limiting-advanced/, https://developer.konghq.com/plugins/ai-rate-limiting-advanced/reference/, https://developer.konghq.com/plugins/ai-semantic-cache/, https://developer.konghq.com/plugins/compatibility/, https://developer.konghq.com/advanced-analytics/explorer/, https://developer.konghq.com/konnect-platform/geos/, https://developer.konghq.com/serverless-gateways/reference/, https://developer.konghq.com/dedicated-cloud-gateways/reference/, https://konghq.com/blog/product-releases/kong-ai-gateway-2-0-ga, https://konghq.com/blog/product-releases/kong-ai-manager, https://konghq.com/blog/product-releases/metering-billing-prepaid-credits, https://github.com/Kong/kong/tree/master/kong/plugins. 404 on fetch: /konnect-platform/plans/, /advanced-analytics/llm-reporting/, /index/ai-gateway/, /ai-gateway/ai-models/.

---

## 2. TrueFoundry AI Gateway

### Pricing (truefoundry.com/pricing, fetched 2026-09-09)

| | Developer | Pro | Pro Plus | Enterprise |
|---|---|---|---|---|
| Price | "$0 / month" | "$499/ month" | "$2999/ month" | "Custom" |
| Requests/month | "50k" | "1M" | "1M" | "Custom 10M Plus" |
| Platform users | 3 | 10 | 25 | Custom |
| Budget limiting | no | yes | yes | yes |
| Rate limiting | no | yes | yes | yes |
| Fallbacks | no | yes | yes | yes |
| Semantic caching | no | no | yes | yes |
| SSO | no | no | yes | yes |
| Logs/Traces | "Basic" | "Included" | "Custom retention" | "Custom retention" |
| Deployment | SaaS only | SaaS only | SaaS only | "SaaS + VPC/On-prem + Air-gapped" |
| Support | none listed | "Standard SLA" | "Enterprise-Grade SLA" | "Enterprise-Grade SLA" |

- Overage FAQ (Pro): "You'll simply be billed for additional usage at transparent, per-unit rates. 2M requests and 5 API keys for additional $499 per month." Pro Plus: "Contact sales for additional usage charges."
- No percentage-of-spend fee anywhere on the page; billing is per request count. Log retention in days is not published anywhere I could fetch - UNVERIFIED. The "5 API keys" wording implies an API-key cap per plan that is not shown in the table - UNVERIFIED.
- Key gotcha: the free Developer tier has **no** budget limiting, rate limiting or fallbacks - everything you need starts at $499/month.

### Per-end-user budget / rate limits

- **Budget Limiting** (docs/ai-gateway/budgetlimiting): configured in UI ("AI Gateway -> Policies -> Budget Limiting") or YAML. `budget_applies_per` accepts `user`, `virtualaccount`, `model`, or `'metadata.<key>'` - "Each unique `project_id` value gets its own $100/day budget". Units: "Cost per day - resets at UTC midnight", "Cost per week - resets on Monday", "Cost per month - resets on the 1st". Modes: block (default; HTTP 429, body "Budget exceeded for model: ... with rule: ...", header `x-tfy-applied-rules`) or "Audit mode". Alerts: "any percentage value between 0 and 100" via email / Slack webhook / Slack bot (`alerts.thresholds`, `notification_target`). No stated limit on number of tracked entities. Example: `limit_to: 10, unit: cost_per_day, budget_applies_per: ['user']`.
- **Rate Limiting** (docs/ai-gateway/ratelimiting): `rate_limit_applies_per: ['metadata.project_id']` supported ("One rate limit per custom metadata value"). Units only: `requests_per_minute/hour/day`, `tokens_per_minute/hour/day` - **no weekly/monthly** rate units (use budgets for that). Sliding window. 429 + `x-tfy-applied-rules`.
- End-user identity: your app sends `X-TFY-METADATA: {"customer_id":"123456"}` ("Stringified JSON where both keys and values must be strings", "maximum value length of 128 characters"); virtual-account tags are auto-added as metadata. Note this means the desktop client needs to be trusted to send the right customer_id, or you proxy through your own backend.
- **"Downgrade to cheaper model after budget": not documented.** Budget docs: no mention of automatic model downgrading. Routing overview: "No mention exists of cost-based or budget-based routing." A TrueFoundry blog claims "requests start returning 429s or fall back to a cheaper model based on your configured policy" but shows no configuration - UNVERIFIED.

### Fallback, alias / remapping, admin UI

- **Virtual Models** (docs/ai-gateway/virtual-model): "a named entry in TrueFoundry AI Gateway that your application calls like any other model" with "one routing strategy and one or more real target models"; "Your apps pass one model identifier; you change targets, weights, or providers in the AI Gateway without redeploying clients." Called via the OpenAI `model` field (e.g. `my-group/production-chat`). Configurable in "dashboard UI ... form editor", YAML, and API.
- Routing config (docs/ai-gateway/load-balancing-overview): rules with `when: {subjects, models, metadata}`, "first matching rule wins"; types `weight-based-routing`, `latency-based-routing`, `priority-based-routing`; managed under "AI Gateway -> Configs -> Routing Config" or Git + `tfy apply`.
- Fallback (docs/ai-gateway/fallback): per target `fallback_status_codes` (default `["401","403","404","408","429","500","502","503"]`), `fallback_candidate`, `retry_config: {attempts, delay, on_status_codes}`; "Retries: attempts on the SAME target", fallback = different target; unhealthy targets demoted.
- Streaming (`stream=True`) and tool calling documented on the OpenAI page; model names are `provider-account/model`, e.g. `openai-main/gpt-4o-mini`.

### Usage reporting & export

- Metrics Dashboard (docs/ai-gateway/analytics): requests, input/output tokens, cost, latency incl. TTFT/ITL/TPOT percentiles; group by model, virtual model, users, virtual accounts, teams, "Custom metadata keys sent in request headers"; "download aggregated metrics data in CSV format"; metrics APIs per datasource.
- Logs API (docs/ai-gateway/fetch-request-logs): `POST https://{control_plane_url}/api/svc/v1/spans/query` with `startTime`, user/virtual-account/metadata filters, `pageToken`/`nextPageToken`.
- Bulk export (docs/ai-gateway/export-logstraces): **manual** - email support@truefoundry.com "Logs/Traces Export - [YOUR_ORG_NAME]"; returned "in JSON format". OTel/Prometheus export is claimed on marketing pages; not verified in docs.

### Audio / image

- Supported endpoints listed on the OpenAI page: `/chat/completions`, `/embeddings`, `/responses`, `/images/generations`, `/images/edits`, `/images/variations`, `/audio/speech`, `/audio/transcriptions`, `/audio/translations`, `/batches`, `/files`, `/moderations`, `/fine_tuning/jobs`, Realtime `/live/{provider-account}`.
- TTS providers: OpenAI, Azure OpenAI, Azure AI Foundry, Vertex, Gemini, Groq, DeepGram, Cartesia, ElevenLabs, Resemble AI, Smallest AI (OpenAI-compatible for OpenAI/Azure/Groq; native SDK passthrough for the rest); streaming example shown.
- STT providers: OpenAI, Azure OpenAI, Azure AI Foundry, Groq, Deepgram, Cartesia, ElevenLabs, Vertex, Smallest AI; models cited whisper-1, whisper-large-v3, nova-3, ink-2, scribe_v2; native providers via `{GATEWAY_BASE_URL}/stt/{providerAccountName}`. Gotcha: "the model ID in code must match the display name of the model on your TrueFoundry model account."
- Image generation: OpenAI/Azure `gpt-image-1, dall-e-2, dall-e-3`; Vertex Imagen 3/4 + Gemini image models; Bedrock Titan/Nova + Stability. Not for Anthropic, Cohere, Groq, xAI.

### Hosting & EU

- SaaS is the only option on Developer/Pro/Pro Plus; VPC/on-prem/air-gapped are Enterprise-only ("Enterprise supports full VPC and air-gapped installations for both control and gateway planes").
- EU residency: press release (Apr 30, 2026) describes "regional gateway planes execute specific requests locally within their region"; the data-residency blog achieves EU residency by "you spin up an EKS cluster in eu-central-1 (Frankfurt)" - i.e. customer-run infrastructure. Intro docs say the SaaS is "hosted in multiple regions across the world" but name no region; trust.truefoundry.com returned an empty body. **Whether an EU-hosted SaaS control/gateway plane exists for non-Enterprise plans is UNVERIFIED.** GDPR compliance announced Dec 30, 2025; DPA availability not found.

### Notable gotchas

- Free tier is essentially a demo (50k req, no budgets/rate limits/fallbacks).
- Rate-limit windows max out at "day"; monthly caps only via cost budgets.
- Bulk log export is a support-ticket process, not self-serve.
- Virtual accounts are created in the UI ("Access > Virtual Accounts"); no documented API to mint them programmatically per end user, so per-end-user attribution is metadata-based, not key-based.

Sources (all fetched 2026-09-09): https://www.truefoundry.com/pricing, https://www.truefoundry.com/ai-gateway, https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway, https://www.truefoundry.com/docs/ai-gateway/budgetlimiting, https://www.truefoundry.com/docs/ai-gateway/ratelimiting, https://www.truefoundry.com/docs/ai-gateway/fallback, https://www.truefoundry.com/docs/ai-gateway/load-balancing-overview, https://www.truefoundry.com/docs/ai-gateway/virtual-model, https://www.truefoundry.com/docs/ai-gateway/openai, https://www.truefoundry.com/docs/ai-gateway/text-to-speech, https://www.truefoundry.com/docs/ai-gateway/audio-transcription, https://www.truefoundry.com/docs/ai-gateway/image-generation, https://www.truefoundry.com/docs/ai-gateway/request-headers, https://www.truefoundry.com/docs/ai-gateway/analytics, https://www.truefoundry.com/docs/ai-gateway/fetch-request-logs, https://www.truefoundry.com/docs/ai-gateway/export-logstraces, https://www.truefoundry.com/docs/ai-gateway/authentication, https://www.truefoundry.com/docs/ai-gateway/gateway-access-control, https://www.truefoundry.com/docs/generating-truefoundry-api-keys, https://www.truefoundry.com/press-room/truefoundrys-ai-gateway-helps-companies-meet-global-data-residency-requirements, https://www.truefoundry.com/blog/decoupling-control-and-data-truefoundrys-strategy-for-global-ai-ml-data-residency, https://www.truefoundry.com/blog/truefoundry-announces-gdpr-compliance, https://www.truefoundry.com/blog/tokenmaxxing-building-the-ai-leverage. 404 / empty: /docs/ai-gateway/load-balancing, /docs/ai-gateway/virtual-models, /docs/ai-gateway/logs, https://trust.truefoundry.com.

---

## Bottom line for your use case

- **TrueFoundry** matches the feature checklist better: per-end-user daily/weekly/monthly cost budgets keyed on a metadata value, hard block or audit mode with threshold alerts, virtual-model aliases changeable in a UI, fallback/retry rules, one OpenAI-compatible endpoint covering chat + STT + TTS + image + realtime, CSV export grouped by your customer id. Cost: $499/month minimum for those features, 1M requests included, then $499 per extra 2M. Missing: native "downgrade after X usage", monthly rate windows, self-serve bulk export, and a verified EU SaaS region below Enterprise.
- **Kong** is a full API-management platform with an AI layer bolted on. It can do per-consumer token/cost limits and model aliasing, has real EU regions, and has the same modality coverage, but pricing ($100/model/month, capped at 5 models on Plus, plus control-plane and per-1M-request fees, no free tier) and operational weight (Consumers, Redis for shared counters, decK/kongctl) make it overkill for a small consumer-app team.
text
All the remaining URL guesses 404'd, so further guessing would be wasteful. I have enough verified material to report.

# Findings (all fetched live on 2026-09-09; nothing below is from memory)

## 1. Unify (unify.ai) — the LLM router no longer exists

**Status:** The LLM router/gateway product is gone. Unify pivoted (during 2025) to an "AI teammates / virtual colleagues" product, and that second product has now also been wound down (Aug 2026). The homepage is a placeholder.

- Homepage today shows only: "Bridging symbolic reasoning and continual learning." / "More coming soon." / contact team@unify.ai. No nav, no pricing, no docs. — https://unify.ai (fetched 2026-09-09)
- `https://unify.ai/pricing` → HTTP 404; `https://unify.ai/docs` → 404; `https://unify.ai/blog` → 404 (fetched 2026-09-09)
- `docs.unify.ai` and `api.unify.ai` → DNS does not resolve (ENOTFOUND) (fetched 2026-09-09)
- `https://console.unify.ai` now shows a wind-down notice: "We're winding down our AI teammate product" / "This product is no longer available. Thank you to everyone who built with us on it — it meant a great deal." / "Unify isn't going anywhere. We're focusing our attention on something new..." / "Questions, or need a copy of your data? support@unify.ai" (fetched 2026-09-09; also verbatim in https://raw.githubusercontent.com/unifyai/winddown-console/main/index.html, CNAME = console.unify.ai)
- Second wind-down page (CNAME r.unify.ai): "That link doesn't go anywhere any more ... We've wound down our AI teammate product since then ... If you were on your way to claim free credits, those have gone with it." — https://raw.githubusercontent.com/unifyai/winddown/main/index.html (fetched 2026-09-09)
- GitHub org description is now "Virtual colleagues that learn on the job"; repos `winddown` and `winddown-console` archived Aug 26–27, 2026. The `unillm` repo is a local MIT Python library ("Lightweight LLM access layer with provider normalization, caching, and observability"), not a hosted router. — https://github.com/unifyai, https://github.com/unifyai/unillm (fetched 2026-09-09)
- The `unifyai/unify` README still says "use the hosted product at console.unify.ai" — contradicted by the console wind-down page; treat the README as stale. — https://github.com/unifyai/unify (fetched 2026-09-09)

**Pricing:** No live pricing exists. Historical router pricing could not be verified (web.archive.org and archive.ph are blocked for this tool; G2 returned 403). Only a third-party SourceForge listing says "Starting at $1 per credit" with a free version/trial — UNVERIFIED and stale. — https://sourceforge.net/software/product/Unify-AI/ (fetched 2026-09-09)

**Per-end-user budgets / fallbacks / remapping / usage export / audio+image / hosting / EU:** N/A — no product to evaluate. Note: several 2026 "review" sites still describe Unify as an active router (e.g. nrouter.ai comparison dated 2026-06-05 that defers to "unify.ai/pricing", which is now a 404) — these are SEO content and should not be trusted. — https://nrouter.ai/blog/product/unify-ai-alternative (fetched 2026-09-09)

**Verdict for your use case:** Eliminate.

## 2. Not Diamond (notdiamond.ai) — a router, explicitly NOT a gateway

**What it is:** A model-selection API. Your code sends messages, gets back a recommended `provider/model`, and then you call that model yourself. Tagline today: "the world's most powerful intelligent model router for coding agents." — https://www.notdiamond.ai (fetched 2026-09-09)

- Quickstart: `client.model_router.select_model()` returns `session_id` and `provider.model`; "developers must independently call the chosen model." `tradeoff` = "cost" | "latency" | omitted (quality); also `cost_quality_tradeoff` 0–10. — https://docs.notdiamond.ai/docs/quickstart-routing (fetched 2026-09-09)
- Their own blog (2026-06-16) draws the line: "A gateway governs deterministic model access while a router automatically decides which model to use." Not Diamond is "the decision layer above the gateway"; quotas/budget, provider failover, billing are explicitly the gateway's job. — https://www.notdiamond.ai/blog/model-routing-vs-gateways-breaking-down-the-difference (fetched 2026-09-09)
- Strategic shift: "Not Diamond Code" (announced 2026-08-04) is a local proxy for coding agents (Claude Code only documented), upstream = Anthropic direct, AWS Bedrock, or an internal gateway URL; early access via waitlist; "raw prompts, code, inputs, and outputs are not sent to Not Diamond." — https://www.notdiamond.ai/blog/not-diamond-code-intelligent-model-routing-for-coding-agents, https://code.notdiamond.ai/docs/, https://code.notdiamond.ai/docs/getting-started/configuration/ (fetched 2026-09-09)

**Pricing (exact):**
- Pricing page has only two plans. "Pay-as-you-go": "$0.05 per million tokens routed" (features: multi-harness support, multi-provider support, savings and usage dashboard, continuous learning from harness usage; "Application required"). "Enterprise": volume-based discounts, org-wide analytics, advanced security/admin controls, SSO with SAML, "Privacy-preserving deployment"; contact sales. No free tier, no trial wording on the page. FAQ: "We charge a small fixed fee per million tokens which is cheaper than the cheapest LLM." — https://www.notdiamond.ai/pricing (fetched 2026-09-09)
- Gotcha: the AWS Marketplace listing shows a different, older 3-tier scheme — "Discovery" free up to 100k monthly API routing requests; "Possibility" $100/month + "$0.001 per API routing request" over the free allowance; "Necessity" custom with VPC deployments. Conflicts with the website; likely stale. — https://aws.amazon.com/marketplace/pp/prodview-erda4iu26h4tm (fetched 2026-09-09)

**Per-end-user budgets / rate limits:** No. Nothing in the docs; the only limit is a platform rate limit of 50 requests/second → 429; higher via a sales call. — https://docs.notdiamond.ai/docs/rate-limits (fetched 2026-09-09)

**Fallbacks / model aliasing:** No gateway-style fallbacks — you implement them. A `default` model parameter (used when Not Diamond itself fails to answer) appears in a search snippet from `docs/fallbacks-and-timeouts`, but that page returned 404 when fetched — UNVERIFIED. Custom models must use a fixed unique `provider/model` id ("cannot match any supported model", one slash max); no alias/remapping mechanism. — https://docs.notdiamond.ai/docs/routing-between-custom-models.md (fetched 2026-09-09)

**OpenAI-compatible proxy endpoint:** None hosted by Not Diamond. OpenRouter's `openrouter/auto` is the closest thing; OpenRouter's current doc says it is "powered by the market: the aggregate spend of millions of people using OpenRouter" (not Not Diamond), no extra fee, streaming and tool calling supported. A Jan 2025 tweet by ND's CEO said ND powered OpenRouter routing; the current doc no longer credits ND. — https://openrouter.ai/docs/guides/routing/routers/auto-router (fetched 2026-09-09)

**Usage reporting/export:** "Savings and usage dashboard" only; no export documented. Not Diamond Code has `notdiamond status` / `notdiamond logs -f` CLI. — https://www.notdiamond.ai/pricing, https://code.notdiamond.ai/docs/getting-started/usage/ (fetched 2026-09-09)

**Audio / image:** Text LLM routing only. The `/models` reference states "Image generation models are excluded"; the supported-models table has only "Function calling" and "Structured outputs" columns, no vision/audio mention. 13 providers listed (OpenAI, Anthropic, Google, Mistral, xAI, Replicate, TogetherAI, Perplexity, Cohere, Minimax, DeepSeek, Qwen, Inception). — https://docs.notdiamond.ai/llms.txt, https://docs.notdiamond.ai/docs/llm-models.md (fetched 2026-09-09)

**Hosting / EU:** Hosted SaaS; "SOC-2 and ISO27001 compliant", AES-256 at rest, TLS in transit. Enterprise offers "Privacy-preserving deployment" / VPC. No hosting region or EU residency statement anywhere fetched — UNVERIFIED. About page gives no location. — https://docs.notdiamond.ai/docs/privacy-security-and-local-deployments.md, https://www.notdiamond.ai/about (fetched 2026-09-09)

**Verdict for your use case:** Not a fit. It solves "which model?" only, and you'd still need a full gateway for budgets, fallbacks, remapping, audio/image. Also clearly re-focusing on enterprise coding-agent customers.

## 3. Other managed gateways with per-END-USER budgets (brief)

**Respan (formerly Keywords AI; rebranded 2026-02-20; keywordsai.co 301s to respan.ai)** — best match found for per-end-user budgets.
- Per-customer budgets via `customer_params` on gateway requests: `budget_duration` ("monthly"/"weekly"/"daily"), `period_budget` (USD), `total_budget` (lifetime USD), `rate_limit` (req/min); "Customer monthly budget" enforced via block; budgets adjustable per customer via the Users API; per-API-key lifetime/recurring caps and org hard cap in Settings > Limits. Custom model aliases in dashboard ("multiple aliases for the same underlying model"); fallbacks central (Settings → Fallback) or per request (`fallback_models`). Gateway at `https://api.respan.ai/api/` handles chat, embeddings, audio STT/TTS, image generation, files. Adds "50 to 150ms" latency. "EU data residency available upon request", SOC 2 Type II, GDPR DPA. Per-user page + log filters; no export feature documented.
- Pricing: Free $0 (100k logs, gateway 412 req/min, 7-day retention), Team $199/mo (8,400 req/min, 30-day retention, 5 seats, +$15/seat), Enterprise custom; overage $8/100k logs. Gateway token fee/markup: not stated — UNVERIFIED.
- https://www.respan.ai/pricing, https://www.respan.ai/docs/documentation/features/gateway/gateway-quickstart, https://respan.ai/docs/documentation/features/customer-identifier.md, https://respan.ai/docs/documentation/features/gateway/limits.md, https://respan.ai/docs/documentation/features/gateway/custom-models.md, https://respan.ai/docs/documentation/features/gateway/advanced.md, https://respan.ai/docs/documentation/compliance.md (fetched 2026-09-09)

**Cloudflare AI Gateway** — Spend limits (launched 2026-06-05) scoped "by model, provider, or admin-defined custom attributes like user, team, or application"; "Split by value" gives "each distinct value ... its own independent budget bucket" (e.g. "give each user a $200/day budget"); on exceed: block by default, "or ... route requests to a fallback model after you've hit a spend limit" via Dynamic Routes (visual UI or JSON; a "Budget Limit" node switches to fallback). Max 20 spend-limit rules per gateway; cost tracking is "best-effort estimation". Core gateway free; Unified Billing adds "A 5% fee"; provider prices pass through. EU residency and audio/image via gateway: UNVERIFIED. — https://blog.cloudflare.com/ai-gateway-spend-limits/, https://developers.cloudflare.com/ai-gateway/features/spend-limits/, https://developers.cloudflare.com/ai-gateway/features/dynamic-routing/, https://developers.cloudflare.com/ai-gateway/reference/pricing/ (fetched 2026-09-09)

**Vercel AI Gateway** — Zero markup; budgets at team/project/API key/user scopes, but "user" = team member, not end user. End users are reporting-only (`providerOptions.gateway.user` or `ai-reporting-user` header; `/v1/report?group_by=user`, Pro/Enterprise, $0.075/1k user-ID writes, $5/1k queries). Exceeded budget → HTTP 402; "soft cap"; no fallback-on-budget. Workaround (one API key per end user + API-key default budget) is not documented as intended — UNVERIFIED. — https://vercel.com/docs/ai-gateway/observability-and-spend/budgets, https://vercel.com/docs/ai-gateway/observability-and-spend/custom-reporting, https://vercel.com/docs/ai-gateway/pricing, https://vercel.com/changelog/set-per-user-budgets-on-ai-gateway (fetched 2026-09-09)

**Zuplo AI Gateway** — Budgets at org/team/app (daily or monthly; cost, tokens or requests); on exceed → 429 or "fall back to a cheaper model" (quota fallback), configured in Portal UI. But "apps" = "a service, an environment, a product, or a squad"; "user-level identity tracking" is "coming next" (post dated 2026-08-19) → no per-end-user budgets yet. Pricing: Free ≤100K req/mo; Builder $25/mo ≤100K then $100 per extra 100K up to 1M; Enterprise from $1,000/mo. Managed edge, managed dedicated, or self-host; EU region not specified. — https://zuplo.com/docs/ai-gateway/fallback, https://zuplo.com/blog/attribute-ai-spend-teams-apps, https://zuplo.com/pricing (fetched 2026-09-09)

**Braintrust** — "The AI proxy is deprecated ... Use the gateway instead." Gateway is public preview, "free to use", pricing TBA; OpenAI-compatible; failover via `x-bt-fallback-providers`; hosted regions include EU West (Ireland); no per-user budgets documented. — https://www.braintrust.dev/docs/guides/proxy, https://www.braintrust.dev/docs/deploy/gateway (fetched 2026-09-09)

**Martian** — withmartian.com is now an interpretability research org ("Understanding Intelligence"); docs still describe a gateway at `https://api.withmartian.com/v1/chat/completions` (200+ models, OpenAI/Anthropic compatible) but pricing, budgets, fallbacks pages could not be found (pricing URLs 404). Third-party snippets claiming "free 2,500 req/mo, $20/mo, 5.5% fee" are UNVERIFIED. — https://withmartian.com, https://docs.withmartian.com/gateway (fetched 2026-09-09)

**Lunar.dev** — "Licensed per seat. Fully self-hosted."; AI Gateway deploys "as a self-hosted cluster"; "limits on AI API calls per user, app, or agent". Not managed → poor fit. — https://www.lunar.dev/pricing, https://www.lunar.dev/product/ai-gateway (fetched 2026-09-09)

(Databricks Unity AI Gateway also has per-user monthly budgets, GA June 2026, but requires a Databricks workspace — enterprise-only context; search snippet only, not fetched.)

**Bottom line:** Unify and Not Diamond are both out. Of the extras, Respan is the only managed gateway found that verifiably does per-end-user daily/weekly/monthly budgets plus fallbacks, aliasing, STT/TTS/image through one OpenAI-compatible endpoint, with EU residency on request; Cloudflare is the strongest "budget → downgrade to cheaper model" implementation (per-user via metadata split) but EU/audio support unverified.

**Note:** The session's WebSearch budget (200 calls) was exhausted mid-task; the last steps used WebFetch only. Also, the Figma MCP server failed to connect and needs re-authorization — not relevant to this task.
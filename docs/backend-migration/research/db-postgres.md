text
All fetches are done; the only remaining gap (Turso's full region list) could not be closed because both docs pages 404, so I'll flag that explicitly. Here is the report.

# Managed DB options for a small SaaS backend (research date 2026-09-09)

Workload assumed: 2k–10k subscribers, ~50 API req/user/day → 100k–500k req/day, 1–3 small queries each → ~0.1–1.5M queries/day (~3–45M/month). All numbers below come from live fetches of official pages; where a page did not state something, I say so.

---

## 1. Neon (serverless Postgres)

**Plans** (https://neon.com/pricing, https://neon.com/docs/introduction/plans)

| | Free | Launch | Scale |
|---|---|---|---|
| Base fee | $0 | "Pay for what you use" — docs: "On Launch and Scale plans, you pay only for what you use; there's no minimum monthly fee" | same, no minimum |
| Projects | 100 | 100 | 1,000 |
| Storage | 0.5 GB/project | $0.35/GB-month | $0.35/GB-month |
| Compute | 100 CU-hours/project (per month) | $0.106/CU-hour | $0.222/CU-hour |
| Branches | 10/project | 10/project (+$1.50/branch-month) | 25/project (+$1.50/branch-month) |
| Autoscaling max | up to 2 CU (8 GB RAM) | up to 16 CU (64 GB) | 16 CU autoscaling, or fixed up to 56 CU (224 GB) |
| Scale to zero | after 5 min, cannot disable | after 5 min, can be disabled | configurable 1 min → always on |
| PITR / instant restore | 6 hours, up to 1 GB-month | up to 7 days, $0.20/GB-month | up to 30 days, $0.20/GB-month |
| Egress | 5 GB incl. | 500 GB/project incl., then $0.10/GB | same; private network $0.01/GB |
| Support | Community | Billing support | Standard/Business/Production |

So the old "Launch $19/mo" is gone: Launch is pure usage-based with no base fee (plans page). No Business/Enterprise tier is listed; there is a forthcoming "Agent Plan".

**CU definition**: "Each CU allocates approximately 4 GB of RAM"; 0.25 CU = 1 GB RAM, 1 CU = 4 GB, 2 CU = 8 GB … 16 CU = 64 GB. Autoscaling range 0.25–16 CU. https://neon.com/docs/manage/computes

**Scale-to-zero / cold start**: suspends after 5 min inactivity; restart "within a few hundred milliseconds"; only computes up to 16 CU can scale to zero. https://neon.com/docs/introduction/scale-to-zero

**Read replicas**: same-region only ("Neon only supports creating read replicas in the same region as your database"); share storage ("No additional storage is required"); support autoscaling and scale-to-zero; Free plan max 3 replica computes/project; billed as compute ("Read replicas are separate computes and count toward CU-hours"). https://neon.com/docs/introduction/read-replicas, https://neon.com/pricing

**Branching**: copy-on-write, branches have dedicated compute, TTL/expiration supported. https://neon.com/docs/introduction/branching

**Regions** (https://neon.com/docs/introduction/regions): 8 AWS regions — us-east-1 (N. Virginia), us-east-2 (Ohio), us-west-2 (Oregon), **eu-central-1 (Frankfurt)**, eu-west-2 (London), **ap-southeast-1 (Singapore)**, ap-southeast-2 (Sydney), sa-east-1 (São Paulo). Azure regions (eastus2, westus3, gwc) are **deprecated: "You can no longer create new projects in Azure regions."** Region is fixed per project.

**Connecting from serverless**: `@neondatabase/serverless` driver over HTTP (one-shot queries, non-interactive `transaction()`) or WebSocket (full node-postgres compatibility); works on Vercel Edge/Cloudflare Workers/Node 19+. https://neon.com/docs/serverless/serverless-driver — PgBouncer pooler via `-pooler` hostname suffix, transaction mode, "up to 10,000 concurrent connections". https://neon.com/docs/connect/connection-pooling

**Vercel Marketplace**: listing shows only "Plans starting at $0" and links to neon.com pricing; "Billing is managed through Vercel". https://vercel.com/marketplace/neon — Neon docs: Vercel-managed integration "routes all billing through your Vercel invoice", you "pick a region & plan", and "Changing your plan affects **all databases** in this integration". Neither page states whether prices are identical to neon.com. https://neon.com/docs/guides/vercel-native-integration, https://neon.com/docs/guides/vercel-overview

**Databricks**: Neon blog (May 14, 2025): "Neon will be joining forces with Databricks after the transaction closes … Neon isn't going anywhere." https://neon.com/blog/neon-and-databricks — Databricks press release: https://www.databricks.com/company/newsroom/press-releases/databricks-agrees-acquire-neon-help-developers-deliver-ai-systems — Plans page lists "Databricks Support" as a higher-tier support option on Scale.

**My cost arithmetic for your load** (Launch rates): compute is always-on at 100k+ req/day, so 0.25 CU × 730 h = 182.5 CU-h ≈ $19.35/mo; 1 CU always on ≈ $77/mo; +5 GB storage ≈ $1.75. Free plan (100 CU-h/project) would not survive an always-on primary.

---

## 2. Supabase

**Plans** (https://supabase.com/pricing)

| | Free | Pro | Team |
|---|---|---|---|
| Price | $0 | $25/month | $599/month |
| Projects | 2 active (unlimited paused) | unlimited | unlimited |
| DB | 500 MB, "Shared CPU, 500 MB RAM" (Nano) | 8 GB disk/project incl., then $0.125/GB | same |
| Compute credits | — | $10/month (covers Micro) | $10/month |
| MAU (Auth) | 50,000 | 100,000, then $0.00325/MAU | same |
| Egress | 5 GB | 250 GB, then $0.09/GB | same |
| File storage | 1 GB | 100 GB, then $0.0213/GB | same |
| Edge Functions | 500,000 invocations | 2M, then $2 per 1M | same |
| Pausing | "After 1 week of inactivity" | "Never" | Never |
| Daily backups | not included | 7 days | 7 days |
| Log retention | 1 day (API/DB) | 7 days | 28 days |
| PITR add-on | — | $100/month per 7 days (~$100/7d, ~$200/14d, ~$400/28d) | same |
| Realtime | 200 conns, 2M msgs | 500 conns then $10/1000; 5M msgs then $2.50/M | same |
| Branching | — | $0.01344/branch/hour | same |
| Other | — | spend cap on by default, email support | SOC2/ISO 27001, priority support, read-only roles |

PITR detail page: https://supabase.com/docs/guides/platform/manage-your-usage/point-in-time-recovery

**Compute add-ons** (https://supabase.com/docs/guides/platform/manage-your-usage/compute + pricing page for specs)

| Size | $/hour | ~$/month | Spec |
|---|---|---|---|
| Nano | $0 | $0 | shared CPU, 500 MB RAM (Free) |
| Micro | $0.01344 | ~$10 | 2-core ARM (shared), 1 GB |
| Small | $0.0206 | ~$15 | 2-core ARM, 2 GB |
| Medium | $0.0822 | ~$60 | 2-core ARM, 4 GB |
| Large | $0.1517 | ~$110–111 (pricing page $110, docs ~$111) | 2-core ARM dedicated, 8 GB |
| XL | $0.2877 | ~$210 | 4-core, 16 GB |
| 2XL | $0.562 | ~$410 | 8-core, 32 GB |
| 4XL | $1.32 | ~$960 | 16-core, 64 GB |
| 8XL | $2.562 | ~$1,870 | 32-core, 128 GB |
| 12XL | $3.836 | ~$2,800 | 48-core, 192 GB |
| 16XL | $5.12 | ~$3,730 | 64-core, 256 GB |

Compute is billed hourly; "$10 in Compute Credits … cover one project running on the Micro/Nano Compute size". Disk (gp3): 8 GB incl. then $0.125/GB; 3,000 IOPS incl. then $0.024/IOPS; 125 MB/s incl. then $0.95/MB/s; io2 $0.195/GB + $0.119/IOPS. https://supabase.com/docs/guides/platform/compute-and-disk

**Read replicas**: "run on the same Compute size as the primary" at the same hourly rate; replica disk is 1.25x primary; "Compute Credits do not apply to Read Replica Compute". https://supabase.com/docs/guides/platform/manage-your-usage/read-replicas — Geo-routing of Data API GETs to nearest replica; async replication. https://supabase.com/docs/guides/platform/read-replicas

**Regions** (https://supabase.com/docs/guides/platform/regions): "General regions": East US (N. Virginia), Central EU (Frankfurt), Southeast Asia (Singapore) — but "General regions aren't yet supported for read replicas or management via the API." Specific regions (16 AWS) include eu-west-1 Ireland, eu-west-2 London, eu-west-3 Paris, **eu-central-1 Frankfurt**, eu-central-2 Zurich, eu-north-1 Stockholm, us-east-1, us-east-2, us-west-1/2, **ap-southeast-1 Singapore**, ap-south-1, ap-northeast-1/2, ap-southeast-2, ca-central-1, sa-east-1.

**Connection from serverless** (https://supabase.com/docs/guides/database/connecting-to-postgres): direct 5432 (IPv6; IPv4 add-on), Supavisor session mode 5432, Supavisor transaction mode 6543 ("ideal for serverless or edge functions"), dedicated PgBouncer (paid plans, 6543), Data API REST/GraphQL. Shared pooler "is IPv4-only on every project tier". No scale-to-zero on paid plans: compute is always-on, so no cold start.

**Auth**: JWT Signing Keys (asymmetric), email/social/magic link/phone, MFA, custom OIDC, SAML SSO — all GA. https://supabase.com/docs/guides/getting-started/features

**Edge Functions limits** (https://supabase.com/docs/guides/functions/limits): 256 MB memory; wall clock **150 s Free / 400 s paid**; CPU time 2 s; request idle timeout 150 s; function size 20 MB (CLI bundle) / 5 MB (server bundle); functions per project 100 Free / 1,000 Pro / 2,000 Team; ports 25/587 blocked. Streaming: `ReadableStream`/SSE responses are documented (https://supabase.com/docs/guides/functions/ai-models) and for long streams the docs recommend `EdgeRuntime.waitUntil(upstream.body.pipeTo(writable))` to avoid early worker retirement (https://supabase.com/docs/guides/troubleshooting/edge-functions-worker-timeouts-and-websocket-drops). WebSockets in/out supported since Dec 3, 2024. https://supabase.com/blog/edge-functions-background-tasks-websockets

**Cron**: built on `pg_cron`; "from every second to once a year"; recommends ≤8 concurrent jobs, each ≤10 minutes; can call Edge Functions via HTTP (pg_net). Cron page does not state pricing. Status "Beta" on the features page. https://supabase.com/docs/guides/cron

**Queues**: built on `pgmq`; exactly-once delivery within visibility window; dashboard management; status "Public Alpha". https://supabase.com/docs/guides/queues, https://supabase.com/docs/guides/getting-started/features

**Studio as admin UI**: Table Editor ("Create tables and relationships, and edit rows from the Dashboard"), SQL Editor, CSV import (https://supabase.com/docs/guides/database/overview); Visual Schema Designer, Policy Templates, Security/Performance Advisor (features page). No official statement about non-developer use; read-only / project-scoped roles are a Team-plan ($599) feature. `https://supabase.com/features/table-editor` returned 404.

**My cost arithmetic**: Pro $25 with Micro covered by credits = $25/mo; Small = $25 + ~$5 = ~$30; + PITR 7d $100 if wanted. One Frankfurt-specific-region primary + one us-east-1 Small replica ≈ +$15 + disk.

---

## 3. Turso / libSQL

**Plans** (https://turso.tech/pricing — page has a Monthly/Yearly toggle; the fetched view showed these prices and did not separately show the other billing period, so treat the odd figures like $24.92 as possibly annual-discounted)

| | Free | Developer | Scaler | Pro |
|---|---|---|---|---|
| Price | $0 | $4.99/mo | $24.92/mo | $416.58/mo |
| Databases | unlimited | unlimited | unlimited | unlimited |
| Storage | 5 GB | 9 GB (+$0.75/GB) | 24 GB (+$0.50/GB) | 50 GB (+$0.45/GB) |
| Rows read/mo | 500M | 2.5B (+$1/B) | 100B (+$0.80/B) | 250B (+$0.75/B) |
| Rows written/mo | 10M | 25M (+$1/M) | 100M (+$0.80/M) | 250M (+$0.75/M) |
| Syncs | 3 GB | 10 GB (+$0.35/GB) | 24 GB (+$0.25/GB) | 100 GB (+$0.15/GB) |
| PITR | 1 day | 10 days | 30 days | 90 days |

The "hobby plan will have its price dropped to $4.99/month" and edge replicas were discontinued for new users on Jan 21, 2025; platform moved AWS-only, "which has no cold starts". https://turso.tech/blog/upcoming-changes-to-the-turso-platform-and-roadmap

**Regions**: `https://docs.turso.tech/cloud/locations` and `/cli/group/locations` returned 404. The only official list I could fetch is the API reference example: aws-ap-northeast-1 (Tokyo), aws-ap-south-1 (Mumbai), **aws-eu-west-1 (Ireland)**, aws-us-east-1, aws-us-east-2, aws-us-west-2. **Frankfurt is not confirmed anywhere I could fetch.** https://docs.turso.tech/api-reference/locations

**Embedded replicas**: local file reads in microseconds, writes go to cloud primary; SDKs TS, Go, Rust, PHP, Python (`libsql`), Flutter; **"In certain contexts, such as serverless environments without a filesystem, you can't use embedded replicas"**; Turso Sync recommended for new projects. https://docs.turso.tech/features/embedded-replicas/introduction

**Connection from serverless**: HTTP API `https://[db]-[org].turso.io`, `POST /v2/pipeline`, Bearer token, optional `baton` for connection reuse. https://docs.turso.tech/sdk/http/reference — Python: `turso_serverless` for remote, `libsql` for embedded replicas. https://docs.turso.tech/sdk/python/quickstart

**Postgres compatibility**: blog July 16, 2026: "we will write a modern version of Postgres, in Turso (which is itself written in Rust)"; "today this is a foundation, not a finished product"; will include wire protocol + server; "compatible enough … but not really 100%". No cloud availability or date stated. https://turso.tech/blog/a-new-modern-version-of-postgres-in-rust

---

## 4. Cloudflare D1

**Pricing** (https://developers.cloudflare.com/d1/platform/pricing/, https://developers.cloudflare.com/workers/platform/pricing/)

| | Workers Free | Workers Paid ($5/mo minimum) |
|---|---|---|
| Rows read | 5M/day | 25B/mo incl., then $0.001/M |
| Rows written | 100k/day | 50M/mo incl., then $1.00/M |
| Storage | 5 GB total | 5 GB incl., then $0.75/GB-mo |

Rows are counted as scanned, not returned ("an unindexed column filter scans all rows"); index writes count as extra row writes; no egress fees; read replication has no extra cost. **Changelog: "Beginning September 1, 2026, D1 queries on the Workers Free plan will fail when an account exceeds the daily row read or row write limits."** https://developers.cloudflare.com/changelog/?product=d1

**Limits** (https://developers.cloudflare.com/d1/platform/limits/): databases 10 Free / 50,000 Paid; max DB size **500 MB Free / 10 GB Paid**; 1 TB per account (Paid); queries per Worker invocation 50 Free / 1,000 Paid; **max query duration 30 s**; statement 100 KB; 100 bound params; 100 columns/table; 2 MB row; Time Travel 7 days Free / 30 days Paid; each DB is single-threaded (~1,000 q/s at 1 ms each).

**Read replication** (https://developers.cloudflare.com/d1/best-practices/read-replication/, updated Aug 10, 2026): no "beta" label on the docs page (the April 10, 2025 launch post called it "public beta": https://blog.cloudflare.com/d1-read-replication-beta/). Enable via dashboard or REST (`read_replication.mode: auto`); replicas auto-created in ENAM, WNAM, WEUR, EEUR, APAC, OC (so **EU covered**); **sequential consistency** via Sessions API (`withSession("first-primary" | "first-unconstrained" | bookmark)`); no extra cost. **"Sessions API is only available via the D1 Worker Binding and not yet available via the REST API."**

**Access outside Workers**: REST `POST /accounts/{account_id}/d1/database/{database_id}/query` with `Authorization: Bearer <token>`, `sql` + `params`, needs D1 Read/Write permission. https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/ — For a Python FastAPI backend this REST path (no Sessions API, no replicas) is the only route; the Workers binding is the first-class one.

**My cost arithmetic**: 45M queries/mo × few rows each is far below 25B reads; 500k writes/day = 15M/mo < 50M → effectively $5/mo. Risk is the 10 GB cap and rows_read on unindexed scans.

---

## 5. PlanetScale (Postgres)

**Status**: "PlanetScale for Postgres is now generally available and out of private preview" (Sept 22, 2025); "from $5/month". https://planetscale.com/blog/planetscale-for-postgres-is-generally-available

**Pricing** (https://planetscale.com/pricing, AWS us-east-1; "Actual prices vary by cloud provider and region"): **no free / hobby / trial tier is listed.**

| Postgres SKU | RAM / vCPU | HA 3-node (ARM / x86) | Single-node |
|---|---|---|---|
| PS-5 | 512 MiB / 1/16 | $15 / $15 | $5 |
| PS-10 | 1 GiB / 1/8 | $30 / $39 | ~1/3 of HA |
| PS-20 | 2 GiB / 1/4 | $50 / $59 | |
| PS-40 | 4 GiB / 1/2 | $83 / $99 | |
| PS-80 | 8 GiB / 1 | $148 / $179 | |
| PS-160 | 16 GiB / 2 | $286 / $349 | |
| Metal M-10 | 10 GiB NVMe incl. | $50 arm64 / $60 x86 | |

Storage (EBS), backups and egress are billed separately; the page gives no per-GB rates.

**Regions** (https://planetscale.com/docs/concepts/regions): AWS **eu-central-1 Frankfurt (`eu-central`)**, eu-west-1 Dublin, eu-west-2 London, us-east-1, us-east-2 (default), us-west-2, **ap-southeast-1 Singapore**, ap-northeast-1, ap-south-1, ap-southeast-2, ca-central-1, sa-east-1; GCP us-central1, us-east4, us-east1, northamerica-northeast1, asia-northeast3, europe-west1 Belgium, europe-west4 Netherlands. Same for Vitess and Postgres; region cannot be changed.

**Connection**: port 5432 direct, port 6432 via PgBouncer ("All PlanetScale Postgres databases include a local PgBouncer instance"), SSL required; for serverless "the Neon serverless driver over HTTP or WebSockets" is supported. https://planetscale.com/docs/postgres/connecting — Always-on clusters, no scale-to-zero.

---

## 6. Railway Postgres

**Pricing** (https://railway.com/pricing): Free $0 (+$1 usage credit, max 1 vCPU/0.5 GB), Hobby $5/mo incl. $5 credit, Pro $20/workspace incl. $20 credit. Usage: CPU $0.00000772/vCPU-s (~$20/vCPU-month), memory $0.00000386/GB-s (~$10/GB-month), volumes $0.00000006/GB-s (~$0.15/GB-month), egress $0.05/GB.

**Postgres** (https://docs.railway.com/guides/postgresql): template on Railway's `postgres-ssl` image; private network by default; enabling "Public Access" creates a TCP proxy and "you will be billed for Network Egress"; HA via Patroni/etcd/HAProxy template; native Backups feature. No pooler/HTTP driver included — you bring PgBouncer yourself.

**Regions** (https://docs.railway.com/reference/regions): us-west2 California, us-east4 Virginia, **europe-west4 Amsterdam**, asia-southeast1 Singapore (all "Metal"). No Frankfurt.

**Scale-to-zero**: Serverless/app-sleeping applies to services (sleep after 5–10 min of no outbound traffic, cold boot delay, first request may 502); a DB with open connections stays up, so Postgres is effectively always-on. https://docs.railway.com/reference/app-sleeping

---

## Upstash Redis (brief)

Free: 256 MB, 500K commands/mo, 10 GB bandwidth. Pay-as-you-go: $0.2 per 100K commands, $0.25/GB storage (first 1 GB free), bandwidth free to 200 GB then $0.03/GB. Fixed: 250 MB $10/mo (+$5 per read region), 1 GB $20 (+$10), 5 GB $100 (+$50), 10 GB $200, 50 GB $400, 100 GB $800, 500 GB $1,500, unlimited commands; Prod Pack +$200/mo. https://upstash.com/pricing/redis — Regions include AWS **eu-central-1 Frankfurt**, eu-west-1, eu-west-2, us-east-1, ap-southeast-1 (+ GCP europe-west1); global DB = primary + async read replicas (eventual consistency), replicated writes count as commands. https://upstash.com/docs/redis/features/globaldatabase — Vercel Marketplace listing shows Redis with "Free, Pay as You Go, Fixed" plans but no numbers. https://vercel.com/marketplace/upstash

---

## Quick comparison for your case

| | EU region | Serverless connect | Scale-to-zero / cold start | Realistic monthly cost (my arithmetic from listed rates) |
|---|---|---|---|---|
| Neon | Frankfurt, London | HTTP/WS driver + PgBouncer | yes, ~few hundred ms; disable on Launch | ~$20–80 (0.25–1 CU always-on, Launch) |
| Supabase | Frankfurt (+5 more EU) | Supavisor 6543 / PgBouncer / REST | none on Pro (always-on) | $25 (Micro) – $30 (Small) + $100 PITR optional |
| Turso | only Ireland confirmed | HTTP `/v2/pipeline` | AWS "no cold starts" | $0–$5 (Free/Developer) |
| D1 | WEUR/EEUR replicas | Workers binding; REST without Sessions | n/a | ~$5 (Workers Paid) |
| PlanetScale | Frankfurt, Dublin, London | PgBouncer 6432 / Neon driver | none | $15 (PS-5 HA) – $50 (M-10) |
| Railway | Amsterdam only | TCP (self-managed pooler) | none for DB | ~$5–30 |

Gaps I could not close: Turso full region list (docs 404), exact Neon plan table inside the Vercel Marketplace (not shown on the listing), Supabase Cron pricing (page silent), PlanetScale per-GB storage/backup/egress rates (page silent).
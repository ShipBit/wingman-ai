text
Wayback is blocked from this environment, so I'm stopping here. Everything else I need is in hand; below is the report with gaps flagged explicitly.

# Admin panel + monitoring options — researched 2026-09-09

Method: every number below comes from a live WebFetch of the cited URL today. Where a page could not be fetched, was JS-rendered without numbers, or geo-localized to EUR, I say so. WebSearch was used only to locate URLs (the session's search budget ran out midway; only fetches after that).

## Quick verdict

| Question | Answer |
|---|---|
| Cheapest for 2–3 admins | $0 in several ways: **Retool Free** (cloud, "Up to 5 users"), **Appsmith Free** (cloud, "Up to 5 users"), **Directus Core self-hosted** (3 user seats — exactly fits; or the Open Innovation Grant lifts all caps if you're <$5M revenue and <50 employees), **SQLAdmin** (BSD-3, runs inside your FastAPI process), **Budibase self-hosted** (unlimited users). |
| Least build effort | **Directus** (auto-generated admin UI + REST/GraphQL + no-code dashboards over your existing Postgres) or **Retool** (drag-and-drop over SQL queries; charts included). **SQLAdmin** is the least-effort path for a Python team for CRUD tables, but it has no charts. |
| Build-your-own on Vercel | Costs nothing extra on an existing Pro team: **Vercel Authentication** is on all plans, protecting *production* needs Pro, and read-only **Viewer seats are free**. **Password Protection** is the $150/mo add-on — you don't need it. **Cloudflare Access** is the alternative: free for up to 50 users. |
| Cheapest monitoring stack | **Sentry Developer** (free, 1 user) or **Team $26/mo** annual (unlimited users) + **Better Stack Free** (10 monitors, 30-s checks, 1 status page, unlimited phone/SMS) + **Axiom Personal** (500 GB/mo free) → $0–26/mo. |
| Highlight.io | Gone as a standalone product. `highlight.io/pricing` now 308-redirects to `launchdarkly.com`. Successor is LaunchDarkly Observability (free Developer tier: 5K errors, 5K replays, 10M logs, 10M traces per month). |

---

## Part A — Admin panel options

### 1. Retool (cloud)
Source: https://retool.com/pricing (fetched; page geo-localized to **EUR**; a monthly/annual toggle exists but only annual prices were extractable).

| Plan | Price (annual, as shown) | Notes |
|---|---|---|
| Free | €0 per builder, €0 per internal user | "Up to 5 users", 250 AI credits/mo |
| Team | **€9/mo per builder** + **€5/mo per internal user** | 1,000 AI credits/mo |
| Business | **€46/mo per builder** + **€14/mo per internal user** | External users: 0–50 free, 51–250 €7.33/mo, 251–500 €5.41/mo, >500 €3.60/mo |
| Enterprise | Custom ("Get pricing") | |

- User types (quoted from the page): "Builders are explicitly assigned by admins and can create, edit, and publish apps, workflows, and agents. Internal users are employees who use apps but don't publish changes."
- **USD (third-party, not Retool's own page):** https://www.totalum.app/blog/retool-pricing-2026 (dated 2026-09-02) states Team **$10 builder / $5 internal user** annual ($12 / $7 monthly), Business **$50 builder / $15 internal** annual ($65 / $18 monthly), Free "Up to 5 users". This matches your assumptions ($10/$5, $50) but I could not confirm USD from an official Retool page: `docs.retool.com/org-users/concepts/pricing`, `/billing`, `/user-types` and `retool.com/pricing/faq` all returned **404**, and `retool.com/pricing?currency=USD` still rendered EUR.
- For 2–3 admins: **Free tier ($0)** as long as you stay ≤5 users total.

### 2. Appsmith
Source: https://www.appsmith.com/pricing

| Plan | Price | Limits |
|---|---|---|
| Free | $0 | "Up to 5 users for cloud", 5 workspaces, "3 repos" Git, Google SSO, "3 standard roles for access control", community support |
| Business | **"$15 / Month per user"** | "Up to 99 users", unlimited environments/repos/workspaces, custom roles, audit logs, workflows, remove branding |
| Enterprise | **"$2,500 / Month for 100 users"** | SAML/OIDC SSO, SCIM, airgapped edition add-on |

- Self-hosted Community edition: the pricing page calls it an "open-source low code application platform, available for free". The "Up to 5 users" cap is explicitly labelled "for cloud"; **the page does not state a user limit for self-hosted Community** (I could not find a docs page that does — `docs.appsmith.com/product/plans-and-billing`, `/product/plans` and `appsmith.com/community-edition` all 404). GitHub README (https://github.com/appsmithorg/appsmith) describes it as "an open-source low-code platform" and links a LICENSE file; the license text itself was not in the fetched content, so I cannot quote "Apache 2.0" from a fetched source.
- For 2–3 admins: **Free cloud ($0)** or self-hosted.

### 3. Directus
**Your assumed numbers (Starter $15 / Professional $99 / BSL) are outdated.** `directus.io/pricing` 301-redirects to https://directus.com/pricing.

| Tier | Price | Included |
|---|---|---|
| Core | **$0** | "3 user seats, 25 Collections, 5 Flows, AI Assistant, Advanced RBAC", community support |
| Team | **$499/mo (annual) or $599/mo (rolling)** | "10 SSO seats, 50 Collections, 20 Flows, Granular RBAC, Basic Support" |
| Enterprise | Custom | "Custom SSO seats, Custom Collections, Unlimited Flows, SSO (SAML / OIDC)" |

- Hosting: "Self-hosting is available on every tier. Directus Cloud is an optional add-on at $99/mo for Core and Team." (https://directus.com/pricing)
- **Open Innovation Grant:** "under $5M in annual revenue and fewer than 50 employees" → self-hosted with "no feature limits. No artificial caps." at no software cost, or cloud hosting at $99/mo. (https://directus.com/pricing)
- License: no longer BSL. It is the **"Monospace Sustainable Core License (MSCL) 1.0"**, "a source-available license derived from the Fair Core License" (https://github.com/directus/directus README). README also states: "Organizations under $5M in annual revenue and 50 employees can use Directus for free under the Open Innovation Grant" and "Organizations above those thresholds using advanced or enterprise features require a commercial license"; "A free tier is available to everyone". The license text (https://directus.com/mscl — `directus.io/bsl` redirects here) restricts "Competing Use" and converts to GPL-3.0 "effective on the fourth anniversary" of each release. **The MSCL text itself contains no dollar threshold** — the $5M/50-employee rule lives on the pricing page/README, not in the license.
- Features (https://directus.com/features): "Layer Directus on top of your existing data… use your existing database structure", "Support for any SQL database", REST ("familiar RESTful principles") and GraphQL APIs, "Visual workflow automation" (Flows), "No code dashboards" (Insights), "Granular permissions and access control".
- For 2–3 admins: **Core self-hosted, $0, 3 seats** — or Grant for no caps. This is the closest to "zero code" for tables + filters + charts over your Postgres.

### 4. Supabase Studio as admin panel
- Pricing (https://supabase.com/pricing): Free $0; Pro "from $25/month" incl. "$10/month in compute credits"; Team "from $599/month"; Enterprise custom. **"Team members | Unlimited | Unlimited | Unlimited | Unlimited"** — no per-seat charge on any plan.
- Roles (https://supabase.com/docs/guides/platform/access-control): Owner ("full access"), Administrator (full "except updating organization settings, transferring projects… and adding new owners"), Developer ("read-only access to organization resources and content access to project resources but cannot change any project settings"), Read-Only. **"Read-Only role is only available on the Team and Enterprise plans."** **"Project scoped roles are only available on the Team and Enterprise plans."**
- Studio features (https://supabase.com/docs/guides/database/overview): "Table Editor" for visual work with the database; "SQL Editor" for "ad-hoc queries and saved snippets". No charting/report feature was mentioned on that page.
- Verdict: usable as a *database* admin panel at $0 extra if your Postgres is already on Supabase (Developer role = can edit rows, can't change settings). No per-table permissions on Pro, no custom charts. Not viable if your DB is elsewhere.

### 5. Build-your-own: SvelteKit + shadcn-svelte on Vercel
Source: https://vercel.com/docs/plans/pro-plan and https://vercel.com/docs/deployment-protection (both fetched; docs last updated 2026-09-02 / 2026-08-28).

- Pro: "$20/month Pro platform fee — 1 deploying team seat included — $20/month in usage credit"; additional Owner/Member seats "$20/month each"; **"Unlimited free Viewer seats with read-only access"** (Viewers can "access project deployments" and comment on previews but not deploy).
- Hobby: "for personal, non-commercial use" (FAQ on https://vercel.com/pricing).
- Deployment Protection:
  - **Vercel Authentication — "Available on all plans"**. Scope "Standard Protection" (everything except production domains) on all plans; scope **"All Deployments" (incl. production) "Available on Pro and Enterprise plans"**. Hobby note: "your production domain remains publicly accessible. To protect production domains, you need a Pro or Enterprise plan."
  - **Password Protection — "Available on the Enterprise plan, or as a paid add-on for Pro plans"**: the "Advanced Deployment Protection" add-on is **$150 per month** (also unlocks Private Production Deployments and Deployment Protection Exceptions; minimum 30 days before you can cancel).
  - Trusted IPs and Passport (SSO) — Enterprise only.
- **So on Pro:** put the admin panel in its own project, set protection to "All Deployments" + Vercel Authentication, add the 2–3 admins as free Viewer seats → $0 on top of the Pro fee. You still write your own auth if you want app-level roles.
- **Cloudflare Access (Zero Trust)** as the alternative gate: https://www.cloudflare.com/zero-trust/products/access/ lists **Free "$0 forever"** with a **50-user limit**, **Pay-as-you-go "$7 per user/month (paid annually)"**, and Contract (custom). The plans page you asked for (https://www.cloudflare.com/plans/zero-trust-services/) was fetched but its comparison table is JS-rendered and returned no numbers — the figures above come from the Access product page. Seat semantics (https://developers.cloudflare.com/cloudflare-one/identity/users/seat-management/): "A user consumes a seat when they perform an authentication event"; once out of seats, "additional users who attempt to log in are blocked".

### 6. Briefly
- **Budibase** (https://budibase.com/pricing/): Free open-source **self-hosted only**: "Unlimited apps", "Unlimited users", 1 workspace. Cloud: Pro **$19/mo** (1 creator, 5K actions), Premium **$49/mo** (1 creator, 10 workspaces, SSO), Business **$299/mo** (3 creators); extra creators "$50/creator/mo", "End users for $5/user/mo"; Enterprise custom.
- **Refine** (https://github.com/refinedev/refine): React meta-framework for admin panels/CRUD, "Licensed under the MIT License" — core is free. The paid items on https://refine.dev/pricing/ are the hosted "Refine AI" builder (Starter $0.99/mo for 300 credits, Pro $20.00/mo for 1,500 credits), not the framework. React, not Svelte — a mismatch for your stack.
- **SQLAdmin** (https://github.com/aminalaee/sqladmin): admin UI for SQLAlchemy models, "BSD-3-Clause license", works with FastAPI/Starlette, sync/async SQLAlchemy and SQLModel, optional session-based `auth` backend. Free, Python-native, lowest effort for CRUD tables; no charts.

---

## Part B — Monitoring

### 1. Sentry
Source: https://sentry.io/pricing/ (page shows annual prices "When billed annually with default pre-paid data"; the monthly-billing toggle is JS and its numbers were not extractable — flagging that $29/$89 monthly could not be verified).

| Plan | Price | Included per month |
|---|---|---|
| Developer | Free, **"Limited to one user"** | 5k errors, 50 replays, 5M spans, **1 cron monitor, 1 uptime monitor** |
| Team | **$26/mo** (annual) | "Unlimited users", 50k errors, 50 replays, 5M spans, 1 cron, 1 uptime |
| Business | **$80/mo** (annual) | Unlimited users, 50k errors, 50 replays, 5M spans, 1 cron, 1 uptime |
| Enterprise | Custom | |

- Pay-as-you-go: cron "+$0.78/monitor additional", uptime "+$1.00/uptime alert additional", logs/metrics "+$0.50/GB". https://docs.sentry.io/pricing/ confirms paid plans include "50k errors, 5GB logs, 5GB application metrics, 5M spans, 50 replays, 1 uptime monitor, 1 cron monitor" and lists error overage tiers (e.g. $0.00015/error on Team in the >500k–10M band).
- FastAPI SDK (https://docs.sentry.io/platforms/python/integrations/fastapi/): "If you have the `fastapi` package in your dependencies, the Sentry FastAPI integration will be enabled automatically"; requires FastAPI ≥ 0.79.0; captures "all exceptions leading to an Internal Server Error", plus tracing of middleware, DB queries, Redis.
- Cron monitoring is a product feature on all plans (https://docs.sentry.io/product/crons/); Uptime monitoring checks at 1/5/10/20/30/60-minute intervals (https://docs.sentry.io/product/uptime-monitoring/).
- Caveat for you: the Developer plan is 1 user, so 2–3 devs sharing a project means Team at $26/mo.

### 2. Better Stack
Sources: https://betterstack.com/pricing and https://betterstack.com/uptime/pricing

- **Uptime Free:** "10 monitors & heartbeats", **"Up to 30 seconds check frequency"** (not 3 min), "1 status page", "Slack & e-mail alerts", **"Unlimited phone call alerts" and "Unlimited SMS"**; team members with telemetry access at no cost.
- **Paid model:** per **Responder $34/mo (monthly) or $29/mo (yearly)** ("Uptime + Telemetry" seat). Add-ons: "Additional 50 monitors" $25/mo ($21 yearly); "Additional 10 heartbeats" $20/mo ($17 yearly).
- **Status pages:** "1 status page included", "1,000 subscribers included"; "Additional public status page" $15/mo ($12 yearly); +1,000 subscribers $40/mo; premium features (custom CSS, white-label, auth, SSO) $15–$250/mo.
- **Telemetry/Logs Free:** **"3 GB per month retained for 3 days"**. Pay-as-you-go: ingestion $0.10/GB (EU), $0.15/GB (US), $0.35/GB (Singapore); retention $0.05/$0.08/$0.18 per GB-month. Bundles from Nano "$30/mo" (EU) to Tera "$500/mo" (US).

### 3. Axiom
Source: https://axiom.co/pricing

- **Personal (free):** $0, "500 GB / mo" ingest, "10 GB-hours / mo" query compute, "25 GB" storage, "30-day retention", community support.
- **Axiom Cloud:** **"$25/month"** platform fee + usage; includes "1 TB / mo" ingest, "100 GB-hours / mo" compute, "100 GB" storage, configurable retention, "Automatic volume discounts". Self-serve add-ons: SSO (SAML) $100/mo, RBAC $50/mo, Audit Logs $50/mo, Directory Sync $100/mo.
- OpenTelemetry: "OTel, Vector, CloudWatch, AWS, Kubernetes, CI/CD" integrations on all plans.

### 4. Highlight.io → LaunchDarkly
- **Status:** https://www.highlight.io/pricing returns a **308 Permanent Redirect to https://launchdarkly.com/**; there is no Highlight pricing page anymore. The migration blog (https://nodejs.highlight.io/blog/launchdarkly-migration) also 308-redirects to launchdarkly.com.
- **Acquisition:** announced on the LaunchDarkly blog April 21, 2025 (https://launchdarkly.com/blog/welcome-highlight-to-launchdarkly/) and by press release April 23, 2025 (https://www.globenewswire.com/news-release/2025/04/23/3066295/0/en/launchdarkly-acquires-highlight-to-advance-the-future-of-guarded-software-releases.html): "error monitoring, logging, distributed tracing and session replay", co-founders joined LaunchDarkly.
- **Sunset date — partially verified:** the search-result snippet of the (now redirecting) Highlight migration post stated hosted services would be "deprecating… on February 28, 2026" and customers must switch SDK snippets "before March 1, 2026". I could not fetch that text directly (redirect; web.archive.org is blocked from this environment), so treat the exact dates as snippet-only. The redirect itself confirms the hosted product is gone as of today.
- **Open source:** https://github.com/highlight/highlight is not archived and its README carries no deprecation notice; the self-hosted repo still exists.
- **Successor pricing** (https://launchdarkly.com/pricing/): Developer **$0 forever** — "10M logs and 10M traces /mo", "5K session replays and 5K errors /mo", 14-day retention. Foundation (pay-as-you-go, yearly billing) — same included amounts, 30-day retention; Enterprise custom, "100+ days". **Per-unit overage prices are not disclosed on the page.**

### 5. One-liners
- **UptimeRobot** (https://uptimerobot.com/pricing/): Free **"50 monitors"**, **"5 min. monitoring interval"**, 1 status page. Solo €9/mo annual (€10 monthly): 10 monitors, 60-s interval, 3 status pages; Team €35/€41: 100 monitors, 30 s, 100 status pages; Scale €65/€77: 200–500 monitors, 15 s, unlimited status pages. **Page geo-localized to EUR; USD not obtainable** (`?currency=USD` variants still showed €).
- **Cloudflare Health Checks** (https://developers.cloudflare.com/health-checks/): availability "Free | Pro | Business | Enterprise — No | Yes | Yes | Yes"; included checks **Pro 10, Business 50, Enterprise 1,000**. So yes, Pro+ includes standalone health checks; Free does not. The Pro/Business plan prices could not be fetched (https://www.cloudflare.com/plans/ and the Pro/Business sub-pages render without prices).
- **Vercel Observability Plus** (https://vercel.com/docs/observability/observability-plus): **not $10/mo** — it is usage-based at **"$1.20 per 1 million events"**, Paid Pro and Enterprise only, 30-day retention (vs 1 day on base Pro), enabled by default for teams upgraded on/after April 3, 2026. The $10/mo figures on https://vercel.com/docs/plans/pro-plan are **Web Analytics Plus $10/month** and **Speed Insights Plus $10/month per project** (+$0.65 per 10k events).
- **Grafana Cloud Free** (https://grafana.com/pricing/): "10k active series", "50 GB" logs, "50 GB" traces, "50 GB" profiles, "14 days retention", "3 active users", "3 active IRM users", Synthetics "100k API test executions & 10k browser test executions per month", k6 "500 virtual user hours". Pro: **$19/month** platform fee + usage (users "$8.00 / active user", metrics "$6.50 / 1k series", logs "$0.050/GB Process, $0.400/GB Write, $0.100/GB Retain").

---

## Could not verify (explicit)
- Retool **USD** prices from an official Retool page (site serves EUR; docs/FAQ URLs 404). Third-party USD figures given above.
- Retool and Sentry **monthly-billing** prices (JS toggles; only annual extracted).
- Appsmith **self-hosted Community user limit** (not stated on pricing page; docs pages 404).
- Cloudflare **Zero Trust plans comparison page** numbers (JS-rendered) — Free 50 users / $7 PAYG taken from the Access product page instead.
- Cloudflare **Pro/Business site-plan prices** (pages render without prices).
- Highlight.io **exact sunset dates** (source now redirects; archive blocked).
- UptimeRobot **USD** prices (geo-localized to EUR).
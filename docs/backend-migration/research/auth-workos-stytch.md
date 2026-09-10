text
Research complete. Below is the full report (all facts from live fetches/searches in this session; nothing from memory). Note: the session's shared WebSearch budget ran out partway through, so the later part relies on direct WebFetch of official URLs; where a page 404'd or didn't contain the fact, it's marked "NOT FOUND / could not fetch".

---

# WorkOS AuthKit

## 1. Pricing

**Pricing page has no date/version stamp** ("The page contains no last-updated timestamp or version information") (https://workos.com/pricing). A third-party guide states the same numbers "as published by WorkOS (July 2026)" (https://idsync.com/guides/workos-pricing — third party).

**Free MAU claim, exact wording:** "First 1M MAUs" → "Free"; "Each additional 1M MAUs" → "$2,500/mo" (https://workos.com/pricing; identical wording at https://workos.com/pricing.md).

**What AuthKit includes (exact):** "email + password, social login, passkeys, MFA, magic auth, and enterprise SSO" with no separate charge listed for these (https://workos.com/pricing.md). So social logins (Google/GitHub/Microsoft/Apple) and MFA are part of the free tier per the pricing page; the social-login docs page itself "contains no information about whether social login incurs additional costs" (https://workos.com/docs/authkit/social-login).

**Add-ons / extras (exact tier text):**

| Item | Price |
|---|---|
| SSO connections 1–15 | "$125/ea" (per month) |
| SSO 16–30 / 31–50 / 51–100 | "$100/ea" / "$80/ea" / "$65/ea"; 101+ "Custom pricing via sales contact" |
| Directory Sync | "Same tiered pricing as SSO" |
| Custom Domain | "$99/mo" |
| Audit Logs | "$125/mo" per SIEM connection (log streaming); "$99/mo per 1M events" retained |
| Radar (bot/fraud) | "First 1,000 checks free; '$100/mo' per 50K additional checks" |
| Scale support | "$1,000/mo"; Enterprise custom |

(https://workos.com/pricing and https://workos.com/pricing.md). Third-party adds a "$50 (101–200)" tier and "custom at 201+" (https://idsync.com/guides/workos-pricing — third party).

- **RBAC:** pricing page silent — "lacks information on ... RBAC" (https://workos.com/pricing.md); RBAC docs mention "Seamless integration with AuthKit" but "No pricing information" (https://workos.com/docs/rbac). NOT FOUND as a priced item.
- **Email sending:** staging sends from `workos.dev`; production "from `workos-mail.com` by default" with "best-effort" delivery; custom sending domain set up via 3 CNAMEs (https://workos.com/docs/custom-domains/email). Custom domains are "a paid service" covering "Email, AuthKit, Admin Portal, Authentication API" (https://workos.com/docs/custom-domains) → the $99/mo Custom Domain line.
- **Custom auth domain:** default hosted domain is "a randomly generated phrase plus the domain `authkit.app`" e.g. `youthful-ginger-43.authkit.app` (https://workos.com/docs/custom-domains/authkit).
- **Radar SMS:** "SMS usage is billed at cost — WorkOS does not up-charge"; Radar must be enabled in dashboard (https://workos.com/docs/radar).
- **Minimum commitment:** none found on pricing page; "No minimum commitment mentioned" (https://idsync.com/guides/workos-pricing — third party).
- **2025/2026 pricing changes:** WorkOS changelog (fetched) shows no pricing/free-tier entries (https://workos.com/changelog). Sacra reports the same "free for the first 1 million MAU, then $2,500 per additional million" with data through Dec 2025 (https://sacra.com/c/workos/ — third party). No evidence of a change.
- **MAU definition:** NOT FOUND on the pricing page text.

**Estimated monthly cost (WorkOS):**

| MAU | Base | Realistic w/ custom domain (needed for prod client-only cookies + branded email) |
|---|---|---|
| 1,000 | $0 | $99 |
| 5,000 | $0 | $99 |
| 10,000 | $0 | $99 |
| 25,000 | $0 | $99 |

(Radar optional: first 1,000 checks free, then $100/mo per 50K.)

## 2. Social login providers

Documented list: **Google, Microsoft, GitHub, Apple, GitLab, LinkedIn, Slack, Xero**; "Not mentioned: Discord, Twitch, Steam, X/Twitter, or Figma" (https://workos.com/docs/authkit/social-login). The authorization-URL enum also shows `"authkit"`, `"AppleOAuth"`, `"BitbucketOAuth"`, `"GoogleOAuth"`, `"MicrosoftOAuth"`, `"GitHubOAuth"` (https://workos.com/docs/reference/authkit/authentication/get-authorization-url).

- Email/password, "Magic Auth", MFA, passkeys: listed in pricing (https://workos.com/pricing.md) and product page (https://www.authkit.com/). Whether Magic Auth is link vs OTP: NOT FOUND in fetched pages.
- **Custom OAuth/OIDC:** a search snippet from the WorkOS blog says "WorkOS allows you to set up a generic OIDC connection to support a wider range of providers, like Dropbox or Reddit" (https://workos.com/blog/social-logins — search snippet, page not fetched). This is an SSO "connection", which per pricing is $125/connection/mo — verify before relying on it for Discord/Steam/Twitch.
- Steam: not an OAuth/OIDC provider in any WorkOS page found.

## 3. Desktop app support

- **Official Electron SDK** `@workos/authkit-electron` (blog dated Aug 13, 2026): "PKCE with sealed CSRF state", redirect `workos-auth://callback`, "You do not need an API key. This library treats your desktop app as a public OAuth client", refresh token "encrypted at rest with Electron's `safeStorage`" (https://workos.com/blog/add-authentication-to-your-electron-app-in-three-calls; https://github.com/workos/authkit-electron — Electron ≥ 30, no Tauri mention).
- Older example `electron-authkit-example` uses `@workos-inc/node` + PKCE + `workos-auth://callback` (https://github.com/workos/electron-authkit-example).
- Expo/native example: `getAuthorizationUrlWithPKCE()`, custom scheme `workos-authkit-example://callback`, "No client secret in the app" (https://github.com/workos/expo-authkit-example).
- **Node SDK v8 "now supports PKCE authentication for public clients"** – changelog Jan 22, 2026 (https://workos.com/changelog).
- **Redirect URI rules:** exact match; production requires HTTPS; "The single exception permits `http://127.0.0.1` in production for native clients"; port wildcards "limited to localhost and loopback addresses"; PKCE via `code_challenge` + `code_challenge_method: "S256"` (https://workos.com/docs/reference/authkit/authentication/get-authorization-url). Custom schemes are accepted in the dashboard (Electron example instructs adding `workos-auth://callback`).
- **Device/CLI auth flow** ("OAuth 2.0 Device Authorization Flow"): "works for any public client that cannot reliably receive a browser redirect"; "Public device clients send the client ID but do not embed an API key or client secret"; endpoints `https://api.workos.com/user_management/authorize/device` + `/user_management/authenticate` (https://workos.com/docs/authkit/cli-auth).
- **Tauri:** no official example or doc found (search returned only Electron/Expo and a generic third-party Tauri OAuth article https://dev.to/datner/tauri-oauth2-5f1h).
- **Static SPA (no server):** client-only integration via `authkit-react`; PKCE; without a custom auth domain you must set `devMode={true}` which "will keep the refresh token in local storage instead of a secure, HTTP-only cookie"; must add your domain to the CORS allow list; "cannot be nested inside an iframe" (https://workos.com/docs/user-management/client-only). `@workos-inc/authkit-js` (vanilla) exists, latest 0.20.2 (https://github.com/workos/authkit-js; https://www.jsdelivr.com/package/npm/@workos-inc/authkit-js); README has only `createClient/getUser/getAccessToken` — devMode/desktop details NOT FOUND in README.
- **Shared user pool website + desktop:** "Multiple Applications" (changelog Mar 16, 2026): "Every application gets its own client ID, redirect URIs, session policies, and credentials while sharing the same users and organizations"; docs explicitly name "Web app + mobile app + desktop client" (https://workos.com/changelog/multiple-applications; https://workos.com/docs/authkit/applications). Sessions are per application (not shared), users are.

## 4. Session lifetime

- Configurable per application in Dashboard → Applications → Sessions tab: "Session length, access token duration, and inactivity timeout" (https://workos.com/docs/authkit/sessions). Inactivity timeout added Jan 7, 2025 (https://workos.com/changelog/session-inactivity-timeouts).
- **Numeric min/max/defaults: NOT FOUND** in docs (checked https://workos.com/docs/authkit/sessions, the .md variant, and https://workos.com/docs/user-management/sessions/integrating-sessions/access-token). Applications doc says "A mobile app can stay signed in longer" (https://workos.com/docs/authkit/applications); the SvelteKit SDK's cookie max-age default is 400 days (https://github.com/workos/authkit-sveltekit) — suggests long sessions are possible, but the hard cap is unverified.
- Refresh tokens "may be rotated after use" (https://workos.com/docs/authkit/sessions).

## 5. Custom user metadata

- "up to 10 key-value pairs"; keys "Up to 40 characters long. ASCII only."; values "Up to 600 characters long. ASCII only."; backend-only ("not in the response body of the User Authentication operations") (https://workos.com/docs/authkit/metadata).
- `external_id`: "must be unique within your environment and are limited to 64 characters"; lookup via get-by-external-id endpoints (https://workos.com/docs/authkit/metadata/external-identifiers).
- **JWT Templates** customize access-token claims with `user.metadata`, `organization.metadata`, `user.external_id`; "must render to a JSON object that is 3072 bytes or smaller" (https://workos.com/docs/authkit/jwt-templates; blog Mar 19, 2025 https://workos.com/blog/custom-objects).

## 6. Bulk import / migration

- Create User: `email` required; `password` optional; `password_hash` + `password_hash_type` in `bcrypt, firebase-scrypt, ssha, ssha256, pbkdf2, argon2`; `email_verified`; `external_id`; `metadata` (https://workos.com/docs/reference/authkit/user/create).
- Migrations CLI (Auth0, Cognito, Clerk, Firebase, CSV): "Users without a matching hash are left without a password and will need to reset on first login"; rate-limit default 50 rps; resumable (https://github.com/workos/workos-migrations).
- Blog (Aug 26, 2026): "Disable webhook delivery for the duration of a bulk import" (https://workos.com/blog/migrate-custom-auth-to-third-party-provider).
- **Account linking:** "they sign in through Google OAuth despite already having a password account, WorkOS will safely attach the new credential to the existing user" — only if email ownership can be verified; otherwise "WorkOS does not complete the authentication flow" (https://workos.com/docs/authkit/identity-linking).

## 7. Backend verification

- JWKS: `https://api.workos.com/sso/jwks/{client_id}`; Python `workos_client.user_management.get_jwks_url()`; Node `workos.userManagement.getJwksUrl(...)`; claims `sub, sid, iss, org_id, role, permissions, exp, iat` (https://workos.com/docs/reference/user-management/session-tokens/jwks; https://workos.com/docs/user-management/sessions/integrating-sessions/access-token).
- Python SDK `workos`, Python 3.10+, sync + async (https://github.com/workos/workos-python).
- Events: `user.created`, `user.updated`, `user.deleted` + authentication.* via Events API or webhooks (https://workos.com/docs/events); webhooks "retried with exponential back-off for up to 3 days", signatures must be validated (https://workos.com/docs/events/data-syncing).

## 8. EU data residency

- DPA Exhibit B data location: "United States of America"; transfers via SCCs; "Updated: June 27, 2023" (https://workos.com/legal/data-processing-addendum). Security page: SOC 2 Type 2, GDPR compliant, no region info (https://workos.com/security). WorkOS blog (Jan 29, 2026) describes auth flowing "through WorkOS's US-based service" (https://workos.com/blog/data-residency-for-enterprise-saas). **No EU region found.**

## 9. Other

- `@workos/authkit-sveltekit` is official but server-side (needs `WORKOS_API_KEY`, `hooks.server.ts`, encrypted cookies) — fine for the Vercel site, not for a static-adapter Tauri frontend (https://github.com/workos/authkit-sveltekit).
- Stability (third-party): founded 2019, $100M raised, ~$30M ARR Oct 2025, ~90 employees, 1,000+ paying customers (https://sacra.com/c/workos/).
- Hosted UI vs headless: client-only libs and PKCE APIs exist; a custom-UI example exists (https://github.com/workos/workos-custom-ui-authkit-example — from search, not fetched).

## Key takeaways (WorkOS) for Tauri + website
- Cost is effectively $0–$99/mo at your scale; the $99 custom domain is practically required for production client-only cookies and non-"best-effort" email.
- Desktop: strong public-client story (PKCE public clients, official Electron SDK, `http://127.0.0.1` allowed in prod, device flow). No Tauri sample — you'd port the Electron/Expo PKCE flow (custom scheme or 127.0.0.1 loopback) in Rust/JS.
- Website + desktop share one user pool via Multiple Applications, each with its own session policy.
- Gaps: no Discord/Twitch/Steam/X out of the box; session max not documented; US-only hosting; metadata limited to 10 ASCII pairs.

---

# Stytch

## 1. Pricing

Page shows no date. Plans: "Pay as you go" "Starting at $0/Month" and "Enterprise" "Starting at: Custom"; free tier "10,000 monthly active users and AI agents", "unlimited organizations", "5 SSO/SCIM connections", "1,000 M2M tokens", "10,000 device fingerprints"; "SSO/SCIM Connections: $125/connection"; "Device Fingerprinting: $.005/fingerprint"; "Brand customization: $99 one-time fee across all projects"; "No feature gating", "no hard caps or pricing cliffs"; B2B and Consumer tabs show "identical pricing structure" (https://stytch.com/pricing).

- **Per-MAU price above 10K: NOT FOUND on the official page** (only "Volume discounts"/"Additional monthly active member cost"). Third party: "$0.10 per additional MAU" (Aug 5, 2025, https://supertokens.com/blog/stytch-pricing). A Stytch blog search snippet says "starts at a transparent 5 cents per active user" (https://stytch.com/blog/why-stytch-over-auth0/ — snippet, not fetched). Supertokens also lists "Pro $249/month", "Scale $799/month", "Enterprise $25,000/year" — these do NOT appear on the current official page and are likely outdated.
- MAU definition: FAQ header "What is a Monthly Active User (MAU)?" exists but body not rendered → NOT FOUND. Billing doc URLs 404'd.
- Self-serve pricing announced Nov 20, 2024 (https://stytch.com/blog/stytch-self-serve-pricing/).

**Estimated monthly cost (Stytch):**

| MAU | Cost |
|---|---|
| 1,000 / 5,000 / 10,000 | $0 |
| 25,000 | 15,000 billable × $0.05–$0.10 = **$750–$1,500/mo** (per-MAU rate unverified officially) |

Plus optional $99 one-time brand removal.

## 2. Social login providers

Official list: **Google, Amazon, Apple, Bitbucket, Coinbase, Discord, Facebook, GitHub, GitLab, LinkedIn, Microsoft, Salesforce, Slack, Twitch, Yahoo** (https://stytch.com/docs/guides/oauth/providers; https://stytch.com/docs/guides/oauth/idp-overview). The email-behavior page additionally references Figma, Snapchat, Spotify, TikTok and **Twitter** as providers (https://stytch.com/docs/guides/oauth/email-behavior) — so X/Twitter appears supported; **Steam: not found**. Consumer methods: magic links, SMS/OTP, passwords, passkeys, Web3, Google One Tap, biometrics (https://stytch.com/b2c). Custom OAuth for Consumer: NOT FOUND; generic SAML/OIDC exists only as B2B Enterprise SSO (https://stytch.com/docs/b2b/guides/sso/overview).

## 3. Desktop app support

- "A PKCE integration is required for applications that use native callback URLs, for example `appname://some/callback`"; JS SDK `oauth.$provider.start()` / `oauth.authenticate(token)`; API `POST /oauth/authenticate` (https://stytch.com/docs/guides/oauth/adding-pkce). Stytch "enforce[s] the use of PKCE ... if we detect that the triggering request contains a deeplink (any protocol that isn't http or https)" (blog Aug 30, 2023, https://stytch.com/blog/authorization-code-flow-with-pkce/).
- Redirect URLs: custom schemes OK ("e.g. `slack://auth/callback`"); "`http://localhost:3000`" only "in Test environments"; wildcards not on public suffixes — "`https://*.vercel.app` is not a valid redirect URL" (https://stytch.com/docs/guides/dashboard/redirect-urls). Loopback in Live: NOT FOUND.
- Frontend SDK stores sessions in cookies (`stytch_session`, `stytch_session_jwt`); "Using HttpOnly cookies requires a custom domain"; no desktop/non-browser docs (https://stytch.com/docs/sdks/resources/cookies-and-session-management).
- **No Electron or Tauri example found.** Headless SDKs: Next.js, React, Vanilla JS, iOS, Android, React Native (https://stytch.com/docs/guides/implementation/frontend-headless).

## 4. Session lifetime

`session_duration_minutes`: "minimum of 5 and a maximum of 527040 minutes (366 days)"; each authenticate extends by that duration (https://stytch.com/docs/api/session-auth; https://stytch.com/docs/consumer-auth/manage-sessions/lifecycle/extend-or-expire-session). JWTs have a "5-minute window" (https://stytch.com/docs/guides/sessions/using-jwts). 30–90+ days: yes.

## 5. Custom metadata

`trusted_metadata` (backend read/write) / `untrusted_metadata` (frontend can edit); "20 top-level keys", "4KB in size" (https://stytch.com/docs/api/metadata). `session_custom_claims`: "Total custom claims size cannot exceed four kilobytes"; reserved claims ignored; "A JWT cannot be modified once it is minted" (https://stytch.com/docs/api/session-auth; https://stytch.com/docs/guides/sessions/custom-claims). Custom Claim Templates can inject `{{ user.trusted_metadata.* }}` (https://stytch.com/docs/guides/sessions/custom-claim-templates — from search). `external_id` max 128 chars (https://stytch.com/docs/api/create-user).

## 6. Bulk import / migration

- Create User has no `password` param (passwordless creation), `create_user_as_pending`, metadata, `external_id` (https://stytch.com/docs/api/create-user). Migrate Password: hash types `bcrypt, md_5, argon_2i, argon_2id, sha_1, sha_512, scrypt, phpass, pbkdf_2`; creates user if missing; 100 rps (https://stytch.com/docs/api/password-migrate). Search snippet: Create User max "65 r/s"; "contact them for enterprise grade bulk import" (https://stytch.com/docs/guides/migrations/migrating-user-data-statically — snippet; fetched page rendered only the overview).
- Recommended: "Turn off breach and strength checks"; store old IDs in `trusted_metadata`; passwordless users: "pass in a dummy password hash, then Delete it afterwards" (https://stytch.com/docs/guides/migrations/additional-migration-considerations).
- **Dedup:** automatic by verified email; Microsoft, Amazon, Coinbase, Facebook, Snapchat, Spotify, TikTok, Twitter "do not return verified emails" → no auto-dedup for those (https://stytch.com/docs/guides/oauth/email-behavior). Password user who later logs in via OAuth/magic link → next password login returns `reset_password` error (forced reset) (https://stytch.com/docs/api/password-authenticate).

## 7. Backend verification

JWKS rotates "every 6 months" with "1 month grace period"; backend SDKs "available in Python, Node, Ruby, Go, and Java" (https://stytch.com/docs/guides/sessions/using-jwts). Endpoint `GET /v1/sessions/jwks/{project_id}` (search snippet from Stytch docs, https://stytch.com/docs/api-reference/consumer/api/sessions/get-jwks). Python SDK `stytch`, 3.10+, async (https://github.com/stytchauth/stytch-python). Webhooks "powered through Svix", `source.object_type.action` (e.g. `direct.user.create`), disabled after 5 days of failures (https://stytch.com/docs/resources/workspace-management/webhooks).

## 8. EU data residency

**NOT FOUND officially** (data-residency/trust/DPA URLs 404'd or empty; privacy policy now redirects to https://www.twilio.com/en-us/legal/privacy). A third-party guide claims "Stytch offers an EU region" (https://guptadeepak.com/ciam-compass/guides/data-residency-and-sovereignty/ — unverified).

## 9. Other

- **Stytch joined Twilio, Oct 30, 2025:** "No immediate changes to your contracts, pricing, SDKs, API keys, or integrations" (https://stytch.com/blog/stytch-joins-twilio/). Contrary: $126.3M raised, $1B valuation 2021, 77 employees (https://research.contrary.com/company/stytch — third party).
- No SvelteKit SDK; use Vanilla JS SDK or backend API.

## Key takeaways (Stytch) for Tauri + website
- Free to 10K MAU; at 25K expect ~$750–$1,500/mo (rate unverified officially).
- Better social coverage (Discord, Twitch, Twitter) but no Steam; Microsoft logins won't auto-link by email.
- Desktop: PKCE + custom-scheme redirects are supported and enforced, but no Electron/Tauri docs and no loopback-in-Live confirmation; `*.vercel.app` wildcard redirects rejected.
- Sessions up to 366 days; 4KB metadata/claims; EU residency unconfirmed; now Twilio-owned.
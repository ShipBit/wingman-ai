text
I have what I need; no further fetches are required. Here is the full report (all facts gathered live on 2026-09-09; WebSearch budget hit the session cap partway through, so later gaps were closed with direct WebFetch only, and anything I could not confirm is marked NOT FOUND).

# Clerk (clerk.com)

## 1. Pricing

**Important 2026 change – Clerk no longer bills "MAU", it bills "MRU" (Monthly Retained Users).**
- Pricing page FAQ: "A monthly retained user is a user who visits your app in a given month at least one day after signing up." Signup day is "First Day Free". (https://clerk.com/pricing)
- Third-party sources (secondary) say the switch from 10,000 free MAU to 50,000 free MRU happened on **February 5, 2026** (https://idsync.com/guides/clerk-pricing, https://www.budgetforge.dev/tools/clerk-pricing-2026). Clerk's own article confirms "Hobby plan: 50,000 MRU at $0/month (updated February 5, 2026; previously 10,000)" (https://clerk.com/articles/clerk-pricing-explained).
- The older announcement blog ("Every application gets 10,000 free monthly active users (MAUs)!", Pro "$25/month", "Additional MAUs are only $0.02 each", "their activity is not counted until 24 hours after signing up") is now superseded (https://clerk.com/blog/new-pricing-plans).

**Tiers (verbatim from https://clerk.com/pricing, no "as of" date on page):**
- Free (Hobby): "50,000 limit per app" MRU, $0, no credit card.
- Pro: "$25/mo" or "$20/mo billed annually", "50,000 included per app", "Additional $0.02/mo each (volume discounts available)".
- MRU volume table: 50,000 included; 50,001–100,000 "$0.02/mo each"; 100,001–1,000,000 "$0.018/mo each"; 1,000,001–10,000,000 "$0.015/mo each"; 10,000,001+ "$0.012/mo each".

**Free vs Pro feature rows (https://clerk.com/pricing):**
- Custom domain: included in both.
- Remove Clerk branding: "No" (Hobby) / "Yes" (Pro).
- MFA: "No" / "Yes". Passkeys: "No" / "Yes".
- Custom session duration: "Fixed to 7 days" (Hobby) / "Yes" (Pro).
- Social connections: "Up to 3" (Hobby) / "Unlimited" (Pro). No per-connection fee listed.
- Enterprise SSO (SAML/OIDC): "No" on Hobby; Pro: "1 connection ... Included per app. 2–15: $75/mo each".
- Satellite domains: "$10/mo each" (Pro only).
- Custom email/SMS templates, allowlist/blocklist: Pro only.
- Organizations: "100 MROs included per app" on free.
- Add-ons: "B2B Authentication Enhanced: $100/mo ($85/mo billed annually)"; "Administration Enhanced: $100/mo ($85/mo billed annually)" (unlimited impersonation); SMS "US/Canada $0.01/SMS, international: market rate".
- The old separate "Enhanced Authentication" add-on is not on the page; MFA/passkeys/white-labeling are listed as Pro inclusions (https://clerk.com/pricing, https://clerk.com/articles/clerk-pricing-explained).

**Estimated monthly cost (MRU; all four sizes are below the 50,000 included):**

| Users | Free plan | Pro plan | Math |
|---|---|---|---|
| 1,000 | $0 | $25 | 1,000 ≤ 50,000 included → overage 0 × $0.02 = $0 |
| 5,000 | $0 | $25 | overage $0 |
| 10,000 | $0 | $25 | overage $0 |
| 25,000 | $0 | $25 | overage $0 |

Pro is only needed if you want MFA, passkeys, custom session duration (>7 days), branding removal, or >3 social providers. Reference from Clerk's own article: "At 100,000 MRU: $25 + (100,000 − 50,000) × $0.02 = $1,025/month" (https://clerk.com/articles/clerk-pricing-explained). Note MRU is stricter than MAU, so actual counts will be at or below any MAU number you have.

## 2. Social login providers
- Full list on the official social-connections overview: Apple, Atlassian, Bitbucket, Box, Coinbase, Discord, Dropbox, Facebook, GitHub, GitLab, Google, HubSpot, Hugging Face, LINE, Linear, LinkedIn, Microsoft, Notion, Slack, Spotify, TikTok, Twitch, Vercel, X/Twitter v2, Xero. "For development instances, Clerk uses pre-configured, shared credentials"; production requires custom OAuth credentials. (https://clerk.com/docs/nextjs/guides/configure/auth-strategies/social-connections/overview)
- Dedicated guides confirmed: Discord (https://clerk.com/docs/guides/configure/auth-strategies/social-connections/discord), Twitch (https://clerk.com/docs/guides/configure/auth-strategies/social-connections/twitch), X/Twitter v2 (https://clerk.com/docs/guides/configure/auth-strategies/social-connections/x-twitter).
- Confirmed: Google, Discord, GitHub, Apple, Microsoft, X/Twitter, Twitch = yes.
- **Steam: NOT listed anywhere.** Custom providers require OIDC: "An OIDC identity provider is required" (discovery URL or manual endpoint config; PKCE option for public clients) (https://clerk.com/docs/authentication/social-connections/custom-provider). Steam is OpenID 2.0, so it cannot be added as a Clerk custom provider; you would need your own proxy (the docs themselves note "Sometimes attribute mapping isn't enough to get a provider working").
- Email/password strategies: "When Password is enabled, users provide a password to sign in."; Email verification code: "Users receive an OTP to their email address to sign in."; Email verification link: "Users receive an email with a link to sign in."; Phone SMS code and Passkeys require a paid plan in production; MFA: SMS code, TOTP, backup codes (https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options).

## 3. Desktop app support
- Official SDK list: Tauri and Svelte appear only as "Community-maintained"; Electron is not listed at all. Official: JavaScript (clerk-js), Expo, Chrome Extension, Python backend, etc. (https://clerk.com/docs/reference/overview)
- Community Tauri plugin `tauri-plugin-clerk` ("Community maintained", 28 stars, 58 commits). Why standard Clerk fails: "On mac cookies do not work on custom domains such as Tauri uses." and Clerk's API errors with "Setting both the 'Origin' and 'Authorization' headers is forbidden." The plugin patches global `fetch` to route Clerk API calls through `tauri-plugin-http`. Limitations: "OAuth flows don't function in default signin components", "Magic links unsupported", "DomainOrProxy not implemented". (https://github.com/Nipsuli/tauri-plugin-clerk)
- GitHub issue: a developer set `allowed_origins: ["tauri://localhost"]` and `allowedRedirectProtocols={"tauri:"}` and still could not sign in from a production Tauri build; issue "Closed as not planned", no maintainer workaround. (https://github.com/clerk/javascript/issues/4725)
- Clerk Backend API `allowed_origins` description: "For browser-like stacks such as browser extensions, Electron, or Capacitor.js, the instance allowed origins need to be updated with the request origin value." (https://raw.githubusercontent.com/clerk/clerk-sdk-python/main/docs/models/updateinstancerequestbody.md) — so non-http origins are contemplated, but only Chrome extensions have an official guide.
- Electron: no official support; community workarounds only (secondary: https://github.com/clerk/javascript/issues/1412, https://www.linkedin.com/pulse/securing-electron-app-clerk-muhammad-azamuddin).
- Static SPA: the JavaScript quickstart is a Vite vanilla-JS app with no backend; load via `npm install @clerk/clerk-js` or CDN script with `data-clerk-publishable-key` (https://clerk.com/docs/js-frontend/getting-started/quickstart). Session persistence is cookie-based: `__client` cookie ("Secure and HttpOnly", references the session) and `__session` cookie (holds the 60-second JWT) (https://clerk.com/blog/how-we-roll-sessions). This cookie dependency is exactly what breaks in Tauri webviews per the plugin README above.
- Standards-based alternative — Clerk as OAuth/OIDC IdP: "To enable PKCE for a public client, you can enable the Public option for each OAuth app in the Clerk Dashboard." Discovery at Frontend API URL + `/.well-known/oauth-authorization-server`. "OAuth access tokens expire after 1 day." "Refresh tokens never expire." Whether `myapp://` or `http://localhost` redirect URIs are accepted: NOT FOUND on the page. (https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth)
- New (changelog 2026-09-08): "OAuth Device Authorization Grant" — "Authorize CLIs, TVs, and other input-constrained devices"; "Public clients send only their Client ID"; "It does not use Proof Key for Code Exchange (PKCE) or redirect URIs."; "currently available in beta", "contact support to enable it for your workspace." (https://clerk.com/changelog, https://clerk.com/changelog/2026-09-08-device-authorization-grant)

## 4. Session lifetime
- "Maximum lifetime ... By default, this setting is enabled with a default value of 7 days for all newly created instances." Inactivity timeout: "By default, this setting is disabled." Both custom values: "requires a paid plan for production use". "Cookies set in Google Chrome have a Max-Age upper limit of 400 days" — "Users who are using Google Chrome will be signed out within 400 days, even if session lifetime is set to a longer duration." (https://clerk.com/docs/guides/secure/session-options)
- Documented hard maximum for session lifetime: NOT FOUND (only the 400-day Chrome note; long sessions are clearly intended).
- Hobby plan: "Fixed to 7 days" (https://clerk.com/pricing). So 30–90-day "remember me" requires Pro.
- Session JWT: "the token is set to expire 60 seconds into the future" (https://clerk.com/blog/how-we-roll-sessions); JWT templates "Token lifetime ... Default is 60 seconds", clock skew default 5 s (https://clerk.com/docs/guides/sessions/jwt-templates).
- Clerk-as-IdP OAuth tokens: access 1 day, refresh never expires (https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth).

## 5. Custom user metadata
- Public: frontend read, backend read/write. Private: backend only. Unsafe: frontend and backend read/write. "8KB maximum" total; when put into session tokens "highly recommended to keep it under 1.2KB" (4KB cookie cap). Backend: `getUser()` and `updateUserMetadata()`. (https://clerk.com/docs/users/metadata)
- JWT templates support `{{user.public_metadata}}`, `{{user.unsafe_metadata}}`, dotted paths like `{{user.public_metadata.interests}}`, `{{user.external_id}}`; session-tied claims (`sid`, `v`, `pla`, `fea`) cannot be in custom JWTs. (https://clerk.com/docs/guides/sessions/jwt-templates)
- Backend API field text: public_metadata "visible to both your Frontend and Backend APIs"; private_metadata "only visible to your Backend API"; unsafe_metadata "can be updated from both the Frontend and Backend APIs" (https://raw.githubusercontent.com/clerk/openapi-specs/main/bapi/2024-10-01.yml).

## 6. Bulk import / migration
- Clerk provides "an open-source tool that takes a JSON or CSV file as input ... and creates a user in Clerk using the Backend API"; CreateUser is rate limited; recommended to "store previous IDs as an `external_id`" and use `"userId": "{{user.external_id || user.id}}"` in a JWT template (https://clerk.com/docs/deployments/migrate-overview).
- `skip_password_requirement`: "When set to true, password is not required anymore when creating the user and can be omitted." `skip_password_checks`: "When set to true all password checks are skipped. It is recommended to use this method only when migrating plaintext passwords to Clerk." `password_digest`: "In case you already have the password digests and not the passwords ..."; `external_id`: "Must be unique across your instance." (https://raw.githubusercontent.com/clerk/openapi-specs/main/bapi/2024-10-01.yml)
- Email addresses created via Backend API: "Addresses are created as verified by default" (https://clerk.com/docs/reference/backend/user/create-user).
- Password hashers: enum values were truncated in the spec I fetched; a search-result summary citing Clerk docs lists "bcrypt, bcrypt_sha256_django, md5, pbkdf2_sha256, pbkdf2_sha256_django, phpass, scrypt_firebase, sha256 and the argon2 variants argon2i and argon2id" with insecure ones migrated to bcrypt on first sign-in — treat as secondary (search summary of https://clerk.com/docs/reference/backend/user/create-user; not verbatim-verified).
- Forcing a password set at first login for password-less imported users: NOT FOUND as an explicit doc statement. In practice they can sign in via email code/link if enabled, or use password reset.
- Account linking: when the OAuth provider returns a verified email matching an existing account, "Clerk links the OAuth account to the existing account and signs the user in." If the OAuth email is unverified, Clerk verifies it first, then links. If the existing Clerk email is unverified, "Clerk will prompt the user to change their password before linking the accounts." (https://clerk.com/docs/authentication/social-connections/account-linking). Since API-created emails are verified by default, an imported user X who later signs in with Google (verified X) is auto-linked.

## 7. Backend verification
- JWKS: Backend API `https://api.clerk.com/v1/jwks`; or "your Frontend API URL with `/.well-known/jwks.json` appended". RS256; verify `exp`, `nbf`, and "Validate that the `azp` (authorized party) claim equals any of your known origins". (https://clerk.com/docs/backend-requests/manual-jwt)
- Webhooks: "Clerk uses Svix to send our webhooks."; retries per Svix schedule; verify with `verifyWebhook` helper; optional IP allowlist from Svix (https://clerk.com/docs/webhooks/overview). Events: `user.created`, `user.updated`, `user.deleted` documented; other payload types include SessionJSON, EmailJSON, OrganizationJSON etc.; full list is in the Dashboard "Event Catalog" (https://clerk.com/docs/guides/development/webhooks/syncing, https://clerk.com/docs/guides/development/webhooks/overview).
- Official Python backend SDK exists (https://clerk.com/docs/reference/overview).

## 8. EU data residency
- "Data is hosted on US infrastructure (Google Cloud and Cloudflare, with all subprocessors in the USA)"; "we do not offer the ability to select regions"; transfers under EU-US Data Privacy Framework; SOC 2 Type 2, HIPAA, no ISO 27001. (https://clerk.com/articles/clerk-security-how-we-protect-your-users)
- DPA (effective Nov 26, 2024): "Clerk hosts Personal Data primarily in Google Cloud data centers and Cloudflare"; no EU hosting option; relies on DPF/SCCs. (https://clerk.com/legal/dpa)
- 2026 changelog: no EU-region entry (https://clerk.com/changelog). Trust center (https://trust.clerk.com) returned 403 — could not fetch.
- Conclusion: **no EU region at any price.**

## 9. Other
- SvelteKit: `svelte-clerk` — "This package is unofficial and not affiliated with Clerk." (https://svelte-clerk.netlify.app/; https://github.com/wobsoriano/svelte-clerk); Clerk's own SDK page classifies Svelte as community (https://clerk.com/docs/reference/overview).
- Vendor: investors include a16z, CRV, Madrona, S28, Stripe, Netlify, Mango, Fathom, South Park Commons; "Free for your first 50,000 monthly retained users and 100 monthly retained orgs" (https://clerk.com/company). Changelog shows ~10 feature entries between 2026-07-31 and 2026-09-08 (https://clerk.com/changelog). Founding year/funding amounts: NOT FOUND on official pages.
- Limitations: no Steam; no EU region; desktop is community-only; Hobby capped at 3 social providers and 7-day sessions.

## Key takeaways for a Tauri desktop app + website (Clerk)
Clerk is cheap at your scale ($0–$25/mo up to 50k retained users) and has a rich provider list (Discord, Twitch, X, Apple, Microsoft, GitHub, Google), but not Steam, and its custom-provider feature is OIDC-only so Steam would need your own bridge. The bigger risk is the desktop path: Clerk's sessions are cookie-bound to its Frontend API, which breaks in Tauri webviews (documented by the community plugin and an unresolved GitHub issue). Workable routes are (a) the community `tauri-plugin-clerk` with its OAuth/magic-link limitations, (b) using Clerk as an OAuth/OIDC IdP with a Public/PKCE client from the system browser (custom-scheme redirect support undocumented), or (c) the new beta Device Authorization Grant. There is no EU data region.

# Kinde (kinde.com)

## 1. Pricing
Verbatim from https://www.kinde.com/pricing/ (no "as of" date on page):
- Free: "$0 forever", "10,500 monthly active users (MAU)", "Use your own custom domain", "Multi-Factor Authentication (MFA)", "Email, SMS and social login", "B2B management with organizations", "2 environments (production and development)". Webhooks "1 per environment". Branding removal "Not included". Support: email + community.
- Pro: "$25 USD per month", "10,500 MAU free", "$0.0175 per extra MAU ($0 for billed users)", "Remove Kinde branding", "Uncapped organizations", "Unlimited feature flags", webhooks "Unlimited".
- Plus: "$75 USD per month", "10,500 MAU free", "$0.0163 per extra MAU ($0 for billed users)", "6% MAU discount", "Free enterprise SSO", "6 environments", "1 advanced organization".
- Scale: "$250 USD per month" (fixed, not "contact us"), "10,500 MAU free", "$0.0151 per extra MAU ($0 for billed users)", "13% MAU discount", "11 environments", "5 advanced organizations".
- All plans: custom domain "Included"; "MFA via SMS", "MFA via email", "MFA via Authenticator app" (SMS "$7c per SMS or BYO provider"). Enterprise SSO: 1 included on Free/Pro, free on Plus/Scale. Kinde-billing transaction fee 0.7% (Free/Pro), 0.6% (Plus), 0.5% (Scale). Social connections count: not quantified on page (no add-on fee listed). Custom roles/permissions: 2 roles + 10 permissions on Free, unlimited on Pro+.
- Note: several third-party pages still show "$0.025/extra MAU" for Pro (e.g. https://outmano.com/tools/kinde/pricing) — the live official page shows $0.0175.

**MAU definition:** "Kinde counts one MAU for every user who is 'active' during a billing period. Active means they have been issued at least one access token." One MAU regardless of sign-in count; users created and deleted before signing in are not counted; users who sign in then are deleted in the same period still count. (https://docs.kinde.com/manage-your-account/your-data/check-your-mau/). Pricing page: "Users on paid subscriptions are not counted" (i.e. customers you bill through Kinde) (https://www.kinde.com/pricing/).

**Estimated monthly cost (MAU; 10,500 included on every plan):**

| MAU | Free | Pro | Plus | Scale |
|---|---|---|---|---|
| 1,000 | $0 | $25 | $75 | $250 |
| 5,000 | $0 | $25 | $75 | $250 |
| 10,000 | $0 | $25 | $75 | $250 |
| 25,000 | see note | $25 + 14,500 × $0.0175 = $25 + $253.75 = **$278.75** | $75 + 14,500 × $0.0163 = $75 + $236.35 = **$311.35** | $250 + 14,500 × $0.0151 = $250 + $218.95 = **$468.95** |

Note: whether the Free plan can exceed 10,500 MAU with overage is NOT FOUND on the page (third-party summaries describe Pro as "uncapped MAUs", implying Free is capped: https://outmano.com/tools/kinde/pricing).

## 2. Social login providers
- Official list: Apple, Bitbucket, Clever, Discord, Facebook, GitHub, GitLab, Google, LinkedIn, Microsoft, Roblox, Slack, Twitch, X (formerly Twitter), Xero, plus "Custom OAuth 2.0 connections". No per-plan limit stated. (https://docs.kinde.com/authenticate/social-sign-in/add-social-sign-in/)
- Confirmed: Google, Discord, GitHub, Apple, Microsoft, X/Twitter, Twitch = yes. **Steam: NOT listed.**
- Custom connections support "OAuth 2.0 and OpenID Connect (OIDC)"; required: Authorization URL, Token URL, User Info URL, Client ID/Secret; provider must "support the OAuth2 authorization code flow"; no OpenID 2.0 mention (https://docs.kinde.com/authenticate/custom-configurations/custom-oauth2-connection/). Steam (OpenID 2.0) therefore not supportable directly.
- Email: "Email without password" ("users sign up with their preferred email, but don't need a password" — a verification code is sent), "Email with password", "Invited users only". Magic link: NOT FOUND (only one-time codes described). (https://docs.kinde.com/authenticate/authentication-methods/email-authentication/)

## 3. Desktop app support
- SDK catalogue: Frontend (JavaScript, React), Backend (incl. Python, SvelteKit, Node, Go, etc.), Native (Android, iOS, React Native, Expo, Flutter). No Electron/Tauri/desktop SDK (https://docs.kinde.com/developer-tools/about/our-sdks/). Tauri/Electron docs or community guides: NOT FOUND.
- Custom-scheme redirects are documented for native SDKs: Expo callback "`myapp://localhost:3000`" registered under Settings > Applications > Callback URLs, with PKCE via expo-auth-session (https://docs.kinde.com/developer-tools/sdks/native/expo/); iOS "`<your_url_scheme>://kinde_callback`", Android "`myapp://myhost.kinde.com//kinde_callback`" (search summaries of https://docs.kinde.com/developer-tools/sdks/native/ios-sdk/ and https://docs.kinde.com/developer-tools/sdks/native/android-sdk/). The generic callback-URL page only discusses http/https and wildcards (https://docs.kinde.com/get-started/connect/callback-urls/).
- Raw PKCE without SDK: `/oauth2/auth`, `/oauth2/token`, `code_challenge_method=S256`, `offline` scope ("Use offline, not offline_access"), redirect_uri must be pre-registered (https://docs.kinde.com/developer-tools/about/using-kinde-without-an-sdk/). This is the natural fit for Tauri: system browser + deep link + PKCE.
- JS SPA SDK `@kinde-oss/kinde-auth-pkce-js`: tokens "stored in memory"; `offline` scope included by default "to silently re-authenticate"; custom domain enables an httpOnly cookie; `is_dangerously_use_local_storage` for dev (https://docs.kinde.com/developer-tools/sdks/frontend/javascript-sdk/).

## 4. Session lifetime
- Defaults: refresh token "15 days (1,296,000 seconds)", access token "24 hours (86,400 seconds)", ID token "1 hour (3,600 seconds)"; all configurable per app under Settings > Environment > Applications > [app] > Tokens (fields: ID/Access/Refresh token expiry, "Session inactivity timeout", "Refresh token cookies toggle (requires custom domain)"); "The refresh token lifetime must always be set longer than the access token lifetime."; "we do not recommend extending the access token lifetime beyond 1 day." (https://docs.kinde.com/build/tokens/configure-tokens/)
- Documented maximum refresh-token lifetime: NOT FOUND. Rotation: "The old refresh token becomes immediately invalid" with a small overlap window (https://docs.kinde.com/build/tokens/refresh-tokens/).
- SvelteKit SDK v2.5.0 added `KINDE_SESSION_MAX_AGE` for session cookie expiry (https://github.com/kinde-oss/kinde-sveltekit-sdk/releases). 30–90-day sessions therefore appear feasible by raising refresh-token expiry, but no upper bound is quoted.

## 5. Custom user metadata
- "Properties are a way for you to add custom data to Kinde, and then use that data for custom claims and in tokens."; properties can be "public" to be passed in tokens; "Properties can be added and edited via API" (Management API, M2M app required) (https://docs.kinde.com/properties/about-properties/).
- Tokens: properties "must be set to public in the property settings" before adding to access/ID tokens via "Customize [access/ID] token" (https://docs.kinde.com/properties/work-with-properties/properties-in-tokens/). Also a "user token generation" workflow for dynamic claims (https://docs.kinde.com/build/tokens/token-customization/).
- Size limits / data types / max property count: NOT FOUND.

## 6. Bulk import / migration
- Bulk import: CSV, NDJSON, Firebase NDJSON, ASP.NET Identity CSV; "Files must be 49MB or smaller"; columns include `provided_id`, `email_verified`, `hashing_method` (bcrypt, crypt, md5, sha256, wordpress, pbkdf2, firebase-scrypt, aspnet-identity-v2). "Users can be imported without passwords. On first login, they'll receive a one-time code to verify identity unless you set password_verified to TRUE". (https://docs.kinde.com/manage-users/add-and-edit/import-users-in-bulk/)
- Management API: `POST /api/v1/user` with `profile` + `identities`; password set separately via `PUT /api/v1/users/{user_id}/password` with the same hashing methods and an `is_temporary_password` flag; `provided_id` supported; rate limits — prefer CSV for thousands (https://docs.kinde.com/get-started/switch-to-kinde/create-users-with-api/).
- Migration options: bulk, API, drip-feed via workflows, hard cutover (https://docs.kinde.com/get-started/switch-to-kinde/switch-to-kinde-for-user-authentication/).
- `user.created` webhook "does not activate during bulk user imports" (https://docs.kinde.com/integrate/webhooks/add-manage-webhooks/).
- Account linking: "If a user signs up with a trusted connection, e.g. Google, Kinde recognises that a user exists and the email address is from a trusted provider, so we add a Google identity to their profile." Google is trusted by default; other connections have a "Trust email addresses provided by this connection" toggle (docs recommend leaving it off) (https://docs.kinde.com/authenticate/about-auth/identity-and-verification/, https://docs.kinde.com/authenticate/social-sign-in/google/). Email auth page also says accounts are linked across providers when the same verified email is detected (https://docs.kinde.com/authenticate/authentication-methods/email-authentication/). So imported email X + later Google sign-in with X → auto-link; for Discord/GitHub etc. you must enable trust or the user verifies by code.

## 7. Backend verification
- JWKS: `https://<your_subdomain>.kinde.com/.well-known/jwks`; RS256 only ("We don't support HMAC signing by design"); use any standard JWT library (https://docs.kinde.com/build/tokens/verifying-json-web-tokens/).
- Webhooks: "Kinde uses the application/jwt content-type" — body is a signed JWT verified against the same JWKS; `@kinde/webhooks` npm decoder; retries immediate, 5s, 30s, 2m, 10m, 1h, 4h, then "Every 12 hours until 36 hours"; "Webhooks that fail consistently for 72 hours are automatically disabled" (https://docs.kinde.com/integrate/webhooks/about-webhooks/). Events: `user.created`, `user.updated`, `user.deleted`, `user.authenticated`, `user.authentication_failed`, `organization.created/updated/deleted`, `role.*`, `permission.*`, `passkey.added/removed`, `subscriber.created`, `access_request.created`, `customer.*` billing events (https://docs.kinde.com/integrate/webhooks/add-manage-webhooks/). Not Svix — Kinde-native delivery.

## 8. EU data residency
- Five regions: Sydney (AU), Oregon (US), Quebec (CA), Dublin (IE), London (UK). "Once selected, you cannot change the data region of your business within Kinde." No extra cost or plan restriction mentioned (https://docs.kinde.com/get-started/learn-about-kinde/supported-data-regions/). EU region launched July 12, 2023 (https://www.kinde.com/blog/releases/eu-data-region-now-available-in-kinde/).
- Compliance: ISO 27001:2022, SOC 2 Type 2 (full report on paid plans), GDPR, HIPAA, CCPA (https://docs.kinde.com/trust-center/privacy-and-compliance/compliance/, https://www.kinde.com/security/).

## 9. Other
- SvelteKit SDK is official (kinde-oss) but a server-side SDK (hooks + `/api/auth/*` routes, `KINDE_AUTH_WITH_PKCE` option) (https://docs.kinde.com/developer-tools/sdks/backend/sveltekit-sdk/). Repo: 8 stars, 5 open issues, latest release 2.5.0 on Sept 3, 2024 — effectively stale for two years (https://github.com/kinde-oss/kinde-sveltekit-sdk, https://github.com/kinde-oss/kinde-sveltekit-sdk/releases). For a static SvelteKit site you would use the JS PKCE SDK instead.
- Official Python SDK exists (https://docs.kinde.com/developer-tools/about/our-sdks/).
- Vendor: "Australian born company"; funding/investors: NOT FOUND on official pages (https://www.kinde.com/about/).
- Limitations: no Steam; no desktop SDK/docs; no magic link found; Free plan limited to 1 webhook per environment and 2 roles.

## Key takeaways for a Tauri desktop app + website (Kinde)
Kinde is the more standards-shaped choice for a desktop app: it is a plain OIDC/OAuth2 server with documented PKCE, `offline` refresh tokens, custom-scheme callbacks (proven via Expo/iOS/Android docs), and a memory-based JS PKCE SDK — so a Tauri flow (system browser + deep-link + PKCE, or in-webview PKCE) needs no proprietary cookie handling, even though there is no Tauri/Electron guide. Free tier is generous (10,500 MAU with custom domain, MFA and social login included), EU/UK regions exist at no listed extra cost, and imports without passwords fall back to one-time codes. Weak spots: no Steam (custom connections are OAuth2/OIDC only), the official SvelteKit SDK looks unmaintained (last release 2024), no magic link, token maximums are undocumented, and costs rise faster than Clerk above ~10.5k MAU ($278.75/mo at 25k on Pro vs Clerk's flat $25).
text
Research is complete; no further fetches are needed. Here is the full report.

---

# Auth provider research: Supabase Auth vs Firebase Auth / Identity Platform

Date of research: 2026-09-09. All facts below come from pages fetched today; third-party sources are labelled. Pages that could not be fetched: Medium "Supabase + Google OAuth in a Tauri 2.0 macOS app" (HTTP 403), Medium "Using Firebase in Electron" (HTTP 403). The WebSearch budget of this session ran out after ~10 searches, so the remainder was done via direct doc fetches.

---

## A. Supabase Auth

### A1. Pricing

**Plan tiers (exact wording from pricing page, no date/version shown on page)** (https://supabase.com/pricing)
- Free: "$0/month"; MAU: "50,000 monthly active users"; Third-Party MAU: "50,000 included"; SSO MAU: not included; Postgres: "Included" (Nano, shared CPU, up to 0.5 GB RAM).
- Pro: "from $25/month"; MAU: "100,000 monthly active users", "then $0.00325 per MAU"; Third-Party MAU: "100,000 included, then $0.00325 per MAU"; SSO MAU: "50 included, then $0.015 per MAU"; "$10/month in compute credits"; Spend cap: "on by default on the Pro Plan"; Postgres: "Included" (Micro instance covered by the credits); "Additional projects each add their own compute cost".
- Team: "from $599/month"; same MAU/Third-party/SSO quotas and overage as Pro; "$10/month in compute credits".
- Enterprise: "custom pricing", all quotas "Custom".

**MAU definition** (https://supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users)
- "You are charged for the number of distinct users who sign in or refresh their token during the billing cycle." Each user counts once per cycle; count resets each cycle.
- Quotas: Free 50,000 (no overage possible); Pro/Team 100,000 then "$0.00325 per MAU". Page example: Pro with 160,000 MAU = 60,000 × $0.00325 = $195.
- Free plan / spend-cap-on orgs that exceed quota get notified and enter a grace period under the Fair Use Policy.

**Third-Party MAU** (https://supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users-third-party)
- "The number of distinct users who sign in or refresh their token during the billing cycle using a third-party authentication provider (Clerk, Firebase Auth, Auth0, AWS Cognito)." Free 50,000; Pro/Team 100,000 then "$0.00325 per Third-Party MAU".

**SSO MAU** (https://supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users-sso)
- "distinct users who sign in or refresh their token during the billing cycle using a SAML 2.0 compatible identity provider." Pro/Team: 50 included, then "$0.015 per SSO MAU". Not on Free.

**Compute add-ons** (https://supabase.com/docs/guides/platform/compute-and-disk)
- Nano $0 (Free default, shared CPU, up to 0.5 GB); Micro $0.01344/h (~$10/mo, 2-core shared, 1 GB); Small $0.0206/h (~$15); Medium $0.0822/h (~$60); Large $0.1517/h (~$110); XL $0.2877/h (~$210); 2XL $0.562/h (~$410). "Nano Compute are billed at the same price as Micro Compute" on paid plans; new Nano instances cannot be launched on paid orgs.
- So: the $25 Pro plan effectively includes one Micro Postgres instance (the $10 credit covers the ~$10 Micro).

**Spend cap** (https://supabase.com/docs/guides/platform/cost-control)
- "The Spend Cap determines whether your organization can exceed your subscription plan's quota for any usage item." With cap on: "After exceeding the quota for a usage item, further usage of that item is disallowed until the next billing cycle." Not covered by the cap (always billed): compute instances/variants, custom domain, disk IOPS/throughput, IPv4, log drains, "Multi-Factor Authentication Phone", PITR.

**Cost at MAU levels (Auth only, single project)**
- 1,000 / 5,000 / 10,000 / 25,000 MAU: Free plan = $0 (all under 50,000). Pro = $25/mo flat (all under 100,000 included MAU; Micro compute covered by credits). Team = $599/mo flat.
- Overage only starts above 100,000 on Pro: e.g. 125,000 MAU = $25 + 25,000 × $0.00325 = $106.25/mo.

### A2. Social login providers

- Docs list 19 built-in providers: Apple, Azure (Microsoft), Bitbucket, Discord, Facebook, Figma, GitHub, GitLab, Google, Kakao, Keycloak, LinkedIn, Notion, Slack, Spotify, Twitter, Twitch, WorkOS, Zoom. Steam is not listed. Page states you can "add any OAuth2 or OIDC-compatible provider using Custom OAuth/OIDC Providers" (https://supabase.com/docs/guides/auth/social-login)
- supabase-js `Provider` type (source, master): `'apple' | 'azure' | 'bitbucket' | 'discord' | 'facebook' | 'figma' | 'github' | 'gitlab' | 'google' | 'kakao' | 'keycloak' | 'linkedin' | 'linkedin_oidc' | 'notion' | 'slack' | 'slack_oidc' | 'spotify' | 'twitch' | 'twitter' | 'x' | 'workos' | 'zoom' | 'fly' | \`custom:${string}\`` (https://raw.githubusercontent.com/supabase/supabase-js/master/packages/core/auth-js/src/lib/types.ts)
- Checklist: Google yes, Discord yes, GitHub yes, Apple yes, Microsoft (azure) yes, X/Twitter yes (`twitter` and `x`), Twitch yes, Steam NO (not built-in), email magic link yes, email OTP yes, password yes.
- Magic link + email OTP: both supported via `signInWithOtp`; "Though the method is labelled 'OTP', it sends a Magic Link by default." "By default, a user can only request a magic link once every 60 seconds and they expire after 1 hour." Auto-signup is default; set `shouldCreateUser: false` to prevent. (https://supabase.com/docs/guides/auth/auth-email-passwordless)
- **Custom OAuth/OIDC providers** (https://supabase.com/docs/guides/auth/custom-oauth-providers): two types — OAuth2 (you supply "Authorization URL, Token URL, and UserInfo URL") and OIDC (issuer URL, discovery). Options: `acceptable_client_ids`, `email_optional`, `pkce_enabled`, `authorization_params`. Sign in with `signInWithOAuth({ provider: 'custom:my-provider' })`. Limits: "Free plan projects can add up to 3 custom providers. Pro plan and above have unlimited custom providers." No beta/date notice on page.
- Steam: not a built-in provider; a community discussion exists ("Sign in with Steam workaround", https://github.com/orgs/supabase/discussions/15118 — search result only, not fetched). Note Steam uses OpenID 2.0, not OAuth2/OIDC, so the custom-provider feature would not fit directly; the workaround described in search results is a server-side flow that creates/links users via the admin API (third-party hint, unverified).
- Third-party auth (separate feature): first-class support for Clerk, Firebase Auth, Auth0, AWS Cognito, WorkOS; requirement: "The third-party provider must use asymmetrically signed JWTs (exposed as an OIDC Issuer Discovery URL)". Generic custom OIDC not listed there. (https://supabase.com/docs/guides/auth/third-party/overview)

### A3. Desktop app support

- **Redirect URL allow list** (https://supabase.com/docs/guides/auth/redirect-urls): glob wildcards `*`, `**`, `?`, `[!...]` supported; custom schemes explicitly allowed: "For mobile applications you can use deep linking URIs. For example, for your SITE_URL you can specify something like com.supabase://login-callback/"; localhost allowed (`http://localhost:3000/**` examples). So `wingman://auth/callback` is allowed. Auth errors are returned as query fragments on the redirect URL.
- **Deep-link doc** (https://supabase.com/docs/guides/auth/native-mobile-deep-linking): pattern `[YOUR_SCHEME]://[YOUR_HOSTNAME]`; "You can choose whatever you would like for YOUR_SCHEME and YOUR_HOSTNAME as long as the scheme is unique across the user's device." Add the URL under "Additional Redirect URLs". Covers Expo, Flutter (Android, iOS, Web, macOS, Windows), Swift, Kotlin; Windows "additional registry setup required" and macOS covered. No Tauri/Electron section.
- **PKCE flow** (https://supabase.com/docs/guides/auth/sessions/pkce-flow): redirect carries `code=`; exchange with `exchangeCodeForSession(code)`; "The code has a validity of 5 minutes and can only be exchanged for an access token once." "The code verifier is created and stored locally when the Auth flow is first initiated" so "the code exchange must be initiated on the same browser and device where the flow was started" (fine for a desktop app that starts the flow and receives the deep link itself). Overlapping flows overwrite the verifier; experimental `appendPkceFlowIdToRedirects` + `flowId` fixes that.
- **supabase-js options**: `flowType: 'implicit' | 'pkce'`, "Defaults to the 'implicit' flow otherwise" (DEFAULT_OPTIONS has `flowType: 'implicit'`); `skipBrowserRedirect`: "If set to true does not immediately redirect the current browser context to visit the OAuth authorization page for the provider." → returns `data.url` you can open in the system browser. Custom `storage` adapter supported. (https://raw.githubusercontent.com/supabase/supabase-js/master/packages/core/auth-js/src/lib/types.ts, https://raw.githubusercontent.com/supabase/supabase-js/master/packages/core/auth-js/src/GoTrueClient.ts, https://supabase.com/docs/reference/javascript/initializing)
- **signInWithIdToken** (native provider SDK route): "Supported names: google, apple, azure, facebook, kakao" plus `custom:${string}`; nonce validation on by default (can be disabled under Providers > Google > Skip Nonce Check). Chrome-extension example uses `chrome.identity.launchWebAuthFlow()` then `signInWithIdToken`. (https://supabase.com/docs/guides/auth/social-login/auth-google, types.ts above)
- **Tauri examples (third-party)**:
  - JeaneC/tauri-oauth-supabase: localhost:9999 loopback via `tauri-plugin-oauth`, opens system browser, captures code, "PKCE authorization flow" (https://github.com/JeaneC/tauri-oauth-supabase).
  - codereader.dev "GitHub OAuth for Tauri apps" (2023-12-15): loopback server via `tauri-plugin-oauth`, server-side code exchange, or device flow (https://codereader.dev/blog/github-auth-for-tauri-apps).
  - Medium Tauri 2.0 deep-link article: NOT FOUND / could not fetch (403).
- Official Supabase Tauri/Electron guide: NOT FOUND.

### A4. Session lifetime (https://supabase.com/docs/guides/auth/sessions)

- Access token (JWT): "Most applications should use the default expiration time of 1 hour." "Setting a value over 1 hour is generally discouraged for security reasons." Values below 5 minutes discouraged. Hard maximum: NOT FOUND on page.
- Refresh tokens: "never expire but can only be used once"; reuse interval "By default this is 10 seconds".
- Pro-plan-and-up settings: "Time-box user sessions", "Inactivity timeout", "Single session per user". "Sessions are not proactively destroyed when you change these settings, but rather the check is enforced whenever a session is refreshed next."
- Conclusion: with defaults (and no time-box), users stay logged in indefinitely as long as the client refreshes.

### A5. Custom user metadata

- `raw_user_meta_data` stores metadata assigned at sign-up; `auth.users` queryable via SQL (`select * from auth.users;`). Recommended `public.profiles` table with FK to `auth.users` and a signup trigger; warning: "If the trigger fails, it could block signups". (https://supabase.com/docs/guides/auth/managing-user-data)
- Admin `createUser` accepts `user_metadata` and `app_metadata`; "This function should only be called on a server. Never expose your service_role key in the browser." (https://supabase.com/docs/reference/javascript/auth-admin-createuser)
- Custom Access Token Hook: runs before token issuance; can add/modify `jti`, `nbf`, `app_metadata`, `user_metadata`, `amr`; required claims `iss, aud, exp, iat, sub, role, aal, session_id, email, phone, is_anonymous` cannot be removed; Postgres function or HTTP (Edge Function) implementation. (https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook)
- Hook plan availability: Before User Created, Custom Access Token, Send SMS, Send Email = "Free, Pro"; MFA Verification Attempt and Password Verification Attempt = "Teams and Enterprise". (https://supabase.com/docs/guides/auth/auth-hooks)

### A6. Bulk user import / account linking

- `auth.admin.createUser({ email, email_confirm: true, user_metadata, app_metadata })` — password is optional in the documented examples, so users can be created confirmed and without a password; they then sign in via magic link/OTP or reset password. A dedicated bulk-import API: NOT FOUND in docs (loop `createUser` server-side). (https://supabase.com/docs/reference/javascript/auth-admin-createuser)
- Identity linking (https://supabase.com/docs/guides/auth/auth-identity-linking): "Supabase Auth automatically links identities with the same email address to a single user." Requires verified email; it will "remove any other unconfirmed identities linked to an existing user". SAML users excluded. Manual linking via `linkIdentity()` (must be enabled). "If you try to create an email account after previously signing up with OAuth using the same email, you'll receive an obfuscated user response with no verification email sent." Add a password to an OAuth account with `updateUser({ password })`. Unlinking needs at least 2 identities.
- Before User Created hook can block signups (domain allowlists, provider blocks, CIDR). (https://supabase.com/docs/guides/auth/auth-hooks/before-user-created-hook)

### A7. Backend verification / webhooks

- JWKS: `GET https://project-id.supabase.co/auth/v1/.well-known/jwks.json`, "cached by Supabase's edge servers for 10 minutes". Algorithms: ES256 (P-256), RS256 (RSA 2048), EdDSA "Coming soon", HS256 "Not recommended for production applications." Migration from legacy secret via dashboard; warning that components verifying against the legacy secret break on rotation. Client-side: `supabase.auth.getClaims()`. (https://supabase.com/docs/guides/auth/signing-keys)
- Verification example in TypeScript with `jose` `createRemoteJWKSet` + `jwtVerify`; claims `sub`, `role`, `iss`, `exp`, plus `aal`, `session_id`, `app_metadata`, `user_metadata`, `is_anonymous`. Python example: NOT FOUND on page (any JWKS-capable library works; not documented). (https://supabase.com/docs/guides/auth/jwts)
- Database Webhooks: "a convenience wrapper around triggers using the pg_net extension", INSERT/UPDATE/DELETE. Whether the webhook UI supports `auth.users`: NOT FOUND (docs only show `public` example). SQL triggers on `auth.users` are documented (profiles-table pattern), so an auth.users trigger calling pg_net is possible but not officially described. (https://supabase.com/docs/guides/database/webhooks, https://supabase.com/docs/guides/auth/managing-user-data)
- Auth server-side hooks: see A5 (Before User Created, Custom Access Token, Send Email/SMS on Free+Pro).

### A8. EU data residency

- Regions include eu-west-1 (Ireland), eu-west-2 (London), eu-west-3 (Paris), eu-central-1 (Frankfurt), eu-central-2 (Zurich), eu-north-1 (Stockholm). "The region you choose also determines where your primary project data is stored." Caveat: "General regions deploy to *an* available AWS region within that broader area" (Europe general region may land in London/Zurich); "Region selection is a data-location control, not proof of regulatory compliance." (https://supabase.com/docs/guides/platform/regions)
- Auth architecture: "When you deploy a new Supabase project, we deploy an instance of this server alongside your database"; "Supabase Auth uses the auth schema in your Postgres database to store user tables and other information." → auth data lives in the project's Postgres, i.e. the chosen region (inferred from these two statements; no explicit "Auth data stays in region" sentence found). (https://supabase.com/docs/guides/auth/architecture)

### A9. SvelteKit SDK

- Official guide uses `@supabase/supabase-js` + `@supabase/ssr` with `hooks.server.ts`, `+layout.ts`/`+layout.server.ts`, `getClaims()` for page protection. Static/prerendered (adapter-static) and client-only usage are not addressed. (https://supabase.com/docs/guides/auth/server-side/sveltekit)
- Rate limits relevant to a static site/desktop app: built-in email provider "2 emails per hour"; configurable with custom SMTP or the Send Email hook; OTP/magic link 60 s window; token refresh "150 requests per 5 minutes, with bursts up to 30". (https://supabase.com/docs/guides/auth/rate-limits)

### Key takeaways for a Tauri desktop app + website (Supabase)

- Cost is $0 (Free) or $25/mo (Pro incl. Micro Postgres) at every MAU level asked; overage only above 100k MAU on Pro.
- Custom schemes like `wingman://` are explicitly allowed in the Redirect URL allow list; loopback `http://localhost:*` also allowed. Use `flowType: 'pkce'`, `skipBrowserRedirect: true`, open `data.url` in the system browser, receive the deep link, call `exchangeCodeForSession(code)` (5-minute, single-use code). Custom `storage` adapter lets you persist the session/verifier outside the webview.
- Provider coverage is good (Google, Discord, GitHub, Apple, Microsoft, X, Twitch, magic link, OTP, password). Steam is not supported natively and does not fit the custom OAuth2/OIDC feature (OpenID 2.0); needs a server-side workaround.
- Sessions last indefinitely by default (refresh tokens never expire); limiting them needs Pro.
- EU residency is straightforward: choose eu-central-1; Auth runs alongside the DB.
- Backend verification via public JWKS (ES256/RS256) in any language; no official Python snippet.
- Production magic links require custom SMTP (built-in = 2 emails/hour).

---

## B. Firebase Authentication / Google Cloud Identity Platform

### B1. Pricing

**Firebase pricing page** (https://firebase.google.com/pricing)
- Spark (no-cost): "Other Authentication services" included; "50K MAUs"; SAML/OIDC "50 MAUs"; Phone Auth "Not applicable".
- Blaze: "Other Authentication services" — "No-cost up to 50K MAUs / Then Google Cloud pricing"; SAML/OIDC "No-cost up to 50 MAUs / Then Google Cloud pricing"; Phone Auth "Billed per SMS sent", see Identity Platform rates.

**Identity Platform pricing (verbatim table, no date shown on page)** (https://cloud.google.com/identity-platform/pricing)
- "Identity Platform charges per Monthly Active User (MAU) for most sign-in methods. Any account that has signed in within a given month is considered an active user. Inactive users are stored at no cost."
- Tier 1 providers: "Email, Phone, Anonymous, Social" — "0 count to 50,000 count $0.00 (Free)"; "50,000 count to 100,000 count $0.0055"; "100,000 count to 1,000,000 count $0.0046"; "1,000,000 count to 10,000,000 count $0.0032"; "10,000,000 count and above $0.0025" (per MAU per month). "Anonymous users are not included in the count of monthly active users if you've enabled automatic clean-up."
- Tier 2 providers: "OpenID Connect (OIDC), Security Assertion Markup Language (SAML)" — "0 count to 50 count $0.00 (Free)"; "50 count and above $0.015" per MAU per month, per project.
- Phone/MFA SMS: "The first ten SMS that you send per day are not billed." Per SMS: United States $0.01, Canada $0.01, India $0.07, Germany $0.10, United Kingdom $0.04, France $0.07, Netherlands $0.10, Austria $0.03, Switzerland $0.07, Spain $0.04, Italy $0.05, Poland $0.03, Sweden $0.05, Japan $0.03, Brazil $0.02, "All other regions (ZZ) $0.49".
- Sign in with Apple / Google / social providers: fall under Tier 1 "Social", i.e. free up to 50,000 MAU. No separate charge listed.
- No-cost tier limits without billing account (https://docs.cloud.google.com/identity-platform/quotas): "Tier 1 Daily Active Users: 3000 per day", "Tier 2 Daily Active Users: 2 per day", "Verification code SMS messages: Instrumentless: 10 sent SMS/day", "Email link sign-in emails: 5 emails/day", "New account creation: 100 accounts/hour for each IP address".
- Upgrade: "Firebase Authentication with Identity Platform" adds MFA, blocking functions, OIDC/SAML, multi-tenancy, IAP integration, BAA coverage, "A 99.95% uptime SLA"; "This upgrade does not require any migration—your existing client SDK and admin SDK code will continue to work as before." (https://docs.cloud.google.com/identity-platform/docs/product-comparison, https://firebase.google.com/docs/auth)
- Third-party confirmation of the tiers (secondary): Logto blog 2026-07-21 and metacto 2026-05-12 quote the same $0.0055 / $0.0046 / $0.0032 / $0.0025 tiers and $0.015 SAML/OIDC (https://blog.logto.io/firebase-authentication-pricing, https://www.metacto.com/blogs/the-complete-guide-to-firebase-auth-costs-setup-integration-and-maintenance).

**Cost at MAU levels (no phone auth)**
- 1,000 / 5,000 / 10,000 / 25,000 MAU: $0 on Spark or Blaze/Identity Platform (all under the 50,000 free tier). Caveat: without a billing instrument the "3000 Daily Active Users" cap applies, so at 25,000 MAU you likely need Blaze (still $0 until 50k MAU).
- First paid MAU at 50,001: e.g. 60,000 MAU = 10,000 × $0.0055 = $55/mo.

**Firebase Dynamic Links shutdown** (https://firebase.google.com/support/dynamic-links-faq)
- "On August 25th, 2025, Firebase Dynamic Links will shut down." Affected: email link authentication on iOS and Android, password reset/email verification flows on mobile, OAuth flows on Android SDK < v20.0.0. Web impact: "No. Firebase Dynamic Link deprecation only impacts handling incoming URLs on mobile devices." → web/desktop email-link sign-in is not affected. Migration: App Links / Universal Links, Firebase Hosting for asset-link files; `linkDomain` replaces `dynamicLinkDomain` ("Deprecated. Don't specify this parameter.") (https://firebase.google.com/docs/auth/web/email-link-auth)

### B2. Social login providers (https://firebase.google.com/docs/auth)

- Built-in: Email/Password, Email Link, Phone, Anonymous, Google, Apple, Facebook, Twitter, GitHub, Microsoft, Yahoo, Play Games (Android), Game Center (iOS), Custom Auth.
- Identity Platform upgrade required: SAML ("web only"), OpenID Connect ("OpenID Connect providers not natively supported by Firebase").
- Checklist: Google yes, GitHub yes, Apple yes, Microsoft yes, X/Twitter yes, email link yes, password yes; email OTP (6-digit code) NOT FOUND (only email link); Discord NO built-in, Twitch NO built-in, Steam NO built-in. Discord/Twitch would need the generic OIDC provider (requires the provider to expose an OIDC discovery document — not verified here) or custom tokens.
- Generic OIDC (https://firebase.google.com/docs/auth/web/openid-connect): "OpenID Connect authentication is only available in upgraded projects." Needs Client ID, Client Secret, Issuer ("when appended with /.well-known/openid-configuration"). Use `new OAuthProvider('oidc.example-provider')` with popup/redirect, or `provider.credential({ idToken })` + `signInWithCredential`.
- Custom tokens (https://firebase.google.com/docs/auth/admin/create-custom-tokens): `createCustomToken(uid, additionalClaims)` via Admin SDK; client calls `signInWithCustomToken()`; "These tokens expire after one hour." This is the route for Steam: verify Steam OpenID on your backend/Cloud Function, mint a custom token. Note: "A Cloud Functions event is not triggered when a user signs in for the first time using a custom token." (https://firebase.google.com/docs/functions/auth-events)

### B3. Desktop app support

- Web SDK popup/redirect in Electron: issue #1334 (opened 2018-10-24, "Cannot set property 'href' of null", still open/feature-request) (https://github.com/firebase/firebase-js-sdk/issues/1334); issue #6444 (2022-07-18): v9 SDK detects Electron renderer as Node.js (`_isNativeEnvironment()` true), blocking `signInWithPopup`/`signInWithRedirect`; reporter's workaround patches `global.process[Symbol.toStringTag]`; no maintainer resolution visible (https://github.com/firebase/firebase-js-sdk/issues/6444). Medium "Using Firebase in Electron" article: could not fetch (403).
- Authorized domains: `continue_uri`/redirect must be in the authorized domains list; no mention of custom schemes, Electron or localhost on the redirect best-practices page (https://firebase.google.com/docs/auth/web/redirect-best-practices). "In projects created after April 28, 2025, Firebase Authentication no longer includes localhost as an authorized domain by default." (https://firebase.google.com/docs/auth/web/email-link-auth). The only documented non-http authorized origin is `chrome-extension://CHROME_EXTENSION_ID`; popup methods "aren't directly compatible with Chrome extensions, because they require code to be loaded from outside of the extension package" (https://firebase.google.com/docs/auth/web/chrome-extension). Custom schemes like `wingman://` in authorized domains: NOT FOUND in docs.
- Recommended pattern for desktop (documented for extensions, used by community for Tauri): do the provider OAuth yourself (system browser + loopback), then `signInWithCredential(GoogleAuthProvider.credential(idToken))`, or mint a custom token on your backend.
- Tauri example (third-party): igorjacauna/tauri-firebase-login — `tauri-plugin-oauth` localhost server on random port, Google OAuth URL, `signInWithCredential`; requires `http://localhost` as authorized redirect URI in the Google Cloud OAuth client; repo archived 2024-02-09 (https://github.com/igorjacauna/tauri-firebase-login).
- Official Firebase Tauri/Electron guide: NOT FOUND.

### B4. Session lifetime (https://firebase.google.com/docs/auth/admin/manage-sessions)

- "Firebase ID tokens are short lived and last for an hour".
- Refresh tokens expire only when: "The user is deleted", "The user is disabled", "A major account change is detected for the user. This includes events like password or email address updates." Admin SDK `revokeRefreshTokens()`; "Password resets also revoke a user's existing tokens". → users stay signed in indefinitely otherwise.

### B5. Custom claims (https://firebase.google.com/docs/auth/admin/custom-claims)

- "The payload must not exceed 1000 bytes"; "Passing a custom claims payload greater than 1000 bytes will throw an error." Avoid OIDC/Firebase reserved names. Propagate on sign-in, token refresh, or `getIdToken(true)`. "Custom claims are only used to provide access control. They are not designed to store additional data." Other data → Firestore/RTDB/own DB.
- Blocking functions can also set `customClaims` (persisted) and `sessionClaims` (per session) (https://firebase.google.com/docs/auth/extend-with-blocking-functions).

### B6. Bulk import / account linking

- `importUsers()`: "Up to 1000 users can be imported in a single API call." Password hashes supported (HMAC_SHA256, modified Firebase scrypt, standard scrypt, etc.); "If no password hashing is needed (phone number, custom token user, OAuth user etc.), do not provide hashing options." "Ability to import users with custom claims directly in bulk." Partial-failure result summary returned. (https://firebase.google.com/docs/auth/admin/import-users)
- Account linking settings (https://docs.cloud.google.com/identity-platform/docs/link-accounts): "Link accounts that use the same email: Identity Platform will raise an error if a user tries to sign in with an email that's already in use. Your app can catch this error, and link the new provider to their existing account." vs "Create multiple accounts for each identity provider". Trusted providers: "Email providers are considered authoritative for all addresses related to their hosted email domain. This means a user logging in with an email address hosted by the same provider will never raise this error (for example, signing in with Google using an @gmail.com email, or Microsoft using an @live.com or @outlook.com email)." Google sign-in doc: "A user logging in with Google will never cause this error when their account is hosted at Google even if they signed up for their account with a password or a social IDP." (https://firebase.google.com/docs/auth/web/google-signin). Otherwise `auth/account-exists-with-different-credential` → sign in with existing provider, then `linkWithCredential()`.
- Forcing a password reset for imported users: NOT FOUND / not fetched (Admin SDK password-reset-link docs were not retrieved).

### B7. Backend verification / triggers

- `verifyIdToken()` (Node, Java, Python, Go, C#). Manual: RS256, keys from `https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com`, `iss` = `https://securetoken.google.com/<projectId>`, `aud` = project ID, `sub` = uid, `exp`/`iat`/`auth_time` checks. (https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- Auth event triggers `onCreate`/`onDelete`: "Cloud Functions for Firebase (2nd gen) does not provide support for the events and triggers described in this guide" (1st gen only). (https://firebase.google.com/docs/functions/auth-events)
- Blocking functions `beforeUserCreated`, `beforeUserSignedIn`, `beforeSendEmail`, `beforeSendSMS`: require "Firebase Authentication with Identity Platform"; "must respond within 7 seconds"; can modify `displayName`, `disabled`, `emailVerified`, `photoURL`, `customClaims`, `sessionClaims`. (https://firebase.google.com/docs/auth/extend-with-blocking-functions)

### B8. EU data residency

- Firebase privacy page: "The Firebase Authentication service is run only from US data centers. As a result, Firebase Authentication processes data exclusively in the United States." Retention: IPs "for a few weeks", other data until user deletion, then removed within 180 days. (https://firebase.google.com/support/privacy)
- Locations page lists Firestore/RTDB/Storage/Functions etc. as regional; Authentication is absent from the location tables. (https://firebase.google.com/docs/projects/locations)
- Official roadmap (Firebase UserVoice, PM Micah Baker): status "Started"; 2025-05-05: "regionalized Firebase Auth by end of 2025" expected; 2025-06-23: "Full regionalization for Firebase Authentication ... still expected to reach preview in Q4 this year"; 2026-04-14: "The first thing that will be available is pass-through authentication from an external IDP, and Firebase Auth will not store any user records. This is ready for early access." No statement that regional EU storage of Firebase Auth user records is GA. (https://firebase.uservoice.com/forums/948424-general/suggestions/46591651-firebase-authentication-for-eu)
- Identity Platform EU-regional option: NOT FOUND in fetched docs.

### B9. SvelteKit SDK

- No official SvelteKit SDK; use the JS SDK. Community: sveltejs/kit issue #1962 (Firebase SDK 9 build errors with adapter-static, old), `svelte-adapter-firebase`, `sveltekit-fireauth`, session-cookie templates (search results only; https://github.com/sveltejs/kit/issues/1962, https://github.com/AlanAcDz/sveltekit-fireauth — not fetched).

### Key takeaways for a Tauri desktop app + website (Firebase)

- Cost: $0 at 1k–25k MAU, first charge above 50k MAU ($0.0055/MAU); social/Apple/Google are Tier 1 (free tier). Discord/Twitch/Steam need Identity Platform OIDC (if the provider exposes OIDC discovery) or custom tokens minted by your backend.
- Desktop is the weak spot: `signInWithPopup`/`signInWithRedirect` are broken/unsupported in Electron-like environments and custom schemes are not documented as authorized domains; the workable path is system browser + loopback (`tauri-plugin-oauth`) + `signInWithCredential`, or your own backend + custom tokens. This means you maintain provider-specific OAuth code yourself.
- Sessions: refresh tokens do not expire unless revoked; ID token 1 hour.
- Backend verification is easy (Admin SDK or x509 certs); user event triggers are 1st-gen only; blocking functions require the Identity Platform upgrade.
- EU data residency: Firebase Auth "processes data exclusively in the United States"; regionalization still not shipped as of the last official update (April 2026), only pass-through external IdP early access.
- No SvelteKit-specific SDK; email-link sign-in on web/desktop is unaffected by the Dynamic Links shutdown, but the continue URL must be an https authorized domain (no custom scheme).
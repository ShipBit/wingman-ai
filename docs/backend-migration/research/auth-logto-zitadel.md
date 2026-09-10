text
I have everything I can get from live sources (about 55 fetches; the shared WebSearch budget ran out partway, so the rest was done by fetching official doc/pricing URLs directly). Report follows.

# Logto Cloud vs Zitadel Cloud — research report (fetched 2026-09-09)

Legend: every fact is followed by the URL it was fetched from. "NOT FOUND" = the page was fetched but did not contain the item; "could not fetch" = 404/unavailable. Third-party sources are labelled.

---

## A. Logto Cloud (logto.io)

### A1. Pricing

**Plans (official pricing page):**
- Free: "$0/mo" — "Up to 50,000 MAU, 50K tokens". Pro: "From $24/mo" (labelled "Best Value") — "Unlimited MAU, 50K included tokens". Enterprise: "Contact us", "Custom resource quota". (https://logto.io/pricing)
- The "$16/mo" figure is outdated: the Sept 1 2025 blog states "Old base price: $16/month; New base price: $24/month (effective October 1)", and the included tokens on both Free and Pro were "reduced from 100k to 50k"; unit price "remains: $0.08 per 100 tokens". RBAC became a Pro-only add-on ($32/mo), tenant members $8/member/mo (1 included), third-party apps $8/app/mo. (https://blog.logto.io/pricing-sep-2025)

**Token-based billing (yes, Logto bills by access tokens, not MAU):**
- "only access tokens are counted" (ID tokens and refresh tokens excluded). Access tokens are issued for: "user sign-in, backend API authorization (RBAC), organization authorization, Machine-to-Machine requests, token exchanges, and refresh token usage." Overage: "$0.08 per 100 tokens" beyond 50,000/month. Bill formula: "Your next bill = $24 (base price) + add-on cost (unbilled usage) + add-on cost (next cycle charge)"; pro-rated on activation/deactivation. Upgrade path "Free to Pro: Available for upgrade when usage exceeds quotas". (https://docs.logto.io/logto-cloud/billing-and-pricing)
- "Refresh tokens are no longer counted toward your token consumption. We only bill for access tokens now" (≈50% reduction). (https://blog.logto.io/pricing-sep-2025)
- Note: every refresh-token use still mints a new access token, which IS counted.

**Add-ons (Pro), verbatim from pricing page / billing docs:**
- Machine-to-machine apps: 1 included, "$8 each extra"; API resources: 3 included, "$4 each extra"; Custom domains: 1 included, "$48 for up to 10 domains"; Enterprise SSO: "$48 per connector"; MFA: "$48 for all factors"; Organizations: "$48"; RBAC: "$32"; Advanced security bundle: "$48"; SAML apps "$96" each; OIDC/OAuth third-party apps "$8"; Tenant members: 1 included, "$8 each extra". (https://logto.io/pricing ; https://docs.logto.io/logto-cloud/billing-and-pricing)
- Plan comparison rows: Custom token claims (Custom JWT) — Free: not available, Pro: included (no separate add-on price listed); Webhooks — Free "1", Pro "10"; Social connectors — Free "3", Pro "Unlimited*"; Applications — Free "3", Pro "Unlimited*"; API resources — Free: not available; Audit log retention — Free "3 days", Pro "14 days"; Support — Free community chat, Pro "Email support (48h response)"; Enterprise: "Custom data region", SLA, compliance. (https://logto.io/pricing)
- Extra tenants: Free plan "up to 10 tenants"; Dev tenants are free with premium features but auto-delete users after 90 days; Prod tenants need Free or Pro subscription. (https://docs.logto.io/logto-cloud/tenant-settings)
- History: add-ons started charging Aug 9 2024 (new users) / Sep 1 2024 (existing). (https://blog.logto.io/pricing-add-ons)

**Cost estimates (Pro plan, USD/month). ASSUMPTIONS, clearly mine:** Logto bills access tokens, so cost depends on tokens per user, not MAU. I model three usage profiles: 10 / 30 / 100 access tokens per MAU per month (10 ≈ one token per app launch a few times a week; 30 ≈ one refresh per day; 100 ≈ frequent refreshes / multiple API resources). Math: tokens = MAU × profile; overage = max(0, tokens − 50,000) / 100 × $0.08; total = $24 + overage.

| MAU | 10 tok/user | 30 tok/user | 100 tok/user |
|---|---|---|---|
| 1,000 | 10K tok → $24 | 30K → $24 | 100K → 50K over → +$40 → **$64** |
| 5,000 | 50K → $24 | 150K → +$80 → **$104** | 500K → +$360 → **$384** |
| 10,000 | 100K → +$40 → **$64** | 300K → +$200 → **$224** | 1M → +$760 → **$784** |
| 25,000 | 250K → +$160 → **$184** | 750K → +$560 → **$584** | 2.5M → +$1,960 → **$1,984** |

Add for Wingman if wanted: MFA +$48, Organizations +$48. Custom domain (1) and Custom JWT are included in Pro. Free plan could technically cover 1,000–5,000 MAU at ≤10 tokens/user, but Free caps social connectors at 3 and has no Custom JWT/MFA/API resources (https://logto.io/pricing).

### A2. Social login providers

- Connector packages in the OSS repo: google, github, gitlab, facebook, linkedin, discord, slack, x, apple, amazon, patreon, huggingface, kook, wechat (native/web), wecom, dingtalk, feishu, qq, kakao, naver, line, alipay (native/web), xiaomi; standards: oauth2, oidc, saml, azuread; plus email/SMS connectors (smtp, logto-email, aws-ses, mailgun, sendgrid, postmark, twilio, vonage, etc.). **No connector-twitch, no connector-steam.** (https://github.com/logto-io/logto/tree/master/packages/connectors)
- Integrations hub lists social: Alipay, Amazon, Apple, Discord, Facebook, GitHub, GitLab, Google, Hugging Face, Kakao, Line, LinkedIn, Naver, Patreon, Slack, WeChat, X (Twitter), OAuth 2.0 (Social), OIDC (Social). Enterprise SSO: Microsoft Entra ID (OIDC & SAML), Google Workspace, OIDC, Okta, SAML. "Twitch, Steam, TikTok, Xero do not appear on this page." (https://docs.logto.io/integrations)
- Checklist: Google yes; Discord yes; GitHub yes; Apple yes; Microsoft — social connector "Microsoft Azure AD" (https://docs.logto.io/connectors/social-connectors) / Entra ID as Enterprise SSO ($48/connector); X/Twitter yes; **Twitch: not built-in → use the standard OAuth 2.0 connector**; **Steam: not built-in; OpenID 2.0 not mentioned anywhere** (standard connectors are OAuth 2.0 and OIDC only) (https://docs.logto.io/connectors/social-connectors ; https://docs.logto.io/integrations).
- Email magic link / email OTP / password: NOT FOUND on the pages I fetched (the sign-in-experience page was not fetched); the migration docs confirm password-based accounts exist (https://docs.logto.io/user-management/user-migration). Treat as unverified from this run.
- Custom OAuth2/OIDC: "official Logto connector for OAuth 2.0 protocol" and OIDC standard connectors exist. (https://docs.logto.io/connectors/social-connectors)

### A3. Desktop app support

- Application types listed: Native app, SPA, Traditional web app, M2M, Third-party OIDC/OAuth app, SAML app, Protected app. The overview page gives no native-platform detail. (https://docs.logto.io/integrate-logto)
- Native quick starts: Android, iOS (Swift), Flutter, Expo, Capacitor. SPA: React, Vue, Angular, Vanilla JS. Web: Next.js, Nuxt, SvelteKit, Express, Go, Python, PHP, Ruby, Spring Boot, .NET. "Svelte, Electron, and Tauri do not appear." (https://docs.logto.io/quick-starts)
- Custom-scheme redirects are documented for mobile: iOS "io.logto.app://callback" registered in Info.plist, v2 uses ASWebAuthenticationSession (system browser); universal links also allowed; "no mention of macOS support". (https://docs.logto.io/quick-starts/swift). Android: "io.logto.android://io.logto.sample/callback", v3 uses Chrome Custom Tabs. (https://docs.logto.io/quick-starts/android). Flutter SDK: "compatible with Flutter applications on iOS, Android, and Web platforms. Compatibility with other platforms has not been tested." (https://docs.logto.io/quick-starts/flutter)
- PKCE: search snippet from docs: native apps "are public clients and cannot keep secrets, so instead of an app secret, Logto protects them with PKCE, strict redirect URI/CORS validation, short-lived access tokens, and refresh-token rotation" (search-result snippet attributed to docs.logto.io; exact page not fetched).
- Loopback (http://127.0.0.1:port) for the Native type: NOT FOUND — the application-data-structure page documents wildcard rules only for SPA/Traditional web and "does not specify whether Native apps support custom schemes or http://localhost". (https://docs.logto.io/integrate-logto/application-data-structure)
- Vanilla JS SDK `@logto/browser` is "framework-agnostic", uses `http://localhost:3000/callback` in examples, `getAccessToken(resource)` auto-refreshes; no explicit Electron/Tauri statement. (https://docs.logto.io/quick-starts/vanilla-js)
- Tauri/Electron guides: none found on docs.logto.io (search + quick-starts page). (https://docs.logto.io/quick-starts)

### A4. Session lifetime

- `refreshTokenTtlInDays`: default 14 days, **maximum 180 days**; applies to Native, Traditional web, SPA. `rotateRefreshToken`: default true; public clients rotate on every refresh, others when ≥70% TTL elapsed; "One-year maximum per refresh token chain"; "For public clients, it is highly recommended to keep refresh token rotation enabled". `alwaysIssueRefreshToken`: Traditional web/SPA only, default off, "not compatible with OpenID Connect". `idTokenTtl`: not documented there. (https://docs.logto.io/integrate-logto/application-data-structure)
- So 30–90+ days stay-logged-in: yes, up to 180 days per refresh token, with rotation extending the chain up to one year.
- "Session max"/access-token TTL default: NOT FOUND in fetched pages. Webhook event `Grant.LimitExceeded` implies a "max concurrent authenticated devices" setting exists. (https://docs.logto.io/developers/webhooks/webhooks-events)

### A5. Custom user metadata + Custom JWT

- `custom_data`: "stores additional user info not listed in the pre-defined user properties"; set via `PATCH /api/users/{userId}/custom-data` (Management API), `PATCH /api/my-account` (Account API), Console, or sign-up profile collection; update overwrites (no merge); "DO NOT put sensitive data in custom_data". Accessible via Custom JWT claims. (https://docs.logto.io/user-management/user-data)
- Custom token claims: "add custom claims within access tokens (JWT / Opaque token)" by implementing `getCustomJwtClaims`; built-in claims cannot be overridden; self-hosted scripts run with server privileges. (https://docs.logto.io/developers/custom-token-claims)
- Plan: Custom token claims — Free: not available; Pro: included (no extra add-on price shown). (https://logto.io/pricing)

### A6. Bulk import / migration / account linking

- Import via Management API `POST /api/users`; `passwordAlgorithm` values: Argon2, SHA256, SHA1, MD5, Bcrypt, Legacy; Legacy format `["hash_algorithm", ["arg1", ...], "expected_hashed_value"]` with `@` placeholder, pbkdf2 example given; password fields appear optional (import without password not explicitly stated); rate-limited (example uses 200 ms delay; "For 100k+ users, contact Logto"); social identities need the "Link social identity to user" API. (https://docs.logto.io/user-management/user-migration)
- Account linking: "Automatic account linking" toggle in Console > Sign-in experience: "automatically link the social account to the existing account based on a matching email or phone number"; if off, user is prompted to link or create; "Only verified email addresses and phone numbers are accepted as identifiers" (requires `email_verified` claim from provider). (https://docs.logto.io/end-user-flows/sign-up-and-sign-in/social-sign-in)

### A7. Backend verification + webhooks

- JWKS: `https://<your-logto-endpoint>/oidc/jwks`; issuer `https://<your-logto-endpoint>/oidc`; "Logto doesn't allow customizing the JWKS URI or issuer". Verify signature, `iss`, `aud` (= API resource indicator), `exp`, `scope`, `organization_id`. Examples: Node/TS (jose), Python (PyJWT + PyJWKClient), Go, Java, .NET, PHP, Ruby, Rust. (https://docs.logto.io/authorization/validate-access-tokens)
- Webhooks: async only ("cannot allow, block, or modify the current authentication flow"). Events: PostRegister, PostSignIn, PostResetPassword; User.Created/Deleted/Data.Updated/SuspensionStatus.Updated; Role.*, Scope.*, Organization.*, OrganizationRole.*, OrganizationScope.*, TrustedDevice.Created/Deleted; Identifier.Lockout, Message.RateLimited, Grant.LimitExceeded. (https://docs.logto.io/developers/webhooks ; https://docs.logto.io/developers/webhooks/webhooks-events). Quota: Free 1, Pro 10 webhooks. (https://logto.io/pricing)

### A8. EU data residency

- Regions selectable at tenant creation: "Europe (Netherlands)", "West US (Arizona)", "Australia (Australia East)", "Japan (Japan East)"; region "cannot be changed after the tenant is created"; extra cost: not specified. (https://docs.logto.io/logto-cloud/tenant-settings). Enterprise: "Custom data region". (https://logto.io/pricing)

### A9. Other

- OSS: license MPL-2.0, 14.5k stars, self-host via Docker Compose or Node.js + PostgreSQL. (https://github.com/logto-io/logto). Cloud-only: multi-tenant console, team members, console MFA, Protected App, built-in email service, "Bring your UI", IdP-initiated SSO, SAML apps beyond 3, branding removal. (https://docs.logto.io/logto-oss)
- SvelteKit SDK `@logto/sveltekit`: server-side (`hooks.server.ts` `handleLogto` with endpoint/appId/appSecret + cookie encryption key); `locals.logtoClient.getAccessToken(resource)`. (https://docs.logto.io/quick-starts/sveltekit). Vanilla `@logto/browser` for static/client-side. (https://docs.logto.io/quick-starts/vanilla-js)
- Stability signals: pricing changed Jul 2024 (add-ons) and Sep 2025 (+50% base, −50% tokens, RBAC to add-on). (https://blog.logto.io/pricing-add-ons ; https://blog.logto.io/pricing-sep-2025)

---

## B. Zitadel Cloud (zitadel.com)

### B1. Pricing

**Plans (official pricing page):** FREE "US$0/Month" — "100 Daily Active Users", "Unlimited Organizations", "Store unlimited Users", "3 identity providers", "Custom workflows", "Service Users / Agents". PRO "US$100/Month" — "Start with 25'000 Daily Active Users per month included", "Custom domain included", "99.5% uptime guarantee", "1h response SLO". ENTERPRISE — custom, "Unlimited Daily Active Users", TAM, volume discounts, "99.99% uptime guarantee". All tiers: data residency "EU, US, Switzerland, Australia". (https://zitadel.com/pricing)

**Detailed table (zitadel.com/pricing/detail):**
- DAU: Free 100; Pro 25,000 included, additional "$50" per unit — **the unit size (per 1,000? per 25,000?) was not present in the fetched text; verify on the page**. External IdPs: Free 3, Pro 3 included, additional "$100" per unit. Custom domains: Free 1, Pro 1 included, additional "$50" upfront. Management API requests: Free 5,000, Pro 500,000 included, "$100" per additional unit. Audit trail: Free 1 day, Pro 2 weeks; logs: Free 30 min, Pro 1 day. Administrators: Free 1, Pro 3 (+"$20" each). Support: Free community; Pro professional, SLA "up-to 99.99%"; Enterprise 24/7, "as low as 30 minutes". (https://zitadel.com/pricing/detail)
- Extended Support and SLA add-on: "$999". Pro is credit-card, month-to-month; Enterprise adds invoice/ACH and 8h private support. Article dated April 25, 2026. (https://help.zitadel.com/zitadel-cloud-pro-vs.-enterprise-which-plan-is-right-for-you)
- Billing cycle: monthly; "Your invoice will contain both pre-paid items for the current billing period and usage-based charges from the last billing period." (https://help.zitadel.com/pricing-and-billing-of-zitadel-services). "You will only pay for what you use ... You don't have to commit to a usage quota per month." (https://help.zitadel.com/what-if-i-dont-use-my-dau-or-external-identity-providers)
- Actions/regions add-ons: no separate prices; "Custom workflows" is listed on Free (https://zitadel.com/pricing); Pro includes "Workflows (Actions)" (https://help.zitadel.com/zitadel-cloud-pro-vs.-enterprise-which-plan-is-right-for-you).

**DAU definition (exact wording, important):** "Sum of DAUs" model: "Monthly Billing Total = Day 1 DAUs + Day 2 DAUs + ... + Day 31 DAUs". A user is active on a day if they perform an authentication event: login (local or external IdP), **"Refreshing a token when an application keeps a user logged in"**, or service-user auth. "Each unique user is only counted once per day, no matter how many times they log in or refresh tokens." (https://help.zitadel.com/how-is-daily-active-users-calculated)
- Zitadel's own MAU→DAU conversion: "1'000 MAU x 22 logins per month = 22'000 DAU" (business app, one login per workday). (https://help.zitadel.com/how-can-i-convert-monthly-active-users-mau-to-daily-active-users-dau)

**Cost estimates (Pro, USD/month). ASSUMPTIONS, clearly mine:** Zitadel's "DAU" is a monthly sum, so the requested "DAU ≈ MAU/3" (average daily actives) equals a monthly DAU-sum of MAU × 10 (30 days × 1/3). I show three profiles: 10 active days/user (= DAU≈MAU/3), 22 (Zitadel's business figure), 30 (daily use — likely for a desktop app that refreshes tokens every day it's opened). Because the overage unit is unverified, I show both readings: (a) $50 per 25,000-DAU block (consistent with the included block and the "$100 per unit" API-request pricing), (b) $50 per 1,000 DAU. Math: over = max(0, MAU × days − 25,000); blocks rounded up.

| MAU | DAU-sum (10 / 22 / 30 days) | (a) $50 per 25K block | (b) $50 per 1K |
|---|---|---|---|
| 1,000 | 10K / 22K / 30K | $100 / $100 / $150 | $100 / $100 / $350 |
| 5,000 | 50K / 110K / 150K | $150 / $300 / $350 | $1,350 / $4,350 / $6,350 |
| 10,000 | 100K / 220K / 300K | $250 / $500 / $650 | $3,850 / $9,850 / $13,850 |
| 25,000 | 250K / 550K / 750K | $550 / $1,150 / $1,550 | $11,350 / $26,350 / $36,350 |

Add: external IdPs beyond 3 at $100 each — for Google + Discord + GitHub + Apple + Microsoft + X + Twitch (7) that is **+$400/month** on Pro (https://zitadel.com/pricing/detail). The article "How are external identity providers billed?" (defining "active" IdP) could not be fetched (404 on guessed slug), so whether unused IdPs count is unverified.

### B2. Social login providers

- Documented IdPs: Google, GitHub, GitLab, Apple, Entra ID, Auth0, Okta, Keycloak, LinkedIn, MockSAML; generic: Generic OIDC, Generic SAML, JWT IdP, LDAP. "Steam, OpenID 2.0, Discord, Twitter/X, Twitch, Facebook, Amazon, Slack are not mentioned." (https://zitadel.com/docs/guides/integrate/identity-providers/introduction)
- SDK/example list mentions "less than 150 External Identity Providers" threshold for Pro. (https://help.zitadel.com/zitadel-cloud-pro-vs.-enterprise-which-plan-is-right-for-you)
- Generic OAuth provider: the LinkedIn-via-generic-OAuth guide and the AddGenericOAuthProvider API page both 404'd on guessed slugs → could not fetch. The introduction page confirms generic OIDC/JWT/SAML/LDAP; Generic OAuth is not confirmed from fetched pages in this run.
- Steam (OpenID 2.0): not supported by any listed provider. A possible bridge is the documented "JWT IdP" (your backend does Steam OpenID and issues a JWT) — the JWT IdP exists (https://zitadel.com/docs/guides/integrate/identity-providers/introduction) but I did not fetch its detail page.
- Email OTP / magic link / password: NOT FOUND in fetched pages (login-settings page not fetched).

### B3. Desktop app support

- Native app type: "Installed on a thin client, such as a smartphone or desktop computer." Examples "Android, iOS, Electron, and Tauri applications." Auth: "Authorization Code Flow with PKCE". Redirect URIs: "Native applications can use custom protocols (e.g., `myapp://`) instead of `http/https`." Development Mode: "Enables non-HTTPS protocols during local development" and "Allows the use of glob patterns in Redirect URIs". (https://zitadel.com/docs/guides/manage/console/applications-overview)
- Recommended flows: "Authorization Code with Proof Key of Code Exchange (PKCE)" for "Native, Mobile, or Desktop applications". (https://zitadel.com/docs/guides/integrate/login/oidc/oauth-recommended-flows)
- Flutter example: Native app type; web redirect `http://localhost:4444/auth.html`, mobile custom scheme `com.example.zitadelflutter` (RFC 8252); must open login in the default browser. (https://zitadel.com/docs/examples/login/flutter)
- Electron loopback discussion (#5777): app used `http://127.0.0.1:45735/...` with dev mode, got "redirect_uri does not correspond"; maintainer: redirect URI is "compared with a string equals"; unresolved. Implication: exact-match loopback with a fixed port works only if registered exactly (or via Dev-mode glob). (https://github.com/zitadel/zitadel/discussions/5777)
- Tauri-specific guide: none on zitadel.com (only mention is the app-type example list).

### B4. Session lifetime

- Instance settings expose "Access Token Lifetime, ID Token Lifetime, Refresh Token Expiration, Refresh Token Idle Expiration" (no values on the page). Login lifetimes: Password Check, External Login Check, Multi-factor Init, Second Factor Check, Multi-factor Login Check. (https://zitadel.com/docs/guides/manage/console/default-settings)
- Defaults (source config): AccessTokenLifetime 12h, IdTokenLifetime 12h, **RefreshTokenIdleExpiration 720h (30 days), RefreshTokenExpiration 2160h (90 days)**; PasswordCheckLifetime 240h, ExternalLoginCheckLifetime 240h, MfaInitSkipLifetime 720h, SecondFactorCheckLifetime 18h, MultiFactorCheckLifetime 12h; "no explicit documented maximum-value constraints". (https://raw.githubusercontent.com/zitadel/zitadel/main/cmd/defaults.yaml)
- Maximum values: NOT FOUND (the UpdateOIDCSettings API page and instance-settings page 404'd). 30–90-day sessions are the default; longer needs raising Refresh Token Expiration (no documented cap found).

### B5. Custom user metadata + Actions v2

- Metadata: key/value, base64 values; `SetUserMetadata` (v2), delete via empty value or `DeleteUserMetadata`; reserved scope `urn:zitadel:iam:user:metadata` returns it in userinfo, or in the ID token with "User Info inside ID Token" app setting; claim `urn:zitadel:iam:user:metadata`. (https://zitadel.com/docs/guides/manage/customize/user-metadata)
- Actions v2: Targets (external HTTP endpoints) + Executions on Request / Response / Function / Event; functions PreUserinfo, PreAccessToken, PreSAMLResponse "receive user data, organization context, and user grants, returning custom metadata, claims, and log entries"; `ZITADEL-Signature` HMAC header; no plan restriction mentioned. (https://zitadel.com/docs/guides/integrate/actions/usage ; https://zitadel.com/docs/concepts/features/actions_v2). Function payload includes `user`, `user_metadata`, `org`, `application`. (https://zitadel.com/docs/guides/integrate/actions/testing-function). Plan: "Custom workflows" on Free (https://zitadel.com/pricing); "Workflows (Actions)" on Pro (https://help.zitadel.com/zitadel-cloud-pro-vs.-enterprise-which-plan-is-right-for-you).

### B6. Bulk import / migration / auto-linking

- Migration guide: Management API `ImportHumanUser` (single) and Admin API `ImportData` (bulk); "Existing password hashes can be imported if they use a supported hash algorithm"; "you always have the option to create a user in ZITADEL without password"; `passwordChangeRequired` flag; `isEmailVerified: true`; IdP links via `idps` (configId, externalUserId); OTP import via `otpCode`; no stated size limits. (https://zitadel.com/docs/guides/migrate/users)
- User v2 `AddHumanUser`: `email.isVerified`, `phone.isVerified`, `password.password` + `changeRequired`, `hashedPassword.hash` + `changeRequired`, `idpLinks[{idpId,userId,userName}]`, `metadata`, `totpSecret` (RFC 6238, HMAC-SHA-1, 30 s). (https://zitadel.com/docs/apis/resources/user_service_v2/user-service-add-human-user)
- Admin `ImportData`: bulk orgs/users/projects/apps; inputs dataOrgs / dataOrgsv1 / GCS / S3 / local; `timeout` field; per-record `errors` array. (https://zitadel.com/docs/apis/resources/admin/admin-service-import-data)
- Hash algorithms: "argon2i / id, bcrypt (Default), md5 (md5Crypt), md5plain, md5salted, phpass, drupal7, sha2 (crypt(3) SHA-256/512), scrypt, pbkdf2"; rehashed on first successful verification; md5/drupal7 verify-only. (https://zitadel.com/docs/concepts/architecture/secrets)
- IdP options: "Account creation allowed", "Account linking allowed" ("a linkable ZITADEL account has to exist already"), "Automatic creation", "Automatic update", "Use PKCE". (https://zitadel.com/docs/guides/integrate/identity-providers/generic-oidc ; .../google). API `providerOptions.autoLinking`: `AUTO_LINKING_OPTION_UNSPECIFIED` / `_USERNAME` / `_EMAIL` ("Links accounts with matching email addresses"). (https://zitadel.com/docs/apis/resources/admin/admin-service-add-google-provider)

### B7. Backend verification + webhooks/events

- Discovery `${CUSTOM_DOMAIN}/.well-known/openid-configuration`; JWKS `/oauth/v2/keys`; authorize `/oauth/v2/authorize`, token `/oauth/v2/token`, introspect `/oauth/v2/introspect`, userinfo `/oidc/v1/userinfo`, revoke `/oauth/v2/revoke`, end_session `/oidc/v1/end_session`; grants: code, refresh, client credentials, JWT profile, token exchange (RFC 8693); PKCE S256; "Keys rotate without prior notice". Access tokens can be opaque (Bearer) or JWT per app "Token settings". (https://zitadel.com/docs/apis/openidoauth/endpoints ; https://zitadel.com/docs/guides/manage/console/applications-overview)
- Targets: `restWebhook` (status only), `restCall` (status + body, `interruptOnError`), `restAsync` (fire-and-forget); `timeout` max 270 s; `payloadType` JSON/JWT/JWE; returns `signingKey`. Event executions on specific event types, groups, or all events. (https://zitadel.com/docs/apis/resources/action_service_v2/action-service-create-target ; https://zitadel.com/docs/guides/integrate/actions/usage)
- Python/TS examples: SDK page lists recommended OIDC libs (Authlib for Django/FastAPI/Flask; next-auth; @auth/sveltekit) but no dedicated token-validation code page was fetched. (https://zitadel.com/docs/sdk-examples/introduction)

### B8. EU data residency

- Regions: "United States (us-central1-a)", "European Union (europe-west3-c)", "Switzerland (europe-west6-c)", "Australia (australia-southeast1-c)" (GCP zone names); data-in-transit not guaranteed to stay in region. (https://help.zitadel.com/where-is-zitadel-cloud-data-stored). Pricing page: data residency "EU, US, Switzerland, Australia" on all tiers (https://zitadel.com/pricing). Data location chosen "When creating a new instance"; service description last updated April 5, 2024. (https://zitadel.com/docs/legal/service-description/cloud-service-description). Extra cost: not specified anywhere fetched.

### B9. Other

- OSS: license "AGPL-3.0 (with Apache 2.0 and MIT exceptions for specific directories)", 15.0k stars; "ZITADEL Cloud and self-hosted ZITADEL run the same codebase"; Docker Compose / Kubernetes. (https://github.com/zitadel/zitadel). Help center has "What should people who cannot use the AGPL 3.0 license do?" and "Can I move from ZITADEL Cloud to self-hosted?" (https://help.zitadel.com/account-subscription). Plans guide (April 28, 2026) describes OSS / Cloud Pro / Cloud Enterprise / Self-hosted Enterprise. (https://help.zitadel.com/choosing-the-right-zitadel-offering-a-guide-to-our-plans-and-models)
- SDKs: Zitadel-specific SDKs Go, .NET, React, Rust, Vue; Svelte/SvelteKit via "@auth/sveltekit"; no vanilla-JS, Electron or Tauri entries. (https://zitadel.com/docs/sdk-examples/introduction)

---

## Key takeaways for a Tauri desktop app + website

**Logto Cloud**
- Fits the provider list best: Google, Discord, GitHub, Apple, Microsoft, X are built-in; Twitch via the standard OAuth 2.0 connector; Steam is NOT possible via connectors (no OpenID 2.0) — you'd need your own Steam bridge and the Management API "link social identity" call (https://docs.logto.io/integrations ; https://docs.logto.io/user-management/user-migration).
- Pricing is predictable and cheap for a desktop app if you keep token churn low (long access-token life, few API resources): $24–$224/mo across 1K–10K MAU in the 10–30 tokens/user profiles; MAU itself is free. Custom JWT is included on Pro; MFA is +$48. Free is unusable for you (3 social connectors). (https://logto.io/pricing)
- Desktop story is thin: Native app type + custom-scheme redirects are documented only for mobile SDKs; no Tauri/Electron guide; loopback for Native not documented. Practical route: register a Native app, use tauri-plugin-deep-link with a custom scheme, and implement PKCE with `@logto/browser` or a generic OIDC client. Verify in the console whether a `myapp://` redirect is accepted before committing. (https://docs.logto.io/quick-starts ; https://docs.logto.io/integrate-logto/application-data-structure)
- Long sessions: refresh TTL up to 180 days, rotation with 1-year chain cap — good for "stay logged in". (https://docs.logto.io/integrate-logto/application-data-structure)
- Website: `@logto/sveltekit` needs a server (hooks.server.ts + app secret); for a static SvelteKit site use `@logto/browser` instead. EU region (Netherlands) available at no stated extra cost. Vendor has repriced twice in 14 months.

**Zitadel Cloud**
- Best explicit desktop support: Native app type literally lists Electron and Tauri, custom `myapp://` schemes allowed, Dev Mode allows http + glob redirects. Redirect matching is exact-string, so pick a fixed custom scheme rather than random loopback ports. (https://zitadel.com/docs/guides/manage/console/applications-overview ; https://github.com/zitadel/zitadel/discussions/5777)
- Provider list is weak for a gaming audience: only Google, GitHub, GitLab, Apple, Entra ID, plus generic OIDC/SAML/JWT/LDAP are documented; Discord, Twitch, X, Steam are not listed. Generic-OAuth support could not be confirmed from fetched pages. Each IdP beyond 3 costs $100/mo on Pro → ~+$400/mo for your 7 providers. (https://zitadel.com/docs/guides/integrate/identity-providers/introduction ; https://zitadel.com/pricing/detail)
- DAU billing punishes "always-logged-in" desktop apps: every day a client refreshes a token counts as a DAU, so 5K MAU using the app daily ≈ 150K DAU-sum/month vs 25K included. Overage unit is unverified ($50 per block — page did not expose the block size); under the plausible 25K-block reading Pro lands at $150–$650/mo for 1K–10K MAU before IdP add-ons, under the per-1K reading it explodes. Verify on https://zitadel.com/pricing/detail before deciding. (https://help.zitadel.com/how-is-daily-active-users-calculated)
- Strong on migration (many hash formats, `changeRequired`, `isVerified`, IdP links, TOTP import, bulk ImportData) and on auto-linking by email (`AUTO_LINKING_OPTION_EMAIL`). Actions v2 targets give signed webhooks and custom claims on all plans. Switzerland/EU regions on every tier; AGPL-3.0 self-host is a real exit path with the same codebase. Refresh default 90 days / 30 days idle, configurable.

Note for the caller: the session-wide WebSearch budget hit 200/200 mid-task (message received from `research-auth`), so later items were fetched by guessing official URLs; 404s are recorded above as "could not fetch" rather than filled from memory.
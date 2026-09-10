# Wingman AI Backend: Weg von Azure — Recherche und Vorschlag

Stand: 2026-09-10. Alle Preise und Feature-Aussagen stammen aus Live-Abrufen der Anbieterseiten am 2026-09-09/10. Die Rohberichte pro Anbieter liegen in `/tmp/wingman-arch/research/`. Wo eine Seite nicht abrufbar oder unklar war, steht das dabei.

---

## 1. Anforderungen (strukturiert aus dem Voice-Input)

**Weg von Azure, komplett.** Betroffen: Azure AD B2C (Auth), wingman-api (3 Azure-Functions-Deployments), Azure OpenAI, Azure AI Foundry Serverless (Mistral/Llama), Azure AI Speech (STT/TTS), slickgpt-api (ToS-Consent), wingman-webhook (PayPro-IPN), Application Insights.

**Economy-Layer.** Wir sind Reseller von AI-Nutzung zum Festpreis. Das neue Backend muss pro Nutzer: Verbrauch messen, Limits setzen, ab Schwelle auf ein günstigeres Modell herunterstufen, Reports liefern. Ob transparent für Nutzer oder unter der Haube, ist offen; beides muss möglich sein.

**Modellverwaltung.** Aktueller Modellkatalog, Remapping (Modell A → Modell B) ohne Code-Hacks, idealerweise Admin-Panel.

**Payment.** PayPro Global bleibt, Webhooks bleiben. Nur unsere Seite dahinter wird getauscht.

**Auth.** Viele Social Logins, einfacher Login im Client, kein täglicher Re-Login. Website-Signup und Subscribe vor dem Download.

**SlickGPT** ist tot. Nur der ToS-Consent-Teil muss ersetzt werden.

**Migration.** Alle User inklusive Subscriptions automatisiert übernehmen. Ein fester Klick-Flow ist okay. Niemand darf kündigen und neu abschließen müssen.

**Betrieb.** Kleines Team, keine Infra-Experten. Managed bevorzugt. Vercel Pro und Cloudflare Business sind vorhanden, aber nicht Pflicht.

---

## 2. Ist-Zustand (aus dem Code)

### Komponenten

| Komponente | Technik | Aufgabe |
|---|---|---|
| Wingman Client | Tauri 2 + SvelteKit statisch, `@azure/msal-browser`, Redirect `http://localhost:5173` | Login gegen B2C, liest Plan aus ID-Token-Claims, Subscribe-Seite, ToS-Dialog, Region-Auswahl |
| Wingman Core | Python-Sidecar | Bekommt das B2C-Access-Token als Secret `wingman_pro` über WebSocket, ruft wingman-api mit Bearer-Token |
| wingman-api | FastAPI auf Azure Functions, 3 Deployments (europe/usa/asia) | Validiert B2C-JWT, prüft Plan-Claims, proxyt `/ask`, `/transcribe-*`, `/generate-*-speech`, `/generate-image`, `/azure-voices`, `/inworld-voices`, PayPro-Endpunkte (subscription/suspend/renew), Modell-Allowlist |
| slickgpt-api | C#/.NET 6 Azure Function | `CheckTermsConsent` / `UpdateTermsConsent` schreiben `extension_WingmanTermsConsentDateTime` per Graph API |
| wingman-webhook | Azure Function, **nicht in den vier Repos** | PayPro-IPN → Graph API → B2C-Extension-Attribute |
| Azure AD B2C | Custom Policies, IdPs Google + GitHub + E-Mail/Passwort | 10 Extension-Attribute halten eine Kopie des Subscription-Zustands |
| PayPro Global | Hosted Checkout, Subscription-API, IPN | Führt die eigentlichen Subscriptions. Checkout bekommt `billing-email` und Custom-Feld `x-azure-user-id` (= B2C objectId) |
| wingman-website | SvelteKit auf Vercel | Pricing-Seite, `/api/pricing` wird vom Client geladen. Kein Login, kein Checkout-Bezug zum Account |
| Sonstiges | Inworld TTS (Ultra, direkt aus wingman-api), Aptabase, Cloudflare R2 für Updates, Legacy Paddle-API und Stripe-Portal-Link | |

### Befunde, die den Plan bestimmen

1. **Der 24h-Re-Login ist kein Bug in unserem Code, sondern ein hartes Microsoft-Limit.** Microsoft-Doku: "Single-page applications using the authorization code flow with PKCE always have a refresh token lifetime of 24 hours while mobile apps, desktop apps, and web apps do not experience this limitation." Der Client ist als SPA-Redirect-URI registriert. Kein Token-Setting ändert das. Entra External ID hat dasselbe Limit. Die Lösung ist unabhängig vom Anbieter: der Desktop-Client muss als Public Client (Native) mit Systembrowser und Loopback- oder Custom-Scheme-Redirect laufen, nicht als SPA im Webview.

2. **Die Subscriptions liegen bei PayPro, nicht in Azure.** B2C spiegelt nur. PayPro liefert alles, um den Zustand ohne B2C neu aufzubauen: `Subscriptions/GetList` (Status, Produkt, nextPayment), `Orders/GetOrderDetails` (Kunden-E-Mail, `customFields["x-azure-user-id"]`), `Subscriptions/ChangeCustomFields` (neue User-ID auf bestehende Subscription stempeln), IPN-URL im Dashboard umstellbar, IPN-Replay im Dashboard, `IS_RESENT`-Flag. Jede IPN trägt `CUSTOMER_ID`, `CUSTOMER_EMAIL`, `SUBSCRIPTION_ID`, `ORDER_CUSTOM_FIELDS`, `CHECKOUT_QUERY_STRING`.

3. **Passwörter sind aus B2C nicht exportierbar.** Graph gibt Passwort-Hashes nicht her. Social-Accounts (Google/GitHub) lassen sich über `identities[].issuer` + `issuerAssignedId` und die verifizierte E-Mail sauber übernehmen. E-Mail/Passwort-Nutzer brauchen einmalig Magic-Link oder Passwort-Reset. Das ist der "feste Flow", der okay ist.

4. **B2C wird seit 2025-05-01 nicht mehr an Neukunden verkauft, Support bis mindestens Mai 2030.** Kein Zeitdruck, aber kein Grund zu bleiben.

5. **PayPro-API ist IP-gebunden.** "API calls are verified by IP … send the list of your IP addresses to support." Serverless-Hosting ohne feste Egress-IP (Vercel Pro, Cloudflare Workers) braucht für die drei PayPro-API-Calls (GetDetails/Suspend/Renew) einen kleinen Relay mit fester IP oder eine Absprache mit PayPro.

6. **Login ist Pflicht für alle Nutzer, auch Free.** Core initialisiert den Tower nur nach `client_logged_in`. Die MAU-Zahl für den Auth-Anbieter ist also die Gesamtnutzerzahl, nicht die Zahl der Zahler.

7. **Nutzer-Configs referenzieren Azure-Stimmen per Name** (`en-US-JennyNeural` usw.). Ein Wechsel des TTS-Anbieters braucht eine Mapping-Tabelle oder eine Übergangszeit mit Azure Speech als letztem Azure-Dienst.

---

## 3. Auth-Anbieter

Bewertungskriterien: Desktop-Flow (PKCE, Systembrowser, Custom-Scheme/Loopback), lange Sessions, Social-Provider (Google, GitHub, Discord, Twitch, Apple, Microsoft, X; Steam ist OpenID 2.0 und geht nirgends nativ), Import ohne Passwort, Auto-Linking per E-Mail, Metadaten/Claims, JWKS, EU-Region, Preis.

| Anbieter | Preis bei 1k / 10k / 25k MAU | Desktop | Provider-Abdeckung | Import ohne PW + Auto-Link | EU | Urteil |
|---|---|---|---|---|---|---|
| **Supabase Auth** | $0 Free / $25 Pro (inkl. Postgres Micro, 100k MAU) | Custom-Scheme in Redirect-Allowlist, `flowType: pkce`, `skipBrowserRedirect` → Systembrowser; Community-Tauri-Beispiele | 19 Provider inkl. Discord, Twitch, X, Apple, Microsoft, GitHub, Google; Custom OAuth2/OIDC | `admin.createUser` ohne Passwort; Auto-Link bei verifizierter E-Mail | Frankfurt u. a. | **Empfehlung**: Auth + DB + Cron + Studio in einem, Refresh-Tokens laufen nicht ab |
| **Auth0** | $0 bis 25k MAU, dann Essentials $1.400 (20k-Tier) | Native-App-Typ, Loopback `http://127.0.0.1:port`, Refresh bis 1 Jahr | Google, GitHub, Apple, Microsoft, X nativ; Discord/Twitch als Custom OAuth2 | Bulk-Import ohne PW ja; **Auto-Link nicht first-party** (Essentials+, manuell) | EU-Tenant | Solide Alternative als reiner IdP, Preis-Klippe bei 25k |
| **WorkOS AuthKit** | $0 bis 1M MAU, Custom Domain $99/Mo praktisch nötig | Offizielles Electron-SDK, PKCE-Public-Client, `127.0.0.1` in Prod erlaubt, Device-Flow | **Kein Discord/Twitch/X** | Import ja, Linking bei verifizierter E-Mail | Nur US | Provider-Lücke disqualifiziert |
| **Kinde** | $0 bis 10.5k, $278/Mo bei 25k | Standard-OIDC/PKCE, Custom-Scheme dokumentiert (mobil) | Discord, Twitch, X, Apple, Microsoft ja | Import ohne PW → OTP beim ersten Login | Dublin/London | Okay, SvelteKit-SDK seit 2024 unbetreut |
| **Clerk** | $0–$25 (50k MRU) | **Cookie-gebundene Sessions brechen im Tauri-Webview** (Community-Plugin, OAuth dort kaputt) | Sehr breit | Ja | **Kein EU** | Nicht für Desktop |
| **Logto Cloud** | $24 Basis + $0,08 pro 100 Access-Tokens über 50k (Token-Billing) | Native-Typ, Custom-Scheme nur mobil dokumentiert | Discord, GitHub, X ja; Twitch via OAuth2-Connector | Ja | Niederlande | Möglich, zweimal umgepreist in 14 Monaten |
| **Zitadel Cloud** | $100 Pro + DAU-Summe; $100/IdP ab dem 4. | Nennt Tauri explizit | **Kein Discord/Twitch/X** | Ja, sehr gut | EU/CH | DAU-Modell bestraft Always-on-Desktop |
| **Better Auth** (self-hosted TS) | $0 Lizenz, Ops selbst | Offizielles Electron-Plugin, Community-Tauri-Plugin (83 Stars), Device-Flow | Alles inkl. Twitch/X; Steam über Community-Plugin | Direkte DB-Inserts | Wo gehostet | Volle Kontrolle, aber wöchentliche Releases, Breaking Minors, 14 Security-Advisories im Juni 2026 |
| Stytch | $0 bis 10k, danach $0,05–0,10/MAU (unverifiziert) | PKCE + Custom-Scheme, keine Desktop-Doku | Discord, Twitch, X ja | Ja | unklar | Twilio-Übernahme, Preis unklar |
| Firebase / GCIP | $0 bis 50k | Popup/Redirect in Electron-artigen Umgebungen kaputt | Kein Discord/Twitch | Ja | **Auth nur US** | Nein |
| Entra External ID | $0 bis 50k | **Gleiches 24h-SPA-Limit** | Kein GitHub/Discord/Twitch/X | Migrations-Tool "Preview" | EU | Nein |

**Empfehlung: Supabase Auth.** Gründe: ein Anbieter für Auth, Postgres, Cron, Studio; $25/Monat bis 100k MAU; alle gewünschten Provider außer Steam; Refresh-Tokens laufen per Default nie ab; Custom-Scheme-Redirects explizit erlaubt; Auto-Linking per verifizierter E-Mail eingebaut; Custom-Access-Token-Hook für Plan-Claims; EU-Region. Einschränkungen: eingebauter Mail-Versand nur 2 Mails/Stunde, also eigener SMTP (z. B. Resend) nötig; kein offizieller Tauri-Guide; Steam nur über serverseitigen Workaround.

**Zweite Wahl: Auth0** (Free bis 25k MAU, sehr reifer Native-Flow), wenn ihr Auth strikt vom Rest trennen wollt und die Preis-Klippe bei 25k akzeptiert.

### Desktop-Login-Flow (für jeden Anbieter gleich)

1. Client öffnet den Systembrowser mit der IdP-Authorize-URL (PKCE).
2. Redirect zurück per `wingman://auth/callback` (Tauri Deep-Link-Plugin) oder Loopback `http://localhost:5173/auth/callback` (der lokale Server läuft schon).
3. Client tauscht den Code gegen die Session.
4. **Neu:** Der Client holt sich vom eigenen Backend ein langlebiges, widerrufbares Geräte-Token (opak) und gibt das an Core statt des IdP-Tokens. Core muss dann nie refreshen. Dieses Token ist gleichzeitig der Schlüssel für die Nutzungsmessung pro Nutzer und Gerät.

Das löst den 24h-Bug endgültig, unabhängig vom IdP.

---

## 4. AI-Gateway / Economy-Layer

Kein Anbieter liefert alle drei Dinge zugleich: managed, Budgets pro Endnutzer mit Auto-Downgrade, und STT/TTS/Bild über denselben Endpunkt.

| Produkt | Kosten | Budgets pro Endnutzer | Downgrade-Regel | Remapping / Fallback | Audio + Bild | EU | Urteil |
|---|---|---|---|---|---|---|---|
| **Vercel AI Gateway** | 0 % Aufschlag, Credits, BYOK | Nur pro Team-Mitglied; Endnutzer nur Reporting ($0,075/1k User-IDs, $5/1k Queries) | Nein | Routing Rules (rewrite Modell A→B teamweit, per CLI), Fallbacks pro Request | STT (whisper, gpt-4o-transcribe, Gemini), TTS (tts-1/-hd), Bild, Streaming-Transkription | Regional Inference pro Request | **Empfehlung als Modell-Zugang** |
| **Cloudflare AI Gateway** | Kern kostenlos; Unified Billing 5 % oder BYOK 0 %; Logs 10M auf Workers Paid $5 | **Ja**: Spend Limits nach Custom-Metadata "split by value" (ein Rule-Slot = alle Nutzer), 429 bei Überschreitung | **Ja**: Dynamic Route mit Budget-Limit-Knoten → günstigeres Modell | Dynamic Routes im UI; Modell-Aliase | 24 Provider inkl. Deepgram, ElevenLabs, Cartesia, Azure OpenAI; OpenAI-Audio-Endpunkte nicht dokumentiert | Log-Lokalisierung EU **nicht** unterstützt; Kostenrechnung "best-effort" | Beste Budget-Logik, EU-Lücke bei Logs |
| **OpenRouter** | 5,5 % auf Credits; BYOK 0 % bis $25k/Monat, dann 5 % | Ja, wenn ein Key pro Nutzer: `limit` + `limit_reset` daily/weekly/monthly | Nein (nur Sperre) | `models`-Array pro Request; kein zentrales UI-Remapping | STT + TTS Endpunkte, Bild | EU-Routing nur Business (8 %) | Gut für Katalogbreite, Export nur Dashboard |
| **LiteLLM** (OSS, self-hosted) | $0 Lizenz + Container + Postgres | **Ja**: Customers/End-Users mit `max_budget`, `budget_duration`, TPM/RPM | Nein nativ (Fallback bei Fehler) | `model_group_alias`, Fallbacks, Admin-UI | `/audio/transcriptions` (Deepgram, Groq, OpenAI…), `/audio/speech` (ElevenLabs, Azure, Polly…), Bild | Wo gehostet | Vollständigster Economy-Layer, aber Ops |
| **Portkey** | Production $49/Mo (100k Logs) | Usage-Limit-Policies per `_user`-Metadata; Preistabelle nennt "Granular Budget & Rate Limits" aber nur unter Enterprise; Policy-Doku 404 | Nein | Configs im UI | STT, Bild | Nicht dokumentiert | Unklar, ob Budgets pro Nutzer ohne Enterprise gehen |
| Respan (ex Keywords AI) | Team $199/Mo | Ja (`customer_params`) | Nein | Aliase, Fallbacks | STT/TTS/Bild | Auf Anfrage | Vollständig, kleiner Anbieter |
| Bifrost (Maxim, OSS) | self-hosted | Ja inkl. `budget_used > X` → Cheaper-Modell-Regel | **Ja** | UI | Ja | Wo gehostet | Funktional bestes Match, nur self-hosted |
| Helicone | Managed | Cost-Limit per Header | Nein | Fallback-Ketten | Kein STT/TTS am Gateway | US | Nein |
| TrueFoundry | $499/Mo min. | Ja | Nein | UI | Ja | Enterprise | Zu teuer |
| Kong | $100/Modell/Mo + Fees | Ja | Nein | Ja | Ja | EU | Overkill |
| Requesty / Eden AI | 5 % / 5,5 % | monatlich / täglich+monatlich | Nein | Requesty ja / Eden nein | Requesty nur OpenAI-Audio / Eden breit | beide EU | Nischen |
| Unify, Not Diamond | — | — | — | — | — | — | Unify existiert nicht mehr; Not Diamond ist nur Router |

**Empfehlung:** Die Nutzer-Ökonomie gehört in **unser Backend**, nicht in den Gateway-Vendor. Grund: Core spricht sowieso nur mit unserer API. Jede Anfrage geht durch uns, jede Antwort enthält `usage`. Eine Tabelle `usage(user_id, day, tokens_in, tokens_out, stt_seconds, tts_chars, images, cost_estimate)` plus eine Tabelle `plan_limits(plan, model_default, model_after_threshold, threshold, hard_cap)` sind ~200 Zeilen und geben genau die Regeln, die ihr wollt, inklusive der Wahl "transparent oder unter der Haube". Damit sind Budgets, Downgrade, Reporting und Admin-Panel vendor-unabhängig.

Der Gateway liefert dann nur noch: Modellkatalog, Fallbacks, Remapping, keinen Aufschlag, Audio. Dafür ist **Vercel AI Gateway** die naheliegende Wahl (0 % Aufschlag, ihr habt den Account, STT/TTS/Bild, Routing Rules für Remapping). **Cloudflare AI Gateway** als Alternative, wenn ihr die Spend-Limits pro Nutzer als zusätzliches Sicherheitsnetz ohne eigenen Code wollt und die fehlende EU-Log-Lokalisierung akzeptiert.

---

## 5. Hosting, Datenbank, Admin, Monitoring

### Option A (Empfehlung): Vercel + Supabase

- **API** als Vercel Functions. Python-Runtime ist offiziell (FastAPI zero-config, Python 3.13/3.14, Streaming per Default, Lifespan-Events). Alternativ TypeScript (SvelteKit/Hono). Pro-Plan: Max-Duration 800 s, 2 GB/1 vCPU Default (bis 4 GB/2 vCPU), Fluid Compute mit Active-CPU-Abrechnung (I/O-Wartezeit kostet keine CPU, ideal für Proxy). Region pro Projekt wählbar; für USA/Asien notfalls zweites Projekt.
- **DB + Auth + Cron**: Supabase Pro $25/Monat (Micro-Compute durch Credits gedeckt), Frankfurt. pg_cron für Monatsresets, Studio als Tabellen-Editor.
- **AI**: Vercel AI Gateway (Credits, 0 % Aufschlag). Speech direkt bei Deepgram/Inworld/OpenAI oder über den Gateway, wo verfügbar.
- **Webhook**: Vercel Function für PayPro-IPN (form-encoded POST, SHA256-`SIGNATURE` prüfen, IP-Allowlist 198.199.123.239 / 157.230.8.40).
- **PayPro-API-Calls** (IP-verifiziert): kleiner Relay mit fester IP (Fly.io Static IPv4 oder Hetzner CX22 ≈ €4/Monat) oder Klärung mit PayPro-Support.
- **Admin-Panel**: eigenes SvelteKit-Projekt auf Vercel, geschützt durch Vercel Authentication (auf Pro für alle Deployments inkl. Production; Viewer-Seats kostenlos) plus Supabase-Rolle. Alternativ Supabase Studio für reine Tabellenpflege.
- **Monitoring**: Sentry Team $26/Monat (annual), Better Stack Free (10 Monitore, 30 s, Statusseite), Axiom Personal (500 GB/Monat frei) bei Bedarf.
- **Website**: bleibt auf Vercel, bekommt Supabase-Login und den Checkout-Link mit der neuen User-ID als `x-user-id`. Damit ist "Subscribe vor Download" erledigt.

Fixkosten grob: Vercel Pro (vorhanden) + Supabase $25 + Sentry $26 + Relay €4 + AI-Credits nach Verbrauch. Deutlich unter dem, was drei Azure-Function-Apps, B2C und App Insights heute kosten dürften; genaue Azure-Ist-Kosten liegen mir nicht vor.

### Option B: Cloudflare-zentriert

Workers (TS) + D1 oder Hyperdrive→Postgres + Queues + AI Gateway mit Spend Limits + Workers AI für STT/TTS. Workers Paid $5/Monat. Vorteile: globale Edge-Verteilung ohne Regionen-Projekte, Budget→Downgrade ohne Code. Nachteile: Python Workers nicht reif, D1 max 10 GB, Log-Lokalisierung EU fehlt, Auth müsste extern (Supabase/Auth0) bleiben.

### Option C: Container mit LiteLLM

FastAPI + LiteLLM-Proxy als Container auf Fly.io/Hetzner/Cloud Run in 2–3 Regionen, Supabase oder Neon als DB. Vollständigster Economy-Layer ab Tag 1, aber Container-Betrieb, Updates, Secrets. Nur sinnvoll, wenn ihr LiteLLMs Features (Virtual Keys, Alias, Admin-UI, Audio-Routing) wirklich alle nutzen wollt.

### DB-Alternativen (falls nicht Supabase)

Neon (Launch usage-based, Frankfurt, ~$20/Monat für 0,25 CU always-on), PlanetScale Postgres (ab $15 HA, Frankfurt), Cloudflare D1 ($5 in Workers Paid, 10 GB Cap), Turso (nur Irland bestätigt), Railway (Amsterdam).

---

## 6. Modelle und Speech: Preise (Listenpreise, USD)

**LLM (pro 1M Tokens, Input / Cached / Output)**
- gpt-4.1-mini (heute): 0,40 / 0,10 / 1,60
- gpt-5.6-luna: 0,20 / 0,02 / 1,20 · gpt-5-mini: 0,25 / 0,025 / 2,00 · gpt-5-nano: 0,05 / 0,005 / 0,40 · gpt-4.1-nano: 0,10 / 0,025 / 0,40
- gpt-5.4: 2,50 / 0,25 / 15,00 · gpt-4.1: 2,00 / 0,50 / 8,00
- Gemini 2.5 Flash-Lite: 0,10 / — / 0,40 · Gemini 3.1 Flash-Lite: 0,25 / 0,025 / 1,50 · Gemini 3.7/3.8 Flash: 0,75 / 0,075 / 3,75 (bis 31.12.2026, danach doppelt)
- Aufschläge: Vercel AI Gateway 0 %, Cloudflare BYOK 0 % / Unified 5 %, OpenRouter 5,5 %

**STT (pro Minute)**
- Deepgram Nova-3 Streaming: 0,0048 mono / 0,0058 multilingual (Aktionspreis; regulär 0,0077 / 0,0092), 45+ Sprachen mit Erkennung
- OpenAI gpt-4o-mini-transcribe 0,003 · whisper-1 / gpt-4o-transcribe 0,006
- ElevenLabs Scribe v2 0,22/h (≈ 0,0037/min)

**TTS (pro 1M Zeichen)**
- Inworld TTS-2 Flash: 15 On-Demand (10 Creator, 7 Growth) · TTS-2: 25 (12,50 Growth), 200+ Sprachen. TTS-1 (das wingman-api heute sendet) ist nicht mehr auf der Preisseite.
- OpenAI tts-1: 15 · tts-1-hd: 30
- Deepgram Aura-2: 30 · Aura-1: 15
- ElevenLabs Flash/Turbo: 50 · v2 Multilingual/v3: 100 (32 / 29 / 70+ Sprachen)
- Azure Speech: Preise werden auf der Seite nicht gerendert ("$-"), Free-Tier 0,5M Zeichen/Monat; Google TTS: Seite nicht abrufbar

**Bild:** gpt-image-1-mini 2,00 Text-In / 2,50 Bild-In / 8,00 Output pro 1M Tokens; gpt-image-1: 5 / 10 / 40. Pro-Bild-Preise standen nicht auf der Seite.

### Kostenmodell pro aktivem Abonnent und Monat

Annahmen (bewusst hoch): 30 Sessions × 40 Turns = 1.200 LLM-Aufrufe mit 3.000 Input- und 150 Output-Tokens (3,6M In / 0,18M Out), 40 Minuten STT, 60.000 TTS-Zeichen, 5 Bilder. Core nutzt per Default lokales Parakeet-STT und Pocket-TTS, die Cloud-Speech-Anteile dürften real kleiner sein.

| Baustein | Günstig | Mittel (heute) | Premium |
|---|---|---|---|
| LLM | gpt-5.6-luna 0,94 · Gemini 2.5 Flash-Lite 0,43 | gpt-4.1-mini 1,73 (mit 70 % Cache-Treffern ≈ 0,97) | gpt-5.4 13,70 |
| STT | Deepgram Nova-3 multi 0,23 | gpt-4o-mini-transcribe 0,12 | whisper 0,24 |
| TTS | Inworld TTS-2 Flash 0,90 | OpenAI tts-1 0,90 | ElevenLabs Flash 3,00 |
| **Summe** | **≈ 1,6–2,1** | **≈ 2,0–2,8** | **≈ 17** |

Das Downgrade-Ziel (z. B. gpt-4.1-mini → gpt-5-nano oder Flash-Lite ab 70 % des Budgets) senkt den LLM-Anteil um Faktor 4 bis 8, ohne dass Nutzer einen anderen Anbieter sehen.

---

## 7. Migrationsplan

**Phase 0: Vorbereitung (ohne Nutzerkontakt)**
1. `wingman-webhook`-Code beschaffen (fehlt). IPN-Typen, die heute verarbeitet werden, dokumentieren.
2. B2C-Export per Graph: `GET /users?$select=id,displayName,identities,otherMails,createdDateTime,accountEnabled,extension_<appId>_WingmanSubscriptionPlan,…` (alle 10 Extension-Attribute), 999 pro Seite, `@odata.nextLink`. Ergebnis als JSON archivieren.
3. PayPro-Export: `Subscriptions/GetList` (alle Status, `includeOrders`), dann je Subscription `Orders/GetOrderDetails` auf der Initial-Order → E-Mail, `customerId`, `x-azure-user-id`.
4. Join: B2C-objectId ↔ PayPro-Subscription; Konflikte (E-Mail geändert, kein Custom-Feld) manuell listen.
5. Neues Backend + Supabase aufsetzen, PayPro-IPN-Handler nachbauen, mit IPN-Simulator und Test-Mode-Orders testen. Egress-IP bei PayPro allowlisten.

**Phase 1: User-Import**
6. Alle B2C-User per `admin.createUser` (E-Mail verifiziert, ohne Passwort) anlegen. Metadaten: `legacy_b2c_object_id`, `paypro_subscription_id`, `plan`, `plan_end_date`, `terms_consent_at`, `provider` (google/github/email).
7. Subscription-Tabelle aus dem PayPro-Export füllen. Neue User-ID per `Subscriptions/ChangeCustomFields` auf jede aktive Subscription stempeln.

**Phase 2: Umschalten**
8. Client-Release mit neuem Login-Flow (Systembrowser + Deep-Link, Geräte-Token für Core) und neuer API-Basis-URL. Region-Auswahl entfällt oder wird auf zwei Vercel-Regionen gemappt.
9. Beim ersten Login: Google/GitHub-Nutzer landen per verifizierter E-Mail automatisch auf ihrem importierten Account. E-Mail/Passwort-Nutzer sehen einmalig "Wir haben unser Login-System erneuert, bitte Magic-Link/Passwort setzen". ToS-Consent wird aus `terms_consent_at` übernommen, kein erneutes Nicken nötig, solange die Terms-Version gleich ist.
10. PayPro-IPN-URL im Dashboard auf das neue Backend umstellen (oder zweite Zeile parallel, dann alte entfernen). Verpasste Events per Dashboard-Replay nachziehen.
11. Alte API-Version im Client für eine Übergangsfrist erlaubt; alte Azure-Ressourcen erst nach Ablauf der Frist abschalten.

**Phase 3: Aufräumen**
12. slickgpt-api, wingman-webhook, drei wingman-api-Apps, B2C-Tenant, App Insights, Paddle-Reste, Stripe-Portal-Link entfernen.

Was nicht automatisch geht: Passwörter (Reset nötig), Nutzer ohne verifizierte E-Mail bei GitHub (GitHub liefert E-Mail nur mit `user:email`-Scope; die B2C-Policy fragt ihn ab, also sollte sie vorliegen), Nutzer, die bei PayPro eine andere E-Mail als im Login benutzen (über `x-azure-user-id` trotzdem auflösbar).

---

## 8. Offene Fragen an dich

1. **Zahlen:** Wie viele User in B2C gesamt, wie viele monatlich aktiv, wie viele zahlende Pro/Ultra? Gibt es noch aktive Stripe- oder Paddle-Subscriptions? Das entscheidet Auth-Tier und Kostenmodell.
2. **wingman-webhook:** Wo liegt der Code? Ich brauche ihn für den IPN-Nachbau.
3. **Sprache des neuen Backends:** TypeScript (SvelteKit/Hono, passt zu Website und Admin) oder Python (FastAPI, passt zu Core und zum bestehenden wingman-api)? Beides läuft auf Vercel.
4. **Speech-Übergang:** Azure Speech vorübergehend als letzten Azure-Dienst behalten (Stimmen-Namen in Configs bleiben gültig) oder harter Wechsel mit Mapping-Tabelle auf Inworld/Deepgram/OpenAI?
5. **Regionen:** Brauchen Nutzer wirklich drei Regionen, oder ging es um Azure-Latenz? Der neue Proxy sitzt sowieso vor US-Modellanbietern.
6. **Steam-Login** gewünscht? Nur mit Better Auth oder eigenem OpenID-2.0-Bridge machbar.
7. **Excalidraw:** Share-Links funktionieren auf `http://excalidraw.lan` nicht, weil WebCrypto nur in Secure Contexts läuft (Browser-Fehler "Cannot read properties of undefined (reading 'importKey')"). Mit HTTPS (z. B. Caddy + lokale CA) gehen sie sofort. Das Ist-Diagramm liegt als Datei unter `/tmp/wingman-arch/current.excalidraw` und lässt sich per "Öffnen" laden; Generator: `/tmp/wingman-arch/current.mjs`.

---

## 9. Quellenverzeichnis

Rohberichte mit allen URLs: `/tmp/wingman-arch/research/`
- `b2c-exit-paypro.md` (B2C-Limits, Graph-Export, PayPro IPN/API)
- `auth-*.md` (Supabase/Firebase, Clerk/Kinde, WorkOS/Stytch, Auth0/Entra, Logto/Zitadel, Better Auth/Descope/Hanko/Ory)
- `gateway-*.md`, `raw-gateway-*.md` (OpenRouter, Portkey, LiteLLM, Cloudflare, Vercel, Helicone, Bifrost, Kong, TrueFoundry, Requesty, Eden, Respan, Unify, Not Diamond)
- `db-postgres.md`, `admin-monitoring.md`, `hosting-part*.md` (Vercel Functions/Fluid/Python)
- `pricing-llm.md`, `pricing-speech.md`

Nicht recherchiert (Subagent abgebrochen): Fly.io / Cloud Run / Hetzner / Railway Container-Preise im Detail, Google Cloud TTS-Preise, Azure-Speech-Listenpreise.

---

## 10. Update 2026-09-10 nach Rückfragen

### Antworten
- 250–350 aktive Subscriptions. Gesamtnutzerzahl (Free) unbekannt, aber weit unter jedem Free-Tier-Limit (Supabase 50k MAU frei, Auth0 25k).
- `wingman-webhook` liegt jetzt unter `/Users/shackles/Source/wingman-webhook`. Konsolidierung mit wingman-api gewünscht (nice-to-have).
- Backend-Sprache egal. Azure Speech behalten nicht nötig. Regionen weg. Steam nice-to-have, Pflicht ist nur Google.

### wingman-webhook (C#/.NET Azure Function) — was er tut
- Endpunkte: `PayProWebhook` (IPN), `GetProducts` (Proxy auf PayPro `Products/GetProductPricing` mit Client-IP für Währung; das ist `PUBLIC_GET_PRODUCTS_URL` in Client und Website), Legacy `StripeWebhook`, `PaddleWebhook`.
- Prüft IP-Allowlist (198.199.123.239, 157.230.8.40 + 2 IPv6), MD5-`HASH` (`"1"` im Testmodus, sonst `ORDER_ID + SecretKey`), SHA256-`SIGNATURE` (`ORDER_ID + ORDER_STATUS + ORDER_TOTAL_AMOUNT + CUSTOMER_EMAIL + ValidationKey + TEST_MODE + IPN_TYPE_NAME`).
- Verarbeitet IPN-Typen 1 OrderCharged, 6 SubscriptionChargeSucceed, 9 SubscriptionRenewed, 13 TrialCharge (→ setzt `PayProSubscriptionId`, `PayProSubscriptionEndDate` = `SUBSCRIPTION_NEXT_CHARGE_DATE` bzw. `TRIAL_PERIOD_TILL`, Plan Pro/Ultra) und 8 Suspended, 10 Terminated, 11 Finished (→ Plan geleert, `LastPayProSubscriptionPlan` gesetzt).
- Plan-Zuordnung über acht PayPro-Produkt-IDs aus Env-Vars (Pro/Ultra × monatlich/jährlich × normal/resubscribe) plus SlickGPT-Pro-IDs.
- Bricht mit 400 ab, wenn `x-azure-user-id` in `ORDER_CUSTOM_FIELDS` fehlt. Bestätigt in der Praxis: PayPro schickt die Custom-Felder bei allen sieben Typen mit.
- Der Endzustand ist rein aus IPNs abgeleitet, keine Reconciliation. Im neuen Backend sollte ein täglicher Cron `Subscriptions/GetList` gegen die eigene Tabelle abgleichen, dann sind verpasste IPNs kein Risiko mehr.

### Angepasste Empfehlung

**Ein Backend statt vier.** wingman-api (3×), wingman-webhook, slickgpt-api und die Website-Pricing-Route werden ein SvelteKit-Projekt auf Vercel: `/api/v1/*` (Proxy für LLM/STT/TTS/Bild mit Metering), `/api/webhooks/paypro` (IPN), `/api/products` (Preise), `/api/me` (Plan, Verbrauch, ToS-Consent), `/admin/*` (Panel). Die Website bekommt denselben Supabase-Login und den Checkout-Link mit `x-user-id`.

**Sprache: TypeScript.** Begründung: Client, Website und Admin sind schon SvelteKit; Supabase-, Vercel-AI-Gateway- und AI-SDK-Tooling sind TS-first; ein Projekt kann API-Routen und Admin-UI zusammen deployen; Node ist die reifste Vercel-Runtime. Python bliebe nur für Core. Die Request/Response-Formen des heutigen `/ask` (OpenAI-Chat-Completion) und der Audio-Endpunkte bleiben kompatibel, damit `providers/wingman_subscription.py` in Core nur die Basis-URL und das Token-Handling ändert.

**Regionen:** Ein Vercel-Projekt in `fra1`. Der Proxy wartet fast nur auf US-Modellanbieter; die Region des Proxys ist dafür zweitrangig. `RegionPrompt` und `/wingman-pro-regions` entfallen im Client.

**Speech:** Direkt umstellen. STT auf Deepgram Nova-3 (Sprach-Autoerkennung, 45+ Sprachen) oder gpt-4o-mini-transcribe; TTS auf Inworld TTS-2 Flash als Standard (schon integriert, 200+ Sprachen, $15/1M) und OpenAI tts-1 als zweite Option. Azure-Stimmen-Namen in Nutzer-Configs werden per Migration auf eine Inworld-Stimme gleicher Sprache und gleichen Geschlechts gemappt; die Liste aus `/azure-voices` liefert Locale und Gender dafür.

**Auth: Supabase.** Google ist Pflicht und eingebaut; GitHub, Discord, Twitch, Apple, Microsoft, X sind Toggles. Steam bleibt offen (serverseitiger OpenID-2.0-Bridge, später).

**Kosten bei 300 Abonnenten** (Fixkosten pro Monat): Supabase Pro $25, Sentry Team $26, Static-IP-Relay ≈ €4, Vercel Pro vorhanden, Vercel AI Gateway 0 % Aufschlag. Variabel: bei $2–3 AI-Kosten pro aktivem Abonnent ≈ $600–900/Monat, mit Downgrade-Regel deutlich darunter.

### Vorgeschlagene erste Schritte (noch nichts umgesetzt)
1. Supabase-Projekt (Frankfurt) anlegen, Google-Provider konfigurieren, Custom-SMTP.
2. Neues Repo `wingman-backend` (SvelteKit): Schema (users, subscriptions, usage, plan_limits, model_routes), PayPro-IPN-Route mit den drei Prüfungen aus dem C#-Code, `/api/products`.
3. B2C-Export-Skript (Graph) und PayPro-Export-Skript, Join-Report.
4. Client: Login-Flow auf Systembrowser + Deep-Link, Geräte-Token für Core, Basis-URL austauschen.
5. Proxy-Routen mit Vercel AI Gateway, Metering, Downgrade-Regel; Admin-Panel.
6. Cutover nach Plan aus Abschnitt 7.

---

## 11. Alt gegen neu, kompletter Flow, Parallelbetrieb, Migration (2026-09-10)

### Alt gegen neu

| Bereich | Heute | Neu | Lebt wo | Kosten/Monat |
|---|---|---|---|---|
| Identität | Azure AD B2C, Custom Policies, MSAL im Webview, 24h-Limit | Supabase Auth, PKCE im Systembrowser, Deep-Link zurück, Sessions unbegrenzt | Supabase Frankfurt | in Supabase Pro $25 enthalten |
| Nutzer-/Subscription-Daten | 10 Extension-Attribute am B2C-User, geschrieben per Graph | Postgres-Tabellen `users`, `subscriptions`, `usage`, `plan_limits`, `model_routes` | Supabase Frankfurt | s. o. |
| API-Proxy | wingman-api, FastAPI, 3 Azure-Function-Apps | `/api/v1/*` im SvelteKit-Backend, eine Region | Vercel fra1 | Vercel Pro vorhanden, Functions nach Active-CPU (Proxy wartet nur, kaum CPU) |
| PayPro-Webhook | wingman-webhook, C#, Azure Function | `/api/webhooks/paypro` im selben Backend | Vercel | 0 |
| Preis-Endpunkt | GetProducts in wingman-webhook | `/api/products` im Backend | Vercel | 0 |
| ToS-Consent | slickgpt-api, C#, Graph-Write | Spalte `terms_accepted_at` + `/api/me/terms` | Backend + Supabase | 0 |
| LLM | Azure OpenAI, gpt-4.1-mini, Modell-Hack im Code | Vercel AI Gateway, Modell aus `model_routes`, Fallbacks, 0 % Aufschlag | Vercel | Listenpreis der Modelle |
| STT | Azure Whisper + Azure Speech | Deepgram Nova-3 oder gpt-4o-mini-transcribe | Deepgram / OpenAI (ggf. via Gateway) | $0,003–0,006/min |
| TTS | Azure Speech Neural + OpenAI tts-hd via Azure + Inworld | Inworld TTS-2 Flash (Standard) + OpenAI tts-1 | Inworld / OpenAI | $15/1M Zeichen |
| Bild | gpt-image-1-mini via Azure | gpt-image-1-mini via Gateway | Vercel AI Gateway | Listenpreis |
| PayPro-API-Calls (IP-gebunden) | aus Azure Functions | über Mini-Relay mit fester IP | Hetzner/Fly | ca. €4–6 (nicht recherchiert) |
| Admin | keins (Env-Vars, Code) | `/admin` im Backend, Supabase-Rolle `admin` | Vercel | 0 |
| Monitoring | App Insights | Sentry + Better Stack | SaaS | $26 (Sentry Team) + 0 |
| Website | wingman-website, kein Login | gleiches Repo, plus Supabase-Login, Account-Seite, Checkout mit `x-user-id` | Vercel | vorhanden |
| Updates | Cloudflare R2 | unverändert | Cloudflare | vorhanden |
| Analytics | Aptabase | unverändert | Aptabase | vorhanden |

Fixkosten neu: ≈ $55–60 plus vorhandene Vercel/Cloudflare-Pläne. Variabel: AI-Verbrauch, bei 300 Abonnenten ≈ $600–900 im Worst-Case-Profil.

### Repos danach

| Repo | Status | Inhalt |
|---|---|---|
| `wingman-backend` (neu, SvelteKit/TS) | neu | `/api/v1/chat`, `/api/v1/audio/transcriptions`, `/api/v1/audio/speech`, `/api/v1/images`, `/api/v1/voices`, `/api/me` (Plan, Verbrauch, ToS, Geräte-Token), `/api/products`, `/api/webhooks/paypro`, `/admin`, Cron (Monatsreset, PayPro-Abgleich), `scripts/` (B2C-Export, PayPro-Export, Import, Join-Report) |
| `wingman-ai` (Core) | ändern | `providers/wingman_subscription.py`: neue Basis-URL, Geräte-Token, Endpunkt-Namen; Enums `WingmanProSttProvider`/`WingmanProTtsProvider` erweitern; Migration, die Azure-Stimmen auf Inworld-Stimmen mappt; `/wingman-pro-regions` entfernen |
| `wingman-client` | ändern | `authService.ts` auf Supabase + Deep-Link (MSAL raus), `RegionPrompt` raus, Subscribe-Seite und ToS gegen `/api/me`, Tauri Deep-Link-Plugin |
| `wingman-website` | ändern | Supabase-Login, Account-Seite (Plan, Verbrauch, PayPro-Portal-Link), Checkout-Link mit `x-user-id`, `/api/pricing` bleibt |
| `wingman-api` | stilllegen | nach Übergangsfrist |
| `wingman-webhook` | stilllegen | nach Übergangsfrist |
| `slickgpt-api` | stilllegen | sofort nach Cutover (nur ToS) |
| `slickgpt` | tot | unverändert |

### Der neue Flow, durchgespielt

**Neuer Nutzer über die Website.** Website → "Anmelden" → Supabase-Login (Google) → Account-Seite → "Pro abonnieren" → PayPro-Checkout mit `billing-email` + `x-user-id=<supabase uuid>` → PayPro IPN `OrderCharged`/`TrialCharge` → Backend prüft IP, HASH, SIGNATURE → `subscriptions` upsert (status, product → plan, next_charge) → Nutzer lädt Client → Login im Client (Systembrowser, dieselbe Google-Session) → Plan ist da.

**Login im Client.** Client öffnet `https://<supabase>/auth/v1/authorize?provider=google&code_challenge=…` im Systembrowser → Supabase redirectet auf `wingman://auth/callback?code=…` → Tauri Deep-Link-Plugin übergibt den Code → `exchangeCodeForSession` → Client hat Supabase-Session (Refresh-Token läuft nicht ab) → Client ruft `POST /api/me/device-token` mit Supabase-JWT → Backend legt Zeile in `device_tokens` an (opak, widerrufbar, Name "Simons PC") → Client speichert es als Core-Secret `wingman_pro` → Core sendet es als Bearer bei jedem Aufruf. Kein Refresh mehr in Core.

**Eine Sprachanfrage.** Core → `POST /api/v1/audio/transcriptions` (Bearer Geräte-Token) → Backend: Token → user_id → Plan → prüft `usage` gegen `plan_limits` → Deepgram → Antwort + `usage` schreiben (Sekunden). Core → `POST /api/v1/chat` mit `model: "wingman-default"` → Backend löst über `model_routes` auf (Plan Pro, Verbrauch unter 70 % → `openai/gpt-4.1-mini`; über 70 % → `openai/gpt-5-nano`; Hard-Cap → 429 mit Hinweis) → Vercel AI Gateway (Streaming, Fallback-Kette) → Backend zählt Tokens aus `usage` der Antwort → Core → `POST /api/v1/audio/speech` → Inworld → Zeichen zählen. Alles in einer Tabelle pro Nutzer und Tag; das Admin-Panel und `/api/me` lesen daraus.

**Modell umbiegen.** Admin öffnet `/admin/models`, ändert `wingman-default (pro) → openai/gpt-5-mini`, speichert. Nächste Anfrage nutzt das neue Modell. Kein Deploy.

**Kündigung.** Nutzer klickt im Client oder auf der Website "Kündigen" → Backend → Relay → PayPro `Subscriptions/Suspend` → PayPro IPN `SubscriptionSuspended` → `subscriptions.status = suspended`, Plan bleibt bis `next_charge` gültig (Grace wie heute) → Cron setzt danach `plan = free`. Renew analog.

**Abgleich.** Täglicher Cron: `Subscriptions/GetList` (alle Status) gegen `subscriptions`; Abweichungen loggen und korrigieren. Das ersetzt das heutige "IPN verpasst = falscher Zustand".

**ToS.** `/api/me` liefert `terms_accepted_at` und `terms_version`; Client zeigt den Dialog nur, wenn Version neuer ist; `POST /api/me/terms` schreibt den Zeitstempel.

### Parallelbetrieb und Test

Ja, komplett parallel, ohne das Alte anzufassen:

1. Eigenes Supabase-Projekt, eigenes Vercel-Projekt, eigene Domain `api.wingman-ai.com` (Cloudflare-DNS).
2. PayPro erlaubt mehrere IPN-URLs (eine pro Zeile). Die neue URL wird als zweite Zeile eingetragen. Ab dann bekommt das neue Backend alle echten Events im Schattenbetrieb, während B2C weiter vom alten Webhook gepflegt wird. Nach dem Import lässt sich der neue Zustand täglich gegen B2C und PayPro vergleichen, bevor ein Nutzer umgestellt wird.
3. Test-Käufe über `use-test-mode=true` + `secret-key` und `ipn-domain=api.wingman-ai.com` treffen nur das neue Backend. IPN-Simulator für Einzel-Events.
4. Client: Build mit Env `PUBLIC_AUTH_BACKEND=new` im Beta-Updater-Kanal. Test-Accounts loggen sich schon gegen Supabase ein, Prod-Nutzer merken nichts.
5. Import-Skripte laufen beliebig oft idempotent (Upsert über `legacy_b2c_object_id`).

### Die Migration, konkret

**Datenflüsse**
- B2C → Graph-Export (JSON: objectId, E-Mail, displayName, identities, 10 Extension-Attribute) → `scripts/import-users` → Supabase `auth.users` (E-Mail verifiziert, kein Passwort) + `users` (legacy_id, terms_accepted_at, provider).
- PayPro → `Subscriptions/GetList` + `Orders/GetOrderDetails` → `scripts/import-subscriptions` → `subscriptions` (paypro_subscription_id, customer_id, status, product, next_charge, x-azure-user-id) → Join über legacy_id, Fallback E-Mail.
- Backend → PayPro `ChangeCustomFields` (neue user_id auf jede aktive Subscription).
- PayPro IPN → neues Backend (parallel zum alten).
- Nichts fließt aus Supabase zurück nach Azure.

**Für uns, Zeitplan**
- T-14: Import laufen lassen, Join-Report prüfen (Erwartung: 250–350 Subscriptions, alle mit `x-azure-user-id`; Rest manuell). IPN-Schattenbetrieb aktiv. Egress-IP des Relays bei PayPro allowlisten.
- T-7: Beta-Client an ein paar Nutzer, Website-Login live (schadet dem alten System nicht).
- T0: Client-Release im Stable-Kanal. Alte IPN-URL bleibt noch. Terms-Version unverändert.
- T0 bis T+30: beide Backends laufen. Alte Clients arbeiten unverändert gegen B2C und wingman-api. Neue Clients gegen Supabase und Backend. IPNs pflegen beide Zustände.
- T+30: alte IPN-URL entfernen, wingman-api/-webhook/slickgpt-api stoppen, B2C-Tenant nach weiteren 30 Tagen löschen. Vorher letzter Vollabgleich.

**Für die Nutzer**
- Google-/GitHub-Nutzer: Client-Update, einmal "Anmelden", Systembrowser öffnet sich, Google-Konto auswählen, fertig. Supabase verknüpft über die verifizierte E-Mail mit dem importierten Account. Plan, Subscription, ToS sind da.
- E-Mail/Passwort-Nutzer: Client-Update, "Anmelden", E-Mail eingeben → Magic-Link oder Code per Mail → drin. Optional Passwort setzen. Einmalig.
- Niemand muss kündigen, neu abschließen oder Zahlungsdaten anfassen. PayPro-Portal bleibt dasselbe.
- Wer nie updatet, läuft bis T+30 weiter, danach fordert der alte Client zum Update auf (Updater-Hinweis).

**Rollback** bis T+30: neue IPN-URL entfernen, Client-Release zurückziehen. Das alte System war nie aus.

## 12. Steuerung und Sichtbarkeit (Antwort auf Rückfrage 2026-09-10)

- Deepgram ist optional. Vercel AI Gateway kann LLM, STT (whisper-1, gpt-4o-transcribe, gemini-3.5-transcribe), TTS (tts-1, tts-1-hd) und Bild. Start: alles über den Gateway. Deepgram (STT-Sprachen + Preis) und Inworld (Ultra-Stimmen, existiert schon) sind spätere Direktintegrationen, keine Pflicht.
- Tier-Logik lebt nur im eigenen Backend: Tabellen `plan_limits`, `model_routes`, `user_overrides`, `usage_daily`; Admin-Panel `/admin`. Vercel Routing Rules sind teamweite Rewrites ohne Tier-Bezug (Notfall-Schalter).
- Sichtbarkeit: `/admin` (Nutzer, Verbrauch pro Nutzer/Tag/Modell), Supabase Studio (Rohdaten, Auth-User-Zahl), Vercel-AI-Gateway-Dashboard (Rechnung pro Modell/Key; Custom Reporting API pro `user`-Header, kostenpflichtig) als Gegenprobe.
- Hook: Middleware pro Anfrage: Geräte-Token → user → plan → usage → `plan_limits`/`user_overrides` → Modell wählen, drosseln oder 429. Globaler Backstop: Budget pro Gateway-API-Key (402).

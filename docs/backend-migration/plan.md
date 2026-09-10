# Implementierungsplan: Neues Wingman-Backend parallel zu Azure

Stand 2026-09-10. Recherche und Begründungen: `research.md` (Abschnitte 1–12) und der Ordner `research/`.

## 0. Feste Entscheidungen

| Baustein | Entscheidung |
|---|---|
| Auth + DB + Cron | Supabase, Region Frankfurt, Pro-Plan ($25/Mo) |
| Backend | Neues Repo `wingman-backend`, SvelteKit + TypeScript, Vercel Pro, Region `fra1`, eine Region |
| LLM, STT, OpenAI-TTS, Bild | Vercel AI Gateway (0 % Aufschlag), Modellwahl über eigene `model_routes` |
| Premium-TTS | Inworld direkt (bleibt, Ultra) |
| Payment | PayPro Global unverändert; IPN an das neue Backend; IP-gebundene PayPro-API-Calls über Relay auf dem Hostinger-Server |
| Monitoring | vorerst nur Vercel- und Supabase-Logs; Sentry/Better Stack später bei Bedarf |
| Azure Speech, Regionen, SlickGPT-API | entfallen |
| Tier-Logik, Metering, Downgrade, Overrides | nur im eigenen Backend (Tabellen + `/admin`) |

Regeln für den Parallelbetrieb: keine Änderung an B2C-Policies, an den Azure Functions oder am Stable-Client, solange Phase 9 nicht erreicht ist. Alles Neue ist additiv: zweite IPN-URL bei PayPro, neue Domains, Beta-Updater-Kanal, neue Supabase- und Vercel-Projekte.

## 1. Datenmodell (Supabase Postgres)

```
users            id (auth.users.id), email, display_name, legacy_b2c_object_id, provider,
                 plan (free|pro|ultra), plan_source (paypro|legacy|manual), plan_until,
                 terms_accepted_at, terms_version, created_at, blocked
subscriptions    id, user_id, paypro_subscription_id (unique), paypro_customer_id,
                 product_id, plan, status (active|suspended|terminated|finished),
                 is_trial, next_charge_at, last_ipn_type, last_ipn_at, raw_last_ipn jsonb
ipn_log          id, order_id, ipn_type_id, received_at, signature_ok, hash_ok,
                 ip_ok, processed, error, payload jsonb            -- idempotent über (order_id, ipn_type_id, next_charge_at)
device_tokens    id, user_id, token_hash, name, created_at, last_used_at, revoked_at
plan_limits      plan, monthly_tokens, monthly_stt_seconds, monthly_tts_chars, monthly_images,
                 downgrade_at_pct, hard_cap_behavior (deny|downgrade_only), updated_by
model_routes     plan, alias (default|downgraded|fast), model, fallbacks text[], enabled
user_overrides   user_id, forced_model, extra_tokens, blocked, note, expires_at
usage_daily      user_id, day, modality (chat|stt|tts|image), model, prompt_tokens,
                 completion_tokens, seconds, chars, images, cost_estimate_usd
                 -- PK (user_id, day, modality, model)
admin_audit      id, admin_user_id, action, target, before jsonb, after jsonb, at
```

Row Level Security: Nutzer lesen nur ihre eigene Zeile in `users`, `subscriptions`, `usage_daily`, `device_tokens`. Alles andere nur über Service-Role im Backend. Rolle `admin` als `app_metadata.role` im Supabase-JWT.

## 2. Phasen

Jede Aufgabe nennt Repo, Ergebnis und Test. Reihenfolge innerhalb einer Phase ist frei, Phasen bauen aufeinander auf. Phasen 5, 6, 7 können parallel zu 3 und 4 laufen.

### Phase 0: Konten und Infrastruktur (keine Codeänderung an bestehenden Repos)

- [ ] 0.1 Supabase-Projekt `wingman-prod` in Frankfurt anlegen; Pro-Plan; Google-Provider mit eigener OAuth-Client-ID (neue Client-ID, nicht die von B2C); GitHub optional gleich mit. Redirect-Allowlist: `wingman://auth/callback`, `http://localhost:5173/auth/callback`, `https://wingman-ai.com/auth/callback`, `https://*.vercel.app/auth/callback`.
- [ ] 0.2 Custom-SMTP in Supabase (der eingebaute Versand ist auf 2 Mails/Stunde begrenzt). Anbieter frei wählbar, Absender `noreply@wingman-ai.com`.
- [ ] 0.3 Vercel-Projekt `wingman-backend`, Region `fra1`, Domain `api.wingman-ai.com` (DNS bei Cloudflare, Proxy aus oder DNS-only, damit Streaming und Body-Größen nicht durch Cloudflare-Limits laufen).
- [ ] 0.4 Vercel AI Gateway: API-Key für `wingman-backend`, Monatsbudget als Backstop setzen (z. B. 2× erwarteter Verbrauch), Credits aufladen.
- [ ] 0.5 Inworld-API-Key aus wingman-api übernehmen (derselbe Account).
- [ ] 0.6 (später, optional) Sentry-Projekt und Better-Stack-Monitor auf `https://api.wingman-ai.com/health`. Vorerst reichen Vercel-Logs (1 Tag) und Supabase-Logs (7 Tage).
- [ ] 0.7 PayPro: Testmodus-Zugang prüfen (`use-test-mode`, `secret-key`), IPN-Simulator-Zugang, Validation Key und Secret Key aus den Azure-Function-Settings übernehmen. Noch keine IPN-URL eintragen.
- [ ] 0.8 Hostinger-Relay (siehe Abschnitt 4) aufsetzen; feste IP beim PayPro-Support allowlisten lassen. Bis die Allowlist steht, laufen PayPro-API-Calls im Testmodus weiter über die alte Azure-Function-IP, also nichts blockiert.

### Phase 1: Backend-Skelett (`wingman-backend`)

- [ ] 1.1 Repo anlegen: SvelteKit, `adapter-vercel`, Drizzle oder Supabase-Migrations für das Schema aus Abschnitt 1, Seed für `plan_limits` und `model_routes` (Werte aus heutigem Stand: Pro und Ultra → `openai/gpt-4.1-mini`, Downgrade → `openai/gpt-5-nano`).
- [ ] 1.2 Auth-Middleware: akzeptiert Supabase-JWT (JWKS, ES256) und Geräte-Token (`Authorization: Bearer wgd_…`, Hash-Lookup in `device_tokens`). Ergebnis: `locals.user` mit Plan.
- [ ] 1.3 `POST /api/me/device-token` (Supabase-JWT → neues Token, einmal sichtbar), `GET /api/me` (Plan, `plan_until`, Verbrauch des Monats, Limits, `terms_accepted_at`, Geräte-Liste), `DELETE /api/me/device-token/:id`, `POST /api/me/terms`.
- [ ] 1.4 `GET /api/products?currency=&billingCountry=`: Proxy auf PayPro `Products/GetProductPricing` über das Relay; Antwortform identisch zum heutigen `GetProducts`, damit Client und Website unverändert lesen können. Cache 10 Minuten.
- [ ] 1.5 `POST /api/webhooks/paypro`: Form-encoded und JSON; IP-Allowlist (198.199.123.239, 157.230.8.40, 2604:a880:400:d0::1843:7001, 2604:a880:400:d1::b6c:c001; Client-IP aus `x-forwarded-for` erstes Element); MD5-`HASH`; SHA256-`SIGNATURE`; Idempotenz über `ipn_log`; Verarbeitung der Typen 1, 6, 9, 13 (Subscription anlegen/aktualisieren, `plan`, `plan_until` = `SUBSCRIPTION_NEXT_CHARGE_DATE` bzw. `TRIAL_PERIOD_TILL`) und 8, 10, 11 (Status setzen, Plan bleibt bis `plan_until`). Nutzer-Zuordnung: `x-user-id` (neu) → `x-azure-user-id` (Legacy über `users.legacy_b2c_object_id`) → `CUSTOMER_EMAIL`. Unbekannter Nutzer: Zeile in `subscriptions` ohne `user_id`, Warnung im Log und in `admin_audit`, trotzdem HTTP 200.
- [ ] 1.6 Plan-Auflösung aus Produkt-IDs: Tabelle statt Env-Vars (`paypro_products(product_id, plan, interval, is_resubscribe)`), Seed mit den acht IDs aus `wingman-webhook`.
- [ ] 1.7 Cron (Vercel Cron, täglich): `Subscriptions/GetList` über Relay, Abgleich mit `subscriptions`, Abweichungen in `admin_audit`; `plan_until` abgelaufen → `plan = free`.
- [ ] 1.8 `GET /health`, strukturierte Logs (console.error mit Kontext reicht für Vercel-Logs).
- Test: Unit-Tests für HASH/SIGNATURE mit echten Werten aus einem Testmodus-Kauf; IPN-Simulator gegen Preview-Deployment; `/api/me` mit Supabase-Testuser.

### Phase 2: Proxy-Routen und Metering (`wingman-backend`)

- [ ] 2.1 `POST /api/v1/chat/completions`: OpenAI-Chat-Completion-Format wie heute `/ask` (messages, tools, stream, reasoning_effort). Middleware: Overrides → Limits → Modellwahl aus `model_routes` → Vercel AI Gateway mit Fallback-Kette → Stream durchreichen → `usage` aus letztem Chunk in `usage_daily`. Hard-Cap: HTTP 429 mit JSON `{error: "quota_exceeded", resets_at}`.
- [ ] 2.2 `POST /api/v1/audio/transcriptions`: multipart, Modell aus `model_routes` (Alias `stt`), Gateway; Sekunden zählen (Dauer aus Datei-Header).
- [ ] 2.3 `POST /api/v1/audio/speech`: Provider `openai` (Gateway, tts-1/tts-1-hd) oder `inworld` (direkt, Streaming wie heute in `generate_inworld_speech`, LINEAR16 für Streaming); Zeichen zählen. Ultra-Prüfung für Inworld.
- [ ] 2.4 `GET /api/v1/voices?provider=inworld|openai&language=`: Inworld-Voices-Proxy wie heute, OpenAI-Stimmenliste statisch.
- [ ] 2.5 `POST /api/v1/images/generations`: gpt-image-1-mini über Gateway, Antwort als Data-URL wie heute.
- [ ] 2.6 `GET /api/v1/models`: Liste der für den Plan erlaubten Aliase mit Anzeigenamen (ersetzt `/wingman-pro-models`).
- [ ] 2.7 Subscription-Aktionen: `POST /api/me/subscription/suspend|renew` (über Relay), `GET /api/me/subscription` (aus DB, nicht live von PayPro).
- Test: Contract-Test, der die heutigen Antworten von wingman-api (Testaccount) gegen die neuen vergleicht (Feldnamen, Streaming-Chunks, Audio-Header); Lasttest mit 20 parallelen Streams.

### Phase 3: Admin (`wingman-backend`, Route `/admin`)

- [ ] 3.1 Zugang nur mit Supabase-Rolle `admin`; zusätzlich Vercel Authentication auf dem Projekt, bis das Panel fertig ist.
- [ ] 3.2 Seiten: Übersicht (Nutzer nach Plan, Tagesverbrauch, Kosten-Schätzung), Nutzerliste mit Suche, Nutzerdetail (Subscription, Verbrauch pro Tag/Modell, Geräte, Overrides setzen, Plan manuell setzen), Modell-Routen und Plan-Limits bearbeiten, IPN-Log, Abgleich-Report, Audit.
- [ ] 3.3 CSV-Export für Verbrauch und Nutzer.
- Test: Änderung einer Route wirkt beim nächsten Request ohne Deploy.

### Phase 4: Migrationsskripte (`wingman-backend/scripts`)

- [ ] 4.1 `export-b2c.ts`: Graph `GET /users?$select=id,displayName,identities,otherMails,createdDateTime,accountEnabled,extension_3453752678f34332bf48453d0bd422f2_*` mit Pagination; Ausgabe `b2c-users.json`. App-Registrierung mit `User.Read.All` (die Graph-App aus wingman-webhook hat `User.ReadWrite.All`, reicht).
- [ ] 4.2 `export-paypro.ts`: `Subscriptions/GetList` (statusIds 1–4, `includeOrders`, Paging 100), je Subscription `Orders/GetOrderDetails` der Initial-Order; Ausgabe `paypro-subscriptions.json`.
- [ ] 4.3 `join-report.ts`: Zuordnung über `x-azure-user-id`, Fallback E-Mail; Report: zugeordnet, mehrdeutig, ohne Nutzer, Nutzer ohne Subscription aber mit Plan in B2C (Legacy Stripe/Paddle).
- [ ] 4.4 `import-users.ts`: idempotent (Upsert über `legacy_b2c_object_id`); `auth.admin.createUser({email, email_confirm: true, app_metadata: {legacy_b2c_object_id}})`; `users`-Zeile mit Plan, `plan_until`, `terms_accepted_at` (aus `WingmanTermsConsentDateTime`, Unix-Sekunden). Flag `--only-email` für Einzelimport (eigener Account zuerst).
- [ ] 4.5 `import-subscriptions.ts`: idempotent über `paypro_subscription_id`.
- [ ] 4.6 `stamp-paypro.ts`: `Subscriptions/ChangeCustomFields` mit `x-user-id` auf jede aktive Subscription (über Relay). Erst in Phase 9 ausführen.
- [ ] 4.7 `compare-shadow.ts`: vergleicht Plan/Status/Enddatum in Supabase mit B2C-Export und PayPro-Export; Report für die Parallelphase.
- Test: Dry-Run-Modus für alle Skripte; Import gegen ein Supabase-Staging-Projekt.

### Phase 5: Client (`wingman-client`)

- [ ] 5.1 Tauri: `tauri-plugin-deep-link` mit Scheme `wingman`, `tauri-plugin-single-instance` (Windows/Linux), `tauri-plugin-opener` für den Systembrowser. macOS: Deep-Links nur im gebündelten Build, im Dev Loopback `http://localhost:5173/auth/callback` verwenden.
- [ ] 5.2 `authService.ts` neu: `@supabase/supabase-js` mit `flowType: 'pkce'`, `skipBrowserRedirect: true`, Session-Storage im Tauri-Store; `signInWithOAuth({provider})` → Systembrowser; Callback → `exchangeCodeForSession`; danach Geräte-Token holen und als Core-Secret `wingman_pro` speichern (Name beibehalten, damit Core-Seite minimal bleibt). MSAL-Abhängigkeit entfernen.
- [ ] 5.3 Umschalter: Env `PUBLIC_AUTH_BACKEND=azure|new` und `PUBLIC_API_BASE_URL`; im Beta-Build `new`, im Stable-Build bis Phase 9 `azure`. Beide Pfade bleiben bis Phase 9 im Code.
- [ ] 5.4 `stores.ts`: `isPro`, `isUltra`, `hasTrial` aus `/api/me` statt aus Token-Claims.
- [ ] 5.5 `RegionPrompt` und Region-Settings entfernen (hinter dem Umschalter, erst im Stable-Release wirksam).
- [ ] 5.6 Subscribe-Seite: Checkout-URL mit `x-user-id` statt `x-azure-user-id`; Subscription-Details aus `/api/me/subscription`; Suspend/Renew über Backend.
- [ ] 5.7 ToS-Dialog gegen `/api/me` und `POST /api/me/terms`.
- [ ] 5.8 Verbrauchsanzeige in den Einstellungen (Tokens, STT-Minuten, TTS-Zeichen des Monats gegen Limit), nur gerendert wenn `/api/me` Verbrauchsdaten liefert (`usage_visible`).
- [ ] 5.10 ToS-Dialog vergleicht `terms_version` aus `/api/me` mit dem Nutzerstand; beim Cutover erscheint er für alle einmal.
- [ ] 5.9 Beta-Updater-Kanal: Release `3.2.0-beta.x` mit `new`.
- Test: Login auf macOS und Windows (Bundle), App-Neustart nach 25 Stunden ohne Re-Login, Kündigen/Renew im Testmodus.

### Phase 6: Core (`wingman-ai`)

- [ ] 6.1 `providers/wingman_subscription.py`: Basis-URL aus Settings, Endpunkte auf `/api/v1/*`, Bearer bleibt `wingman_pro`. 401/403/429 sauber an den Client melden (429 mit `resets_at` als Hinweistext).
- [ ] 6.2 `WingmanProSttProvider`: `whisper`, `azure_speech` → `cloud` (ein Eintrag; Modell entscheidet das Backend). `WingmanProTtsProvider`: `azure` → `openai`, `inworld` bleibt. Migration `migration_316_to_320.py`: Azure-Stimme → Inworld-Stimme gleicher Sprache und gleichen Geschlechts (Mapping-Tabelle aus der heutigen `/azure-voices`-Liste erzeugen), Fallback OpenAI-Stimme.
- [ ] 6.3 `wingman_pro.region` und `/wingman-pro-regions` entfernen; `base_url` Default `https://api.wingman-ai.com`.
- [ ] 6.4 `get_wingman_pro_models` → `/api/v1/models`.
- Test: bestehende Provider-Tests; manuelle Session mit Beta-Client.

### Phase 7: Website (`wingman-website`)

- [ ] 7.1 Supabase-Login (gleiche Projekt-Keys), Account-Seite: Plan, `plan_until`, Verbrauch (wenn `usage_visible`), Link ins PayPro-Portal, Geräte, ToS-Zustimmung für die aktuelle Version.
- [ ] 7.2 Pricing-Seite: Buttons mit Checkout-URL inkl. `x-user-id` und `billing-email`, wenn eingeloggt; sonst erst Login.
- [ ] 7.3 `/api/pricing` bleibt; `PUBLIC_GET_PRODUCTS_URL` auf `api.wingman-ai.com/api/products`.
- Test: Kauf im Testmodus von der Website ohne installierten Client; danach Client-Login zeigt Plan.

### Phase 8: Beta-Test mit dem eigenen Account

Voraussetzung: Phasen 0–2, 4.4 (Einzelimport), 5, 6 fertig.

1. Eigenen B2C-Account per `import-users --only-email` importieren.
2. Zweite IPN-URL `https://api.wingman-ai.com/api/webhooks/paypro` bei PayPro eintragen (Store Settings → General Settings → Integration, eine URL pro Zeile). Ab jetzt Schattenbetrieb für alle Nutzer; `subscriptions`-Zeilen ohne `user_id` sind erwartet, bis 4.4 komplett läuft.
3. Beta-Client installieren, Login, Sprach-Session, Kündigen und Renew im Testmodus (Testprodukte), Bild, Inworld-Stimme.
4. Ein bis zwei externe Tester mit ihrem Einverständnis: ihre Accounts einzeln importieren, Beta-Link geben.
5. `compare-shadow.ts` täglich laufen lassen, Abweichungen fixen.
6. Produktivnutzer merken nichts: Stable-Client spricht weiter mit B2C und wingman-api, der alte Webhook pflegt B2C weiter.

### Phase 9: Cutover

- [ ] 9.1 T-7: Vollimport aller Nutzer und Subscriptions, Join-Report ohne offene Mehrdeutigkeiten. `stamp-paypro.ts` ausführen.
- [ ] 9.2 T-7: Website-Login live.
- [ ] 9.3 T0: Client `3.2.0` im Stable-Kanal mit `PUBLIC_AUTH_BACKEND=new`. Release-Notes: "Einmal neu anmelden." Für E-Mail/Passwort-Nutzer erklärt der Login-Screen den Magic-Link.
- [ ] 9.4 T0 bis T+30: beide Backends laufen, beide IPN-URLs aktiv. Support-Fälle: Nutzer ohne Zuordnung im Admin manuell verknüpfen (Suche nach PayPro-E-Mail).
- [ ] 9.5 T+30: alte IPN-URL entfernen; wingman-api, wingman-webhook, slickgpt-api stoppen (nicht löschen); alter Client-Pfad aus dem Code entfernen.
- [ ] 9.6 T+60: B2C-Tenant und Azure-Ressourcen löschen; Legacy-Paddle/Stripe-Code entfernen.

Rollback bis T+30: neue IPN-URL entfernen, Stable-Release auf `3.1.x` zurücksetzen. Das alte System war nie aus.

## 3. Tests und Abnahme

- Unit: IPN-Validierung, Plan-Auflösung, Limit-Entscheidung (Tabelle aus Beispielen: 0 %, 69 %, 70 %, 100 %, Override, gesperrt).
- Contract: heutige wingman-api-Antworten vs. neue Routen für `/ask` (stream und non-stream, mit tools), Whisper-Transkript, Inworld-Stream (Header, Chunk-Größe), Bild-Data-URL.
- E2E im Testmodus: Kauf Pro monatlich, Trial, Kündigen, Renew, Ablauf (Cron), Upgrade Pro → Ultra (`ChangeProduct`), jeweils Zustand in `/api/me` prüfen.
- Schatten: `compare-shadow.ts` über mindestens 14 Tage ohne unerklärte Abweichung.
- Beta: 25-Stunden-Test ohne Re-Login auf macOS und Windows.

## 4. Relay für PayPro-API-Calls

PayPro verifiziert API-Aufrufe per IP-Allowlist. Vercel Pro hat keine feste Ausgangs-IP; das Zusatzprodukt "Static IPs" kostet $100/Monat pro Projekt, "Secure Compute" ist Enterprise. Der Hostinger-Server ist die günstige Lösung.

Betroffene Aufrufe (alle `POST https://store.payproglobal.com/api/...`): `Products/GetProductPricing`, `Subscriptions/GetSubscriptionDetails`, `Subscriptions/Suspend`, `Subscriptions/Renew`, `Subscriptions/GetList`, `Subscriptions/ChangeCustomFields`, `Orders/GetOrderDetails`.

Relay-Design (bewusst minimal):
- Eine Route `POST /paypro/*`, prüft `Authorization: Bearer <RELAY_SECRET>`, ergänzt `vendorAccountId` und `apiSecretKey` serverseitig (die Keys liegen nur auf dem Relay, nicht auf Vercel), leitet Body an PayPro weiter, gibt Antwort zurück. Kein State, keine DB.
- VPS: Node- oder Python-Service hinter Caddy (HTTPS, `relay.wingman-ai.com`), systemd, IP-Allowlist eingehend optional auf Vercel-Ranges verzichten und nur das Secret prüfen. Shared Hosting: dieselbe Logik als eine PHP-Datei mit `curl`.
- Ausfall des Relays betrifft nur Preise, Kündigen/Renew und den Abgleich, nicht Login oder AI-Anfragen. `/api/products` cached 10 Minuten.
- Monitoring später optional über Better Stack.

Entschieden: Hostinger KVM 2, also VPS mit eigener IPv4. Variante Node-Service hinter Caddy.

## 5. Secrets und Konfiguration

| Wo | Was |
|---|---|
| Vercel `wingman-backend` | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_JWKS_URL`, `AI_GATEWAY_API_KEY`, `INWORLD_API_KEY`, `PAYPRO_VALIDATION_KEY`, `PAYPRO_SECRET_KEY`, `RELAY_URL`, `RELAY_SECRET` |
| Hostinger-Relay | `PAYPRO_ACCOUNT_ID`, `PAYPRO_API_KEY`, `RELAY_SECRET` |
| Client (public) | `PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_ANON_KEY`, `PUBLIC_API_BASE_URL`, `PUBLIC_AUTH_BACKEND`, PayPro-Checkout-Variablen wie heute |
| Website | wie Client plus Server-Keys für Account-Seite |
| Migrationsskripte (lokal) | Graph-App-Credentials aus wingman-webhook, PayPro-Keys, Supabase Service Role |

## 6. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| PayPro-Custom-Feld fehlt bei manchen IPN-Typen | Fallback auf `CUSTOMER_EMAIL` und `SUBSCRIPTION_ID`-Lookup; Schattenbetrieb zeigt es vor dem Cutover |
| Nutzer mit anderer E-Mail bei PayPro als beim Login | Join über `x-azure-user-id`; Rest manuell im Admin |
| Deep-Link auf macOS nur im Bundle | Dev über Loopback; Beta-Test nur mit gebündelten Builds |
| Vercel-Streaming bricht bei 800 s | Chat-Streams sind unter 2 Minuten; Inworld-Streams unter 1 Minute |
| Cloudflare-Proxy vor `api.wingman-ai.com` limitiert Body/Streaming | DNS-only für die API-Domain |
| Relay down | nur Preise/Kündigen betroffen; Cache; Monitoring |
| Gateway-Modell abgekündigt | `model_routes` im Admin ändern; zusätzlich Vercel Routing Rule als Notfall |
| Supabase-Mail-Limit | eigener SMTP ab Phase 0 |

## 7. Entschieden am 2026-09-10

1. **Hostinger KVM 2** (VPS-Tarif mit eigener IPv4): Relay als kleiner Node-Service hinter Caddy, systemd, `relay.wingman-ai.com`. Vor dem Allowlisten die Ausgangs-IP auf dem Server prüfen (`curl -4 ifconfig.me`) und genau diese an den PayPro-Support geben.
2. **ToS neu akzeptieren.** `TERMS_VERSION` wird beim Cutover hochgesetzt. Der importierte Zeitstempel aus B2C wandert als Historie in `users.terms_accepted_at`, gilt aber nicht für die neue Version. Jeder Nutzer nickt im neuen Client und auf der Website genau einmal.
3. **Verbrauch sichtbar.** 5.8 und 7.1 sind Pflicht. Schalter `app_settings.usage_visible` (global) und optional pro Plan, damit die Anzeige ohne Release ausgeblendet werden kann. `/api/me` liefert Verbrauch und Limits nur, wenn der Schalter an ist.
4. **Repo `ShipBit/wingman-backend`.**

Ergänzung Datenmodell: `app_settings(key text primary key, value jsonb, updated_by, updated_at)` mit `terms_version`, `usage_visible`, `maintenance_message`. Pflege im Admin.

## 8. Status (Übergabe 2026-09-10, 13:00)

Erledigt:
- Supabase-Projekt `wingman-prod` angelegt, Ref `bkmmccpxmrccaeikyila`, Central EU (Frankfurt), Org ShipBit, noch **Free** (Pro erst vor dem Cutover). Data API an, "Automatically expose new tables" aus, automatic RLS an.
- Google OAuth-Client "Supabase Auth" im GCP-Projekt `wingmanai-414509` (Web application, Origin + Redirect auf die Supabase-Domain). Branding: `bkmmccpxmrccaeikyila.supabase.co` als Authorized Domain ergänzt, Publishing status auf "In production" gestellt. Der Consent Screen wird auch von B2C (`b2clogin.com`) genutzt, nichts entfernen.
- 1Password, Vault "Shared": `op://Shared/Supabase Wingman Prod Database/dbPass`, `op://Shared/Google OAuth Wingman/Client ID`, `op://Shared/Google OAuth Wingman/Client Secret`.
- CLIs eingeloggt: `supabase` (sieht das Projekt), `vercel` (User `shipbitbot`), `gh` (Shackless), `op` (ShipBit-Konto). SSH-Key `~/.ssh/id_ed25519.pub`.

Noch nicht begonnen:
- Repo `wingman-backend` (lokal unter `/Users/shackles/Source/wingman-backend`, GitHub `ShipBit/wingman-backend` noch anzulegen). Nächster Schritt: SvelteKit-Scaffold, `supabase link`, Migrationen aus Abschnitt 1, Google-Provider und Redirect-Allowlist per `supabase/config.toml` + `supabase config push`.
- Ausstehende 1Password-Items: SMTP, Vercel AI Gateway Key, PayPro (Keys + 8 Produkt-IDs), Azure Graph Export, Inworld, Hostinger Relay (IP, User), optional Cloudflare DNS Token.

# Wo die Zugangsdaten liegen und wohin sie gehören

Stand 2026-09-10. Gehört zu `plan.md`, Phase 0. Jede Zeile: wo der Wert heute
steht, wo er künftig hin muss.

## 1. Google-Provider in Supabase (blockiert jeden Login-Test)

Der Wert im Projekt ist aktuell der Platzhalter `local-dev.apps.googleusercontent.com`.

1. https://supabase.com/dashboard/project/bkmmccpxmrccaeikyila/auth/providers
2. Zeile **Google** aufklappen (Toggle "Enable Sign in with Google" ist schon an).
3. **Client IDs**: die Client-ID aus `op://Shared/Google OAuth Wingman/Client ID`
   eintragen. Das Feld heißt Plural und akzeptiert eine Liste — es darf nur
   dieser eine Wert drinstehen, der Platzhalter muss raus.
4. **Client Secret (for OAuth)**: `op://Shared/Google OAuth Wingman/Client Secret`.
5. **Save** unten rechts. Ohne Save passiert nichts.

Prüfen (die Client-ID steht im Redirect, das ist die einzige verlässliche Probe):

```sh
curl -s -i "https://bkmmccpxmrccaeikyila.supabase.co/auth/v1/authorize?provider=google" \
  | grep -i '^location'
```

`-s -i`, nicht `-sI`: mit `-I` schickt curl ein HEAD, und darauf antwortet GoTrue
mit 405 ganz ohne `Location`-Header — man sieht dann nichts und hält es für kaputt.

Erwartet: `client_id=…apps.googleusercontent.com` mit der echten ID.

**Erledigt am 2026-09-10:** Client-ID `1080940440260-…apps.googleusercontent.com`
steht im Projekt. Google nimmt sie an — der Redirect landet auf der Anmeldeseite,
kein `invalid_client`, kein `redirect_uri_mismatch` — und `wingman://auth/callback`
übersteht den Authorize-Aufruf, die Redirect-Allowlist stimmt also auch. Was ein
Skript nicht prüfen kann, ist der Login selbst; das zeigt erst der Beta-Client.

Wichtig: **kein `supabase config push` ausführen, solange nicht klar ist, was es
ändert.** Der Google-Provider ist deshalb bewusst nicht mehr in `config.toml`
deklariert. Vor jedem Push `supabase config diff` lesen.

## 2. PayPro-Werte aus dem Azure-Portal holen

**Erledigt am 2026-09-10.** Simon hat den App-Settings-Export als
`/Users/shackles/Source/wingman-backend/azure.json` abgelegt. Die Datei ist
`chmod 600`, steht in `.gitignore` und war nie in einem Commit. Die vier Werte
liegen damit lokal vor; sie müssen noch nach Vercel bzw. auf den Relay-VPS.
`scripts/vercel-env.sh production` schiebt sie in ein verlinktes Vercel-Projekt,
ohne sie auszugeben. Die acht Produkt-IDs aus dem Export sind identisch mit denen
in der wingman-client-`.env` und stehen bereits in `paypro_products`.

Alle vier Werte laufen heute produktiv in der Function App `wingman-webhook`.
Das ist die verlässliche Quelle — nicht im PayPro-Panel suchen, wenn es nicht
sein muss.

1. https://portal.azure.com → oben suchen: `wingman-webhook` → die **Function App**
   öffnen (nicht die Resource Group, nicht den Storage Account).
2. Linkes Menü → **Settings** → **Environment variables** (in der älteren Ansicht:
   **Configuration** → Tab **Application settings**).
3. Auf den Namen klicken, dann **Show value**. Mit **Advanced edit** sieht man alle
   Einträge auf einmal als JSON, das ist beim Kopieren schneller.

| Azure-App-Setting | Neues Ziel | Wohin |
|---|---|---|
| `PayProValidationKey` | `PAYPRO_VALIDATION_KEY` | Vercel-Projekt `wingman-backend` |
| `PayProSecretKey` | `PAYPRO_SECRET_KEY` | Vercel-Projekt `wingman-backend` |
| `PayProApiKey` | `PAYPRO_API_KEY` | **nur** Relay-VPS, `/etc/paypro-relay.env` |
| `PayProAccoundId` (Tippfehler ist im Original) | `PAYPRO_ACCOUNT_ID` | **nur** Relay-VPS |

Für Phase 4 (B2C-Export) später aus derselben Liste: `AzureAppId`,
`AzureClientSecret`, `AzureTenantId`.

Die acht Produkt-IDs braucht es hier **nicht** mehr: sie stehen auch in der
`.env` von wingman-client (`PUBLIC_PAYPRO_PRO_MONTHLY` usw.) und sind am
2026-09-10 in `paypro_products` geschrieben worden — lokal und in `wingman-prod`.

Mit installierter Azure-CLI (`brew install azure-cli`, dann `az login`) geht es
ohne Klicken:

```sh
az functionapp config appsettings list -n wingman-webhook -g <resource-group> \
  --query "[?contains(name,'PayPro') || contains(name,'Azure')].{name:name,value:value}" -o table
```

## 3. Was im PayPro-Control-Panel zu tun ist

Zugang: https://cp.payproglobal.com (Vendor-Login). Die Pfade stammen aus PayPros
Doku, die Beschriftungen können minimal abweichen.

- **Validation key, Secret key, API secret key**: Store Settings → General Settings
  → **Integration**. Der API-Key ist dort regenerierbar — nicht neu erzeugen,
  sonst bricht die alte Azure-Function.
- **vendorAccountId**: Account Settings → **Business info**.
- **IP-Allowlist für API-Calls: nicht anfordern, bevor das Relay steht.** Gemessen
  am 2026-09-10 antwortet PayPro auf `Products/GetProductPricing` und
  `Subscriptions/GetList` von einer normalen Privatanschluss-IP. Für dieses Konto
  ist also **keine** Allowlist aktiv, und das Backend kann PayPro direkt aufrufen.
  Ein Support-Ticket würde das Konto in den Allowlist-Modus schalten und damit
  alle anderen Quellen sperren, Vercel eingeschlossen. Also erst das Relay
  aufsetzen, dann die IP melden — oder ganz darauf verzichten. IP auf der
  Maschine selbst holen, nicht aus dem Hostinger-Panel:
  ```sh
  curl -4 ifconfig.me
  ```
- **Zweite IPN-URL** (erst in Phase 8, nicht jetzt): Store Settings → General
  Settings → **Integration**, Feld *IPN URLs*, eine URL pro Zeile. Die alte Azure-URL
  bleibt stehen, `https://api.wingman-ai.com/api/webhooks/paypro` kommt darunter.
- **IPN-Log und Resend**: Reports → Others → **IPN**. Einzelne Events auswählen und
  über das Brief-Symbol bzw. Bulk actions → Resend erneut schicken. Resends tragen
  `IS_RESENT=1`.
- **IPN-Simulator**: https://cc.payproglobal.com/Tools/SimulateIpn — schickt einen
  vollständigen Testfall an eine frei wählbare URL. Damit lässt sich der Webhook
  gegen ein Vercel-Preview-Deployment testen, bevor irgendetwas Echtes umgestellt wird.
- **Testbestellung**: an die Checkout-URL `&use-test-mode=true&secret-key=<Secret Key>`
  anhängen. In Testbestellungen ist `HASH` = `md5("1")`, das ist im Webhook bereits
  berücksichtigt.

## 4. Was jetzt noch offen ist

1. ~~Google-Provider reparieren~~ — erledigt und geprüft.
2. ~~Die vier PayPro-Werte aus Azure kopieren~~ — liegen in `azure.json`.
3. **Vercel-Projekt anlegen**, `vercel link`, dann `scripts/vercel-env.sh production`
   für die PayPro-Werte, den Rest (Supabase, AI Gateway, Inworld, `CRON_SECRET`)
   von Hand. Domain `api.wingman-ai.com` als DNS-only bei Cloudflare.
4. **Entscheidung Relay ja/nein.** Ohne Allowlist läuft der direkte Weg; das
   Relay ist fertig, kostet aber einen VPS und ein bewegliches Teil mehr. Wenn
   nein: `PAYPRO_ACCOUNT_ID` und `PAYPRO_API_KEY` in Vercel setzen. Wenn ja:
   Relay aufsetzen, `RELAY_URL`/`RELAY_SECRET` in Vercel setzen, die beiden
   PayPro-Keys dort wieder löschen.
5. IPN-Simulator gegen das Preview-Deployment (Phase 8), zweite IPN-URL erst danach.

## 5. Gemessene Eigenheiten der PayPro-API (2026-09-10)

Gegen das echte Konto ermittelt, weil die Doku dünn war:

- `Subscriptions/GetList` pagiert mit `skip` und `take`; `take` über 100 ergibt 400.
  `response` ist ein flaches Array. Felder pro Eintrag: `id`, `status` als Wort
  (`Active`, `Suspended`, `Terminated`, `Finished`), `nextPayment` als `M/D/YYYY`,
  `createdAt` als ISO, `isTrial`, `orders` (nur Order-IDs, und nur mit
  `includeOrders: true`). Kein Produkt und kein Status-Filter im Request.
- Bestand heute: **1773 Subscriptions, davon 257 aktiv, 1374 suspended,
  142 terminated, 833 mit Trial-Flag.** Das deckt sich mit der Annahme
  "250–350 aktive" aus der Recherche.
- `Products/GetProductPricing` lehnt eine IPv6-Adresse in `ipAddress` mit
  "IpAddress is invalid." ab und kippt den ganzen Aufruf, wenn eine `productId`
  nicht numerisch ist. Beides fängt `/api/products` jetzt ab.
- Preise heute für DE/EUR: Pro 5,99 monatlich und 59,99 jährlich, Ultra 9,99 und
  89,99, jeweils inklusive Steuer.

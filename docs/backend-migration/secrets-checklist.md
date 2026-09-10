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
curl -sI "https://bkmmccpxmrccaeikyila.supabase.co/auth/v1/authorize?provider=google" \
  | grep -i '^location'
```

Erwartet: `client_id=…apps.googleusercontent.com` mit der echten ID.

Wichtig: **kein `supabase config push` ausführen, solange nicht klar ist, was es
ändert.** Der Google-Provider ist deshalb bewusst nicht mehr in `config.toml`
deklariert. Vor jedem Push `supabase config diff` lesen.

## 2. PayPro-Werte aus dem Azure-Portal holen

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
- **IP-Allowlist für API-Calls**: geht nur über den Support. Ticket mit der
  Ausgangs-IP des VPS aufmachen; die IP auf der Maschine selbst holen, nicht aus
  dem Hostinger-Panel:
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

## 4. Reihenfolge, die am wenigsten Leerlauf erzeugt

1. Google-Provider reparieren (oben, 2 Minuten) — danach ist der Login testbar.
2. Die vier PayPro-Werte aus Azure kopieren.
3. Support-Ticket bei PayPro für die IP-Allowlist aufmachen; das dauert extern am
   längsten, deshalb früh.
4. Relay auf dem VPS aufsetzen (`relay/README.md` im Backend-Repo).
5. Vercel-Projekt anlegen, Env-Variablen setzen, Domain `api.wingman-ai.com`
   DNS-only.
6. Erst dann IPN-Simulator gegen das Preview-Deployment.

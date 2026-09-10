# Offene Fragen und Entscheidungen

Stand 2026-09-11, nachts. Ergänzt `plan.md` (Fortschritt) und
`secrets-checklist.md` (Zugangsdaten). Hier steht nur, was noch **entschieden**
oder **von Simon erledigt** werden muss.

## Entschieden, umgesetzt

| Frage | Entscheidung |
|---|---|
| Relay auf dem Hostinger-VPS | entfällt. PayPro antwortet von jeder IP, das Backend ruft direkt auf. `relay/` bleibt einsatzbereit. **Kein Allowlist-Ticket beim Support**, das würde Vercel aussperren. |
| Modell für Chat | `openai/gpt-4.1-mini` bleibt Standard, Downgrade auf `openai/gpt-4.1-nano` statt `gpt-5-nano` (kein Reasoning, gleiche Familie, Tool-Calling). |
| Bildqualität | `quality: low` als Standard, `medium` erlaubt, `high` nicht angeboten. 0,22 statt 3,3 Cent pro Bild. |
| Planwechsel Pro ↔ Ultra | Monatsabos sofort, ohne Aufpreis. Jahresabos zum Verlängerungstermin, mit Hinweis auf Discord für Sofortwechsel von Hand. PayPro kann keine anteilige Verrechnung. |
| Manuelle Freipläne | bleiben unverändert. Sichtbar im Admin unter „Freipläne“. |
| Import | alle Nutzer und Subscriptions sind in Produktion importiert. Skripte sind idempotent und laufen vor dem Cutover erneut. |

## Morgen als Erstes: IPN-Report prüfen

**Frage:** Feuert die zweite IPN-URL aus den Store-Einstellungen für echte
Bestellungen, oder überstimmt das Produkt-Feld sie?

Simon hat am 2026-09-10 gegen 21:44 UTC in Store Settings → General Settings →
Integration eine zweite Zeile ergänzt:
`https://api.wingman-ai.com/api/webhooks/paypro`. Das Produkt-Feld
(Store settings → Product setup → IPN URL) nimmt nur **eine** Adresse und zeigt
weiterhin auf `https://wingman-webhook.azurewebsites.net/api/PayProWebhook` —
das muss so bleiben, sonst hört das alte System auf, B2C zu pflegen.

**So prüfen:** cp.payproglobal.com → Reports → Others → IPN, Filter auf
*Isn't test mode*, Zeitraum seit dem 10.09. 21:44 UTC. Bei rund 250 aktiven Abos
läuft über Nacht mindestens eine Verlängerung durch.

- **Zwei Zeilen pro Ereignis**, eine mit der Azure-URL und eine mit unserer:
  Parallelbetrieb läuft, nichts weiter zu tun.
- **Nur eine Zeile:** das Produkt-Feld gewinnt. Dann PayPro-Support fragen, ob es
  dort mehrere Adressen oder einen Wildcard akzeptiert. Notfalls erst am Cutover
  umschalten — kostet den Schattenbetrieb, geht aber.

## Fallen, die in der Nacht auf den 11.09. zugeschnappt sind

### PostgREST hört bei 1000 Zeilen auf — ohne Fehler

Das Admin-Dashboard zeigte 1000 Nutzer und 1000 Subscriptions. Beides falsch:
`db.from('users').select(...)` liefert höchstens 1000 Zeilen und meldet das
nicht. Die echten Zahlen sind 5547 Nutzer und 1774 Subscriptions.

Behoben in zwei Schritten:

* `admin_overview(p_today, p_month_start)` (Migration
  `20260911000000_admin_overview.sql`) zählt in Postgres. Der Endpunkt ruft nur
  noch diese Funktion auf.
* `selectAll()` in `src/lib/server/admin.ts` blättert in 1000er-Schritten
  durch. Genutzt vom CSV-Export (Nutzer und Verbrauch) und von den Freiplänen.
  **Jede neue Abfrage, die eine ganze Tabelle abdecken soll, muss das
  benutzen** — sonst fehlen ab Zeile 1001 stillschweigend Daten.

### Deployments aus Git schlugen seit dem ersten Tag fehl

Jeder Push erzeugte zwei Deployments: eins aus Git (**immer ERROR**) und eins
aus der CLI (READY). Nur die CLI-Deployments waren je live. Grund:

* Alle Geheimnisse kamen über `$env/static/private`, also **zur Bauzeit**.
* In Vercel sind sie als *Sensitive* angelegt, und sensitive Werte sind beim
  Bauen nicht lesbar. Der Git-Build brach mit
  `[MISSING_EXPORT] "AI_GATEWAY_API_KEY" is not exported` ab.
* `AI_GATEWAY_API_KEY` fehlte in Vercel überhaupt. Der lokale Build hat ihn aus
  `.env` genommen und **fest in das Bundle geschrieben** — der Schlüssel lag im
  ausgelieferten Code.

Behoben: alle sieben Dateien lesen jetzt über `$env/dynamic/private` zur
Laufzeit, und `AI_GATEWAY_API_KEY` liegt als *Encrypted* in Vercel
(production, preview, development). Seither läuft der Git-Build durch, und im
Build-Ergebnis steht kein `vck_`-Schlüssel mehr.

**Regel:** im Backend nie wieder `$env/static/private` für ein Geheimnis.

### Core sprach lokal, nicht über das Backend

`wingman_pro.tts_provider: openai` allein reicht nicht — solange
`features.tts_provider` auf `pocket_tts` steht, wird lokal gesprochen und das
Backend sieht keinen einzigen TTS-Aufruf. Simons Config steht jetzt auf
`features.tts_provider: wingman_pro`. Zurück auf lokal: dieses Feld wieder auf
`pocket_tts` setzen.

### Das Modell im Config war ein Name, keine Alias

`wingman_pro.conversation_deployment` stand auf `gpt-4.1-mini`. Das Backend
liefert unter `/api/v1/models` aber nur `default` und `fast` — der Name passte
zu keinem Eintrag, das Auswahlfeld im Client wäre leer geblieben. Die Migration
316→320 schreibt jeden unbekannten Wert auf `default` um.

Nebenwirkung: `conversation_manager.py` entschied an `"gpt" in
conversation_deployment` , ob es Tool-Call-IDs im OpenAI-Format erzeugt. Mit
einem Alias war das falsch. Prüft jetzt nur noch den Provider.

## Ende-zu-Ende belegt (11.09., nachts)

Ein Durchlauf über das neue Backend, gemessen an `usage_daily`:

| Schritt | Beleg |
|---|---|
| Anmeldung | Magic Link → Geräte-Token `wgd_…` → Core, Tower mit ATC und Computer gebaut |
| Modellliste | `/api/v1/models` liefert `{plan: "pro", models: [default, fast]}` |
| Frage | `conversation_token_usage` 1681/26, Chat über `openai/gpt-4.1-mini` |
| Antwort | „Alle Hauptsysteme sind online und funktionsfähig …" |
| Sprachausgabe | `playback_started` → `playback_finished`, `openai/tts-1`, TTS-Zeichen 52 → 170 → 280 |
| Dashboard | Verbrauch, Kosten je Modell und die echten Nutzerzahlen sichtbar |

## Erkenntnis: `ipn-domain` bindet die Zustellung an die Bestellung

Am 2026-09-10 gemessen. Der Client hängt bei Testkäufen
`&ipn-domain=wingman-webhook-test.azurewebsites.net` an die Checkout-URL. PayPro
merkt sich das **pro Bestellung** und schickt alle künftigen Nachrichten dieser
Subscription dorthin, unabhängig von jeder Store-Einstellung. Deshalb kam der
erste Testversuch nie bei uns an — nicht weil die Konfiguration falsch war.

Wichtig dabei: PayPro tauscht nur den **Hostnamen** und behält den **Pfad** aus
der konfigurierten IPN-URL, also `/api/PayProWebhook`. Das Backend bedient
diesen Pfad jetzt zusätzlich als Alias auf `/api/webhooks/paypro`
(`src/routes/api/PayProWebhook/+server.ts`). Damit lässt sich jede Testbestellung
mit `ipn-domain=api.wingman-ai.com` direkt an uns leiten — der Weg, um den
Webhook mit echten Daten zu testen, ohne das Live-System anzufassen.

## Bewiesen am 2026-09-10, 21:57 UTC

Erste echte PayPro-IPN durch die volle Kette:

```
Bestellung 44235457, IPN-Typ 13 (TrialCharge)
  IP-Allowlist   bestanden
  MD5 HASH       bestanden
  SHA256 SIGNATURE bestanden
  Subscription 5362626 angelegt: pro, active, Trial, bis 17.09.2026
  Zuordnung über x-azure-user-id -> legacy_b2c_object_id
  Nutzer simon.hopstaetter@shipbit.de: plan pro, Quelle paypro
```

Damit ist der Webhook nicht mehr nur gegen selbst signierte Anfragen getestet,
und die Nutzer-Zuordnung über die importierte B2C-Objekt-ID funktioniert in der
Praxis — genau der Mechanismus, an dem beim Cutover 1763 Subscriptions hängen.

**Testdaten, die dafür existieren:** Zwei Subscriptions im PayPro-Testmodus auf
`simon.hopstaetter@shipbit.de`, beide dürfen angefasst werden:
`5362578` (Bestellung 44235140, IPNs gehen an den Azure-Test-Host) und
`5362626` (Bestellung 44235457, IPNs gehen an uns). Echte Kundenabos bleiben tabu.

## Offen, braucht eine Entscheidung von Simon

1. **Zweite IPN-URL bei PayPro eintragen** (Store Settings → General Settings →
   Integration, eine URL pro Zeile): `https://api.wingman-ai.com/api/webhooks/paypro`.
   Die alte Azure-URL bleibt stehen. Das ist die erste Änderung am Live-System,
   rein additiv. Ab dann laufen beide Backends parallel mit und wir verlieren
   keine Zahlung mehr. Ohne diesen Schritt bleibt jeder Import ein Standbild.

2. **Was passiert mit den 183 manuellen Freiplänen langfristig?** Sie laufen nie
   ab. Möglichkeiten: so lassen, ein Enddatum in zwölf Monaten setzen, oder nach
   Verbrauch aufräumen, sobald der Client umgezogen ist und die Ansicht zeigt,
   wer das Produkt überhaupt nutzt.

3. **Die 13 Subscriptions ohne zugeordneten Nutzer.** Gelöschte B2C-Konten. Vor
   dem Cutover einmal durchsehen, ob eine davon noch aktiv ist.

4. **Die 2 zahlenden Nutzer ohne Plan in B2C.** Die zahlen und haben womöglich
   keinen Pro-Zugang. Support-Fall, nicht technisch.

5. **147 Konten ohne jede E-Mail-Adresse** wurden nicht importiert (GitHub gibt
   sie nicht immer heraus). Alle ohne Plan und ohne Zahlung. Sie legen beim
   ersten Login neu an. Wenn das nicht reicht, bräuchte es einen Abgleich über
   die GitHub-ID — Aufwand lohnt sich vermutlich nicht.

6. **Resend-Tarif und Mail-Limit vor dem Cutover.** 2380 Konten melden sich mit
   E-Mail und Passwort an und brauchen je einen Magic Link. `email_sent` steht
   auf 100 pro Stunde.

7. **Supabase Pro** vor dem Cutover (aktuell Free).

## Ungeprüft, bis echte Daten fließen

- **Der Webhook hat noch nie eine echte PayPro-IPN gesehen.** Getestet wurde mit
  selbst signierten Anfragen und dem IPN-Simulator-Format. Der erste echte Test
  ist die zweite IPN-URL.
- **Der Downgrade-Pfad im Chat** greift nachweislich (Log zeigt den Modellwechsel
  samt Fallback-Kette), ist aber nie mit Guthaben durchgelaufen.
- **Deep-Link und Login im Client** — Phase 5, noch nicht gebaut.

## Fallen, die schon zugeschnappt sind

Damit sie nicht ein zweites Mal zuschnappen:

- `supabase config push` löst `env()` aus der lokalen `.env` auf und schreibt
  ohne Rückfrage. Hat einmal die Google-Client-ID durch einen Platzhalter
  ersetzt. Immer erst `supabase config diff` lesen. Der Google-Provider ist
  deshalb bewusst **nicht** in `config.toml` deklariert.
- SvelteKits CSRF-Schutz beantwortet form-encodete POSTs ohne `Origin` mit 403,
  **und ist im Dev-Server abgeschaltet**. PayPros IPN lief im ersten Deploy
  dagegen. Auflage: das Admin-Panel darf niemals Cookie-Authentifizierung
  benutzen, sonst wird aus dem Kompromiss eine Lücke.
- `accountEnabled` in B2C ist **kein** Nutzerzustand. Jedes Social-Login-Konto
  steht auf `false`, jedes Passwort-Konto auf `true`. 133 zahlende Kunden sehen
  darin aus wie gesperrt.
- Die Importskripte schreiben dorthin, wohin `SUPABASE_URL` zeigt — und in der
  `.env` steht die lokale Adresse. Beide Skripte sagen den Zielort jetzt beim
  Start an.
- Vercel speichert keine leeren Umgebungsvariablen, und CLI-gesetzte Werte sind
  danach nicht mehr auslesbar (`CRON_SECRET` liegt deshalb in der lokalen `.env`).

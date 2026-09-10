# Offene Fragen und Entscheidungen

Stand 2026-09-10, spät abends. Ergänzt `plan.md` (Fortschritt) und
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

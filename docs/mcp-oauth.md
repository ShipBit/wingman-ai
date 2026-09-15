# MCP OAuth

Hosted MCP servers increasingly refuse API keys. ElevenLabs' hosted server is the
example that forced this: `POST https://api.elevenlabs.io/v1/mcp` without a token
answers

```
HTTP/2 401
www-authenticate: Bearer resource_metadata="https://api.us.elevenlabs.io/.well-known/oauth-protected-resource"
{"detail":"OAuth bearer token required for the hosted MCP."}
```

Before this change Wingman could only send a static `Authorization: Bearer <secret>`
header, so every server of that kind was out of reach.

## What a user sees

An MCP server in `mcp.yaml` now carries an `auth` field with three values:

* `none` — no credentials, the default.
* `api_key` — the old behaviour. The secret `mcp_<name>` goes out as a bearer
  header. Configs written before 3.2.1 keep working: a server with a `headers`
  entry or a stored `mcp_<name>` secret behaves exactly as it did.
* `oauth` — the server is reached with an OAuth access token that Wingman
  obtains, stores and refreshes.

For an `oauth` server the MCP section of a wingman grows an **Authorize** button.
Pressing it opens the system browser at the provider's consent page. Once the
user consents, the provider redirects back to Wingman's own HTTP server, the
token is stored, and the button turns into a state badge with a **Sign out**
action.

## Why the redirect goes to Core

Core already runs a uvicorn server on port 49111. The OAuth redirect URI is

```
http://localhost:<core port>/mcp/oauth/callback
```

This is the loopback redirect every native MCP client uses, and it needs nothing
from Tauri: the browser talks to a local HTTP port, not to the app. It behaves
identically under `npm run dev` and in the bundled app, which a custom
`wingman://` deep link would not — the deep link plugin only fires for the
packaged build.

The consequence to know about: Core has to run on the same machine as the
browser. A Core on a remote host cannot complete the flow, because the
provider redirects the user's own browser to *their* localhost.

## Registration: two paths

The MCP spec expects Dynamic Client Registration (RFC 7591) and the Python SDK
does it automatically when the authorization server advertises a
`registration_endpoint`. Most hosted MCP servers do.

ElevenLabs does not. Its metadata has no `registration_endpoint`, and `/register`
answers 404 on every host we tried. It advertises
`client_id_metadata_document_supported: true` instead, so the client id is an
HTTPS URL pointing at a JSON document that describes the client.

So `McpServerConfig` has an optional `oauth_client_id`. When it is set, Wingman
seeds the SDK's client storage with it and the SDK skips registration entirely.
When it is empty, the SDK registers dynamically. Both paths then run the same
authorization code grant with PKCE.

## Where tokens live

In `secrets.yaml`, under the key `mcp_oauth_<server name>`, as a JSON blob
holding the token set, the expiry and the client information. That file is
already the place Wingman keeps credentials and is already excluded from
anything a user shares. No new file, no new format to migrate later.

## Connecting must never block on a browser

Wingman connects its MCP servers while a wingman boots. If the SDK's OAuth
provider were allowed to start a browser flow there, a wingman with an
unauthorized server would hang until someone noticed.

So there are two kinds of provider:

* **interactive** — built only by the authorize endpoint. Its callback handler
  waits on a future that the `/mcp/oauth/callback` route resolves.
* **silent** — built at connect time. It reuses a stored token and refreshes it
  when it is expired, but its callback handler raises immediately. A server that
  was never authorized fails fast with "needs authorization" instead of hanging.

## Files

Core:

| File | Change |
| --- | --- |
| `api/enums.py` | `McpAuthType` |
| `api/interface.py` | `auth`, `oauth_client_id`, `oauth_scopes` on `McpServerConfig`; OAuth status models |
| `services/mcp_oauth.py` | new — token storage, flow, provider factory |
| `services/mcp_client.py` | pass an `httpx.Auth` into the transports |
| `services/wingman_mcp_manager.py` | build the silent provider per server |
| `services/config_service.py` | authorize / status / revoke endpoints |
| `main.py` | the `/mcp/oauth/callback` route |
| `templates/configs/mcp.template.yaml` | the ElevenLabs entry |
| `services/migrations/migration_320_to_321.py` | backfill that entry into existing `mcp.yaml` |

Client:

| File | Change |
| --- | --- |
| `src/lib/Configuration/McpServerEditor.svelte` | auth type, client id, scopes |
| `src/lib/Configuration/McpConfig.svelte` | authorize / sign out, state badge |
| `src/services/mcpOAuthService.ts` | new — start the flow, open the browser |
| `messages/{en,de,fr,es}.json` | strings |

## The one thing that is not solved

ElevenLabs has no public client id and no way to register one. The template ships
the server with `oauth_client_id` empty and the field is editable in the UI, so a
user who has one can paste it. Giving Wingman a working one out of the box means
publishing a client id metadata document at an HTTPS URL Wingman controls —
`wingman-ai-mcp-servers` is the natural host — and that is a deploy, not a code
change.

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

The other consequence: OAuth is verified for the streamable-HTTP transport,
which is what ElevenLabs uses. SSE connections run on their own thread with
their own event loop, and the provider is built on the main loop, so a token
refresh on an SSE server would write to `secrets.yaml` from that thread. It has
not been tested.

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
  waits on a future that the `/mcp/oauth/callback` route resolves. That route
  then waits for the token exchange before answering the browser, so the page a
  user lands on says what happened rather than what was about to be attempted.
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
| `services/mcp_client.py` | pass an `httpx.Auth` into the transports; apply the tool filter |
| `services/wingman_mcp_manager.py` | build the silent provider per server |
| `services/config_service.py` | authorize / status / revoke endpoints |
| `main.py` | the `/mcp/oauth/callback` route |
| `templates/configs/mcp.template.yaml` | the ElevenLabs entry |
| `services/migrations/migration_320_to_321.py` | backfill that entry into existing `mcp.yaml` |

Client:

| File | Change |
| --- | --- |
| `src/lib/Configuration/McpServerEditor.svelte` | auth type, client id, scopes, tool filter |
| `src/lib/Configuration/McpConfig.svelte` | authorize / sign out, state badge |
| `src/services/mcpOAuthService.ts` | new — start the flow, open the browser |
| `messages/{en,de,fr,es}.json` | strings |

## The ElevenLabs entry, and the one step left

Two things about that server are not obvious and both cost a debugging round:

* **Use the regional URL.** Its protected resource metadata declares the resource
  as `https://api.us.elevenlabs.io/v1/mcp`. Connect to `https://api.elevenlabs.io/v1/mcp`
  and the SDK refuses the mismatch before any browser opens. The template uses
  the regional one.
* **Its client id is a URL.** `oauth_client_id` points at
  `https://wingman-ai-mcp-servers.wingman-ai.workers.dev/oauth/client`, a client
  id metadata document added to the worker repository on the branch
  `feat/oauth-client-metadata`.

The worker branch is merged and deployed. The whole path is verified against the
live server: discovery, the authorization URL, consent in a browser, the
callback, the token exchange, a silent refresh of an expired token, and the
failure pages.

A user who has their own client id can paste it into the server's settings
instead; the field is editable in the UI.

## Refreshing a stored token

A provider built from stored state never runs discovery, because discovery only
happens inside the SDK's 401 branch and a stored token does not produce a 401.
`_get_token_endpoint` then falls back to `<origin>/token`, which against
ElevenLabs is a 404 — the real one is `/v1/oauth/token` — and the SDK drops
through to the full browser flow.

Left alone that would have asked every user to authorize again every hour, with
a working refresh token sitting in the file. So the authorization server's
metadata is discovered once and cached in the token bundle next to the token.

## Tool count

A server's tool definitions go into the prompt in full once the model activates
that server, and stay there until the conversation is reset. Some servers are
far too large for that.

| ElevenLabs | tools | tokens |
| --- | --- | --- |
| everything | 111 | 222,142 |
| without the two largest | 109 | 101,151 |
| `creative_*` | 29 | 20,384 |

`agents_run_tests` alone is 72,840 tokens: a one-line description and a schema
carrying 336 definitions, the whole agent data model. `agents_create_draft` is
another 48,151.

Every tool a server offers is listed in the wingman's MCP settings with a
switch. Switching one off puts its name into `disabled_tools` on the server in
`mcp.yaml`, and `McpClient._build_tools` marks it `is_enabled: false`. The
model never sees it: `get_tool_definitions` skips it, the discovery manifest
leaves it out, and the registry refuses a call to it by name. The ElevenLabs
entry ships with 104 of its 111 tools off, leaving speech, transcription, the
voice list, image, video, image edit and `get_flow_run_status`.

Skills work the same way from the wingman's side: `disabled_skill_tools` on the
wingman config, applied through `Skill.get_enabled_tools`, which is what the
registry and the prompt builder read. `get_tools` stays the full list for the
UI.

Both are blacklists on purpose: a tool the server or skill adds later is on
until someone switches it off.

## Scopes

The MCP spec tells a client to request every scope the protected resource
advertises, and the SDK implements that by overwriting whatever the application
asked for. Against ElevenLabs that turns a request for text-to-speech into a
request for all seven scopes, including writing conversational agents and
generating video.

`oauth_scopes` in `mcp.yaml` therefore wins over the SDK's choice. Leaving it
empty keeps the spec behaviour, which is what a server that advertises nothing
useful needs.

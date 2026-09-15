"""OAuth for MCP servers that refuse API keys.

A growing number of hosted MCP servers only accept an OAuth access token.
ElevenLabs' is the one that forced this module: an unauthenticated request to
`https://api.elevenlabs.io/v1/mcp` answers 401 with
`{"detail":"OAuth bearer token required for the hosted MCP."}`.

The MCP Python SDK already implements the protocol — discovery, dynamic client
registration, the authorization code grant with PKCE, and token refresh — behind
`OAuthClientProvider`, which is an `httpx.Auth` and can be handed straight to the
streamable-HTTP and SSE transports. What it does not bring is the two things that
are specific to an application: where tokens are kept, and how a user is walked
through a browser consent page.

Both of those live here.

## Two providers, because connecting must never block

Wingman connects a wingman's MCP servers while that wingman boots. If a browser
flow could start there, one unauthorized server would hang the boot until someone
happened to notice a browser tab.

So `build_silent_provider` returns a provider whose callback handler raises at
once. It still sends a stored token and still refreshes an expired one, because
refreshing is a plain HTTP round trip with no user in it. Only a server that was
never authorized fails, and it fails immediately with a message that says so.

`start_authorization` builds the other kind. Its callback handler waits on a
future that the `/mcp/oauth/callback` route resolves, and it is only ever reached
because a user pressed a button.

## Why the tokens need an absolute expiry

`OAuthToken` carries `expires_in`, a duration, which is all the token endpoint
returns. The SDK turns that into an absolute time when it receives a token, but
`_initialize` — the path that loads a token from storage — does not. Left alone,
every Core restart would treat a token minted two days ago as fresh, send it,
take a 401, and fall through to the full browser flow while a perfectly good
refresh token sat in the file.

So storage keeps `expires_at` next to the token and hands the SDK an `expires_in`
recomputed against the clock, and `_WingmanOAuthProvider` overrides `_initialize`
to write that through to the context. From then on the SDK's own refresh path
does the right thing on its own.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, PrivateAttr

try:
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthMetadata,
        OAuthToken,
    )

    OAUTH_AVAILABLE = True
except ImportError:
    # `mcp_client` degrades gracefully when the MCP SDK is not installed, and it
    # imports this module for `NeedsAuthorization`. Without these stand-ins that
    # graceful path would turn into an ImportError at startup — the one place it
    # was written to avoid.
    OAUTH_AVAILABLE = False

    class TokenStorage:  # type: ignore[no-redef]
        pass

    class OAuthClientProvider:  # type: ignore[no-redef]
        def __init__(self, **_kwargs):
            raise RuntimeError("MCP SDK not installed.")

    class OAuthToken(BaseModel):  # type: ignore[no-redef]
        pass

    class OAuthClientMetadata(BaseModel):  # type: ignore[no-redef]
        pass

    class OAuthClientInformationFull(BaseModel):  # type: ignore[no-redef]
        pass

    class OAuthMetadata(BaseModel):  # type: ignore[no-redef]
        pass


from api.enums import LogType, McpAuthType
from api.interface import McpOAuthStartResult, McpOAuthStatus, McpServerConfig
from services.printr import Printr

printr = Printr()

# The path the provider redirects back to. It is part of the redirect URI that
# gets registered with an authorization server, so changing it invalidates every
# token a user already holds.
CALLBACK_PATH = "/mcp/oauth/callback"

# Prefix for the secrets.yaml key that holds a server's token bundle.
SECRET_PREFIX = "mcp_oauth_"

# How long to wait for the SDK to hand us an authorization URL. This covers
# metadata discovery and, when the server supports it, dynamic client
# registration — a few HTTP round trips, no user involved.
_URL_TIMEOUT = 30.0

# How long a user has to finish the consent page before the flow is abandoned.
_CONSENT_TIMEOUT = 300.0

# How long the callback route waits for the token exchange before answering the
# browser. It is the code-for-token round trip plus one MCP handshake, so seconds
# rather than minutes, and the page says "finishing up" if it runs over.
_EXCHANGE_TIMEOUT = 30.0

# Treat a token as expired slightly early, so one that dies mid-request gets
# refreshed beforehand instead of costing a failed call.
_EXPIRY_SKEW = 30.0


class NeedsAuthorization(Exception):
    """Raised by the silent provider when only a browser flow could continue.

    `McpClient` turns this into the message a user sees, so it carries the
    server's display name rather than its config name.
    """

    def __init__(self, display_name: str):
        self.display_name = display_name
        super().__init__(
            f"'{display_name}' needs authorization. "
            "Open the wingman's MCP settings and press Authorize."
        )


class WingmanTokenStorage(TokenStorage):
    """Keeps one server's OAuth state in secrets.yaml.

    Everything for a server lives in a single JSON blob under
    `mcp_oauth_<server name>`, holding the token set, the absolute expiry, and
    the client information — dynamically registered or configured. One key, one
    write, and a user who wants to revoke Wingman's access entirely can delete
    one line.
    """

    def __init__(
        self,
        server_name: str,
        secret_keeper: Any,
        fallback_client_info: Optional[OAuthClientInformationFull] = None,
    ):
        self.server_name = server_name
        self.secret_key = f"{SECRET_PREFIX}{server_name}"
        self._secret_keeper = secret_keeper
        # Used when nothing is stored yet, which is how a configured client id
        # reaches the SDK: it finds client info already present and skips
        # registration.
        self._fallback_client_info = fallback_client_info

    # ── the blob ──────────────────────────────────────────────────────

    def read(self) -> dict:
        """The stored bundle, or an empty dict when there is none."""
        raw = self._secret_keeper.secrets.get(self.secret_key)
        if not raw:
            return {}
        if isinstance(raw, dict):
            # Someone hand-edited secrets.yaml into real YAML. Accept it.
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            printr.print(
                f"MCP OAuth state for '{self.server_name}' is not readable and was ignored.",
                color=LogType.WARNING,
                server_only=True,
            )
            return {}

    async def _write(self, bundle: dict) -> None:
        self._secret_keeper.secrets[self.secret_key] = json.dumps(bundle)
        await self._secret_keeper.save()

    async def clear(self) -> None:
        """Forget everything about this server, tokens and registration alike."""
        if self.secret_key in self._secret_keeper.secrets:
            del self._secret_keeper.secrets[self.secret_key]
            await self._secret_keeper.save()

    # ── TokenStorage ──────────────────────────────────────────────────

    async def get_tokens(self) -> OAuthToken | None:
        bundle = self.read()
        raw = bundle.get("tokens")
        if not raw:
            return None
        try:
            token = OAuthToken.model_validate(raw)
        except Exception:
            return None

        # Hand back what is actually left, not what was left when it was issued.
        expires_at = bundle.get("expires_at")
        if expires_at:
            token.expires_in = max(0, int(expires_at - time.time()))
        return token

    async def set_tokens(self, tokens: OAuthToken) -> None:
        bundle = self.read()
        bundle["tokens"] = tokens.model_dump(exclude_none=True)
        bundle["expires_at"] = (
            time.time() + tokens.expires_in if tokens.expires_in else None
        )
        await self._write(bundle)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        bundle = self.read()
        raw = bundle.get("client_info")
        if raw:
            try:
                return OAuthClientInformationFull.model_validate(raw)
            except Exception:
                pass
        return self._fallback_client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        bundle = self.read()
        bundle["client_info"] = client_info.model_dump(exclude_none=True, mode="json")
        await self._write(bundle)


class _ConfiguredScopeMetadata(OAuthClientMetadata):
    """Client metadata whose configured scope survives the SDK's scope strategy.

    The MCP spec tells a client to ask for every scope the protected resource
    advertises, and the SDK implements that by overwriting `scope` partway
    through the flow with whatever discovery turned up. Against ElevenLabs that
    turns a request for text-to-speech into a request for all seven scopes,
    including writing conversational agents and generating video.

    A scope list in `mcp.yaml` is a deliberate statement about how much of an
    account Wingman should be able to touch, so it wins. Leaving `oauth_scopes`
    empty — the default — keeps the SDK's behaviour untouched, which is what a
    server that advertises nothing useful needs.
    """

    _configured_scope: Optional[str] = PrivateAttr(default=None)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "scope":
            # Read through the private-attribute dict rather than the attribute:
            # this runs during construction too, before private attributes exist.
            configured = (self.__pydantic_private__ or {}).get("_configured_scope")
            if configured:
                value = configured
        super().__setattr__(name, value)


class _WingmanOAuthProvider(OAuthClientProvider):
    """`OAuthClientProvider` that can refresh a token it loaded from disk.

    Two things the base class only ever learns during a browser flow, and
    therefore does not know when it starts from stored state:

    * **The expiry.** It loads a token without deriving one, so a token restored
      from disk looks valid forever. See the module docstring.
    * **The token endpoint.** `_get_token_endpoint` reads it from
      `context.oauth_metadata`, which is only filled by the discovery step inside
      the 401 branch. On a provider that starts with a valid-looking token there
      is no 401 and no discovery, so a refresh falls back to `<origin>/token`.
      Against ElevenLabs that is a 404 — the real one is `/v1/oauth/token` — and
      the SDK then drops through to the full browser flow. Every user would have
      been asked to authorize again every hour, with a working refresh token
      sitting in the file.

    So the metadata is discovered once and kept next to the token.
    """

    async def _initialize(self) -> None:
        await super()._initialize()
        tokens = self.context.current_tokens
        if tokens and tokens.expires_in is not None:
            self.context.update_token_expiry(tokens)

        # Only needed to refresh. A provider with nothing stored discovers this
        # on its own during the flow it is about to run.
        if tokens and tokens.refresh_token and not self.context.oauth_metadata:
            metadata = await self._authorization_server_metadata()
            if metadata:
                self.context.oauth_metadata = metadata

    async def _authorization_server_metadata(self) -> Optional[Any]:
        """The authorization server's metadata, from storage or from the network.

        Cached in the token bundle after the first lookup, so the common case —
        Core starting up with servers to reconnect — costs no extra requests.
        """
        storage = self.context.storage
        if not isinstance(storage, WingmanTokenStorage):
            return None

        bundle = storage.read()
        stored = bundle.get("oauth_metadata")
        if stored:
            try:
                return OAuthMetadata.model_validate(stored)
            except Exception:
                pass  # Written by an older version, or by hand. Rediscover it.

        metadata = await _discover_authorization_server(self.context.server_url)
        if metadata:
            bundle = storage.read()
            bundle["oauth_metadata"] = metadata.model_dump(
                exclude_none=True, mode="json"
            )
            await storage._write(bundle)
        return metadata


async def _discover_authorization_server(server_url: str) -> Optional[Any]:
    """Walk the two-step discovery an MCP client does on its first 401.

    The resource points at its authorization server, and that server publishes
    where its token endpoint is. The SDK's own URL builders are used so this
    follows the same fallbacks the spec asks for, including the legacy paths.
    """
    try:
        from mcp.client.auth.utils import (
            build_oauth_authorization_server_metadata_discovery_urls,
            build_protected_resource_metadata_discovery_urls,
            create_oauth_metadata_request,
            handle_auth_metadata_response,
            handle_protected_resource_response,
        )
    except ImportError:
        return None

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            auth_server_url: Optional[str] = None
            for url in build_protected_resource_metadata_discovery_urls(
                None, server_url
            ):
                request = create_oauth_metadata_request(url)
                prm = await handle_protected_resource_response(
                    await client.send(request)
                )
                if prm and prm.authorization_servers:
                    auth_server_url = str(prm.authorization_servers[0])
                    break

            for url in build_oauth_authorization_server_metadata_discovery_urls(
                auth_server_url, server_url
            ):
                request = create_oauth_metadata_request(url)
                ok, metadata = await handle_auth_metadata_response(
                    await client.send(request)
                )
                if not ok:
                    break
                if metadata:
                    return metadata
    except Exception as e:
        printr.print(
            f"Could not look up the authorization server for {server_url}: {e}",
            color=LogType.WARNING,
            server_only=True,
        )
    return None


class _PendingFlow:
    """One in-progress browser flow.

    `authorization_url` resolves as soon as the SDK has a consent page to show.
    `callback` resolves when the browser comes back. `outcome` resolves when the
    token has been exchanged, with None on success and the error message
    otherwise.
    """

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.state: Optional[str] = None
        loop = asyncio.get_event_loop()
        self.authorization_url: asyncio.Future[str] = loop.create_future()
        self.callback: asyncio.Future[tuple[str, Optional[str]]] = loop.create_future()
        # Resolves with the error message, or None when the token was stored.
        # The callback route waits on this so the page it renders says what
        # actually happened rather than what was about to be attempted.
        self.outcome: asyncio.Future[Optional[str]] = loop.create_future()
        self.task: Optional[asyncio.Task] = None

    def fail(self, error: BaseException) -> None:
        for future in (self.authorization_url, self.callback):
            if not future.done():
                future.set_exception(error)
            self._swallow(future)
        if not self.outcome.done():
            self.outcome.set_result(str(error) or error.__class__.__name__)

    @staticmethod
    def _swallow(future: asyncio.Future) -> None:
        """Mark a failed future's exception as seen.

        Nobody may be awaiting these by the time a flow is torn down, and asyncio
        prints a traceback for an unretrieved exception when the future is
        collected. That looks like a crash and is not one. Reading the exception
        is what marks it retrieved; the value is deliberately discarded.
        """
        if future.done() and not future.cancelled():
            future.exception()


class McpOAuthService:
    """Runs and stores MCP OAuth for the whole of Core.

    One instance per process, reached through `get_oauth_service()`, because the
    redirect URI is a property of the process — there is exactly one HTTP port
    listening for callbacks — and because a flow started from the settings UI has
    to be finishable by a request arriving on an unrelated route.
    """

    def __init__(self, secret_keeper: Any):
        self._secret_keeper = secret_keeper
        self._host = "localhost"
        self._port = 49111
        self._flows: dict[str, _PendingFlow] = {}
        self._by_state: dict[str, _PendingFlow] = {}
        self._on_state_changed: Optional[Callable[[str, bool, Optional[str]], Any]] = (
            None
        )

    # ── wiring ────────────────────────────────────────────────────────

    def set_callback_origin(self, host: str, port: int) -> None:
        """Tell the service which port the callback route is listening on.

        `main.py` calls this once uvicorn has bound. A host of `0.0.0.0` means
        "every interface", which is not something a browser can be sent to, so it
        becomes localhost.
        """
        self._host = "localhost" if host in ("0.0.0.0", "::", "") else host
        self._port = port

    def set_state_changed_handler(
        self, handler: Callable[[str, bool, Optional[str]], Any]
    ) -> None:
        """Register the callback that broadcasts a finished flow to the client."""
        self._on_state_changed = handler

    @property
    def redirect_uri(self) -> str:
        return f"http://{self._host}:{self._port}{CALLBACK_PATH}"

    # ── building providers ────────────────────────────────────────────

    def _client_metadata(self, config: McpServerConfig) -> OAuthClientMetadata:
        scope = " ".join(config.oauth_scopes) if config.oauth_scopes else None
        metadata = _ConfiguredScopeMetadata(
            client_name="Wingman AI",
            client_uri="https://www.wingman-ai.com",
            redirect_uris=[self.redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            # A desktop app cannot hold a secret, so it authenticates with PKCE
            # alone. Every authorization server we target advertises "none".
            token_endpoint_auth_method="none",
            scope=scope,
        )
        metadata._configured_scope = scope
        return metadata

    def _storage(self, config: McpServerConfig) -> WingmanTokenStorage:
        fallback = None
        if config.oauth_client_id and OAUTH_AVAILABLE:
            # A configured client id is the escape hatch for servers with no
            # registration endpoint. Seeding storage with it makes the SDK's
            # `_register_client` return early, so it never posts to a /register
            # that would answer 404.
            #
            # The SDK also has a native `client_metadata_url` argument for this,
            # but it only accepts an HTTPS URL and only uses it when the server
            # advertises `client_id_metadata_document_supported`. Seeding covers
            # that case and a plain client id a provider handed out, which is
            # what the settings field promises to accept.
            metadata = self._client_metadata(config)
            fallback = OAuthClientInformationFull(
                client_id=config.oauth_client_id,
                **metadata.model_dump(exclude_none=True),
            )
        return WingmanTokenStorage(config.name, self._secret_keeper, fallback)

    def build_silent_provider(
        self, config: McpServerConfig
    ) -> Optional[httpx.Auth]:
        """The provider used when connecting. Never opens a browser.

        Returns None for servers that are not on OAuth, so the caller can pass
        the result straight through to the transport.
        """
        if config.auth != McpAuthType.OAUTH or not OAUTH_AVAILABLE:
            return None

        async def refuse_redirect(_url: str) -> None:
            raise NeedsAuthorization(config.display_name)

        async def refuse_callback() -> tuple[str, Optional[str]]:
            raise NeedsAuthorization(config.display_name)

        return _WingmanOAuthProvider(
            server_url=config.url or "",
            client_metadata=self._client_metadata(config),
            storage=self._storage(config),
            redirect_handler=refuse_redirect,
            callback_handler=refuse_callback,
        )

    # ── the browser flow ──────────────────────────────────────────────

    async def start_authorization(
        self, config: McpServerConfig
    ) -> McpOAuthStartResult:
        """Begin a flow and return the consent page to open.

        The flow keeps running after this returns: it is parked on the callback
        future until the browser comes back to `/mcp/oauth/callback`.
        """
        if not OAUTH_AVAILABLE:
            return McpOAuthStartResult(
                success=False,
                server_name=config.name,
                error="MCP SDK not installed. Run 'pip install mcp' to enable MCP support.",
            )
        if config.auth != McpAuthType.OAUTH:
            return McpOAuthStartResult(
                success=False,
                server_name=config.name,
                error=f"'{config.display_name}' is not configured for OAuth.",
            )
        if not config.url:
            return McpOAuthStartResult(
                success=False,
                server_name=config.name,
                error=f"'{config.display_name}' has no URL. OAuth needs an HTTP or SSE server.",
            )

        self._cancel_flow(config.name)
        flow = _PendingFlow(config.name)
        self._flows[config.name] = flow

        async def on_redirect(url: str) -> None:
            # The SDK generates the state parameter itself and only reveals it
            # inside this URL, so this is where the callback route learns which
            # flow an incoming request belongs to.
            state = _state_from(url)
            if state:
                flow.state = state
                self._by_state[state] = flow
            if not flow.authorization_url.done():
                flow.authorization_url.set_result(url)

        async def on_callback() -> tuple[str, Optional[str]]:
            return await asyncio.wait_for(flow.callback, timeout=_CONSENT_TIMEOUT)

        provider = _WingmanOAuthProvider(
            server_url=config.url,
            client_metadata=self._client_metadata(config),
            storage=self._storage(config),
            redirect_handler=on_redirect,
            callback_handler=on_callback,
        )

        flow.task = asyncio.create_task(self._run_flow(config, provider, flow))

        try:
            url = await asyncio.wait_for(flow.authorization_url, timeout=_URL_TIMEOUT)
        except asyncio.TimeoutError:
            self._cancel_flow(config.name)
            return McpOAuthStartResult(
                success=False,
                server_name=config.name,
                error="The server did not answer in time. Check the URL and your connection.",
            )
        except Exception as e:
            self._cancel_flow(config.name)
            return McpOAuthStartResult(
                success=False, server_name=config.name, error=_readable(e)
            )

        return McpOAuthStartResult(
            success=True, server_name=config.name, authorization_url=url
        )

    async def _run_flow(
        self, config: McpServerConfig, provider: httpx.Auth, flow: _PendingFlow
    ) -> None:
        """Drive the flow by doing the one thing that provokes it: connect.

        The SDK's OAuth provider is an httpx auth hook, so it only acts on a 401.
        Running a real MCP handshake is both how the flow starts and how we learn
        that the token we just obtained actually works.
        """
        error: Optional[str] = None
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                url=config.url,
                headers=config.headers or None,
                auth=provider,
                timeout=60,
                sse_read_timeout=60,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
            printr.print(
                f"MCP authorized: {config.display_name}",
                color=LogType.MCP,
                server_only=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error = _readable(e)
            # A flow can fail before it ever produces a consent page — bad URL,
            # metadata that does not validate, a registration endpoint that is
            # not there. `start_authorization` is still waiting on that URL, and
            # without this it would wait out the full timeout and then report a
            # timeout instead of the reason.
            if not flow.authorization_url.done():
                flow.authorization_url.set_exception(RuntimeError(error))
            printr.print(
                f"MCP authorization failed ({config.display_name}): {error}",
                color=LogType.ERROR,
                server_only=True,
            )
        finally:
            if not flow.outcome.done():
                flow.outcome.set_result(error)
            self._forget(flow)

        if self._on_state_changed:
            result = self._on_state_changed(config.name, error is None, error)
            if asyncio.iscoroutine(result):
                await result

    async def handle_callback(
        self, code: Optional[str], state: Optional[str], error: Optional[str]
    ) -> tuple[bool, str]:
        """Feed a redirect from the authorization server back into its flow.

        Returns whether it was accepted and a message for the browser page.
        """
        if error:
            for flow in self._matching(state):
                flow.fail(RuntimeError(error))
            return False, error

        if not code:
            return False, "The authorization server sent no code."

        flows = self._matching(state)
        if not flows:
            return False, "No authorization is waiting. It may have timed out — try again in Wingman."

        for flow in flows:
            if not flow.callback.done():
                flow.callback.set_result((code, state))

        # Wait for the token exchange before answering. Handing the code over is
        # not the same as it working: a stale or replayed code fails here, and a
        # page that said "connected" before finding that out would be lying to
        # the one person who could act on it.
        flow = flows[0]
        try:
            outcome = await asyncio.wait_for(flow.outcome, timeout=_EXCHANGE_TIMEOUT)
        except asyncio.TimeoutError:
            return True, "Wingman is finishing up. Check the wingman's MCP settings."
        except asyncio.CancelledError:
            return False, "The authorization was cancelled."

        if outcome:
            return False, outcome
        return True, "Wingman is connected."

    def _matching(self, state: Optional[str]) -> list[_PendingFlow]:
        if state:
            # A state that names no flow is not ours. Handing it to the one flow
            # that happens to be running would make the SDK abort that flow on
            # its state check, so a stray request could kill a real
            # authorization mid-consent.
            flow = self._by_state.get(state)
            return [flow] if flow else []
        # No state at all. If exactly one flow is running it is unambiguous
        # which one this is; the SDK still checks the state on its own side.
        if len(self._flows) == 1:
            return list(self._flows.values())
        return []

    def _forget(self, flow: _PendingFlow) -> None:
        self._flows.pop(flow.server_name, None)
        if flow.state:
            self._by_state.pop(flow.state, None)
        flow._swallow(flow.callback)

    def _cancel_flow(self, server_name: str) -> None:
        flow = self._flows.get(server_name)
        if not flow:
            return
        if flow.task and not flow.task.done():
            flow.task.cancel()
        flow.fail(asyncio.CancelledError())
        self._forget(flow)

    # ── state a user can see ──────────────────────────────────────────

    def status(self, config: McpServerConfig) -> McpOAuthStatus:
        """What Wingman holds for this server, without touching the network."""
        if config.auth != McpAuthType.OAUTH:
            return McpOAuthStatus(server_name=config.name, is_authorized=False)

        bundle = self._storage(config).read()
        tokens = bundle.get("tokens") or {}
        access_token = tokens.get("access_token")
        if not access_token:
            return McpOAuthStatus(server_name=config.name, is_authorized=False)

        expires_at = bundle.get("expires_at")
        scope = tokens.get("scope")
        return McpOAuthStatus(
            server_name=config.name,
            is_authorized=True,
            is_expired=bool(expires_at and time.time() > expires_at - _EXPIRY_SKEW),
            can_refresh=bool(tokens.get("refresh_token")),
            scopes=scope.split(" ") if scope else None,
            expires_at=expires_at,
        )

    async def revoke(self, config: McpServerConfig) -> None:
        """Drop the stored token and registration.

        Local only. Telling the provider to invalidate the token as well would
        need its revocation endpoint and a second round trip that can fail on its
        own; a user who wants that does it in the provider's own account page,
        which is where they can see every client anyway.
        """
        self._cancel_flow(config.name)
        await self._storage(config).clear()
        printr.print(
            f"MCP authorization removed: {config.display_name}",
            color=LogType.MCP,
            server_only=True,
        )


_service: Optional[McpOAuthService] = None


def get_oauth_service() -> McpOAuthService:
    """The one service for this process.

    There is a single HTTP port receiving callbacks and a single secrets file, so
    a second instance could only disagree with the first. `SecretKeeper` is
    imported lazily because it reaches into the config layer, and this module is
    imported by `mcp_client`.
    """
    global _service
    if _service is None:
        from services.secret_keeper import SecretKeeper

        _service = McpOAuthService(SecretKeeper())
    return _service


def _state_from(url: str) -> Optional[str]:
    values = parse_qs(urlparse(url).query).get("state")
    return values[0] if values else None


def _readable(error: BaseException) -> str:
    """Turn what the SDK raises into a sentence worth showing a user."""
    if isinstance(error, NeedsAuthorization):
        return str(error)

    # anyio groups everything a task group raised. The first cause is the one
    # that actually says something.
    inner: BaseException = error
    while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
        inner = inner.exceptions[0]

    text = str(inner) or inner.__class__.__name__
    if "404" in text and "register" in text.lower():
        return (
            "This server does not support automatic client registration. "
            "Enter an OAuth client ID in the server's settings."
        )
    return text

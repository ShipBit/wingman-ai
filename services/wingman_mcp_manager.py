"""WingmanMcpManager — owns all MCP discovery, connection, and lifecycle.

Centralises MCP concerns (registry creation, secret injection, timeout
handling, enable/disable, parallel init) in one focused service.
"""

import asyncio
import traceback
from typing import Callable

from api.commands import McpStateChangedCommand
from api.enums import (
    LogSource,
    LogType,
    McpTransportType,
    WingmanInitializationErrorType,
)
from api.interface import SettingsConfig, WingmanConfig, WingmanInitializationError
from services.mcp_client import McpClient
from services.mcp_registry import McpRegistry
from services.printr import Printr
from services.secret_keeper import SecretKeeper

printr = Printr()

_AUTH_HEADER_KEYS = {"authorization", "api-key", "x-api-key"}
_STDIO_DEFAULT_TIMEOUT = 60.0
_HTTP_DEFAULT_TIMEOUT = 30.0


class WingmanMcpManager:
    """Manages MCP server discovery, connection, enable/disable, and teardown."""

    def __init__(
        self,
        wingman_name: str,
        mcp_client: McpClient,
        secret_keeper: SecretKeeper,
        get_mcp_config: Callable,  # callable returning the central mcp_config (from tower)
        settings: SettingsConfig,
        config: WingmanConfig,
    ):
        self.wingman_name = wingman_name
        self.mcp_client = mcp_client
        self.secret_keeper = secret_keeper
        self._get_mcp_config = get_mcp_config
        self.settings = settings
        self.config = config

        # Manager owns its registry and the broadcast callback
        self.mcp_registry = McpRegistry(
            mcp_client,
            wingman_name=wingman_name,
            on_state_changed=self._broadcast_mcp_state_changed,
        )

    # ─────────────────────────── Private ────────────────────────────────────── #

    async def _prepare_connection_params(
        self, mcp_config, log_secret_found: bool = False
    ) -> tuple[dict, float]:
        """Build request headers (with secret-injected auth) and resolve the timeout."""
        headers: dict = {}
        if mcp_config.headers:
            headers.update(mcp_config.headers)

        secret_key = f"mcp_{mcp_config.name}"
        api_key = await self.secret_keeper.retrieve(
            requester=self.wingman_name,
            key=secret_key,
            prompt_if_missing=False,
        )
        if api_key:
            if log_secret_found:
                printr.print(
                    f"MCP secret '{secret_key}' found ({len(api_key)} chars)",
                    color=LogType.INFO,
                    source_name=self.wingman_name,
                    server_only=True,
                )
            if not any(k.lower() in _AUTH_HEADER_KEYS for k in headers.keys()):
                headers["Authorization"] = f"Bearer {api_key}"

        default_timeout = (
            _STDIO_DEFAULT_TIMEOUT
            if mcp_config.type == McpTransportType.STDIO
            else _HTTP_DEFAULT_TIMEOUT
        )
        timeout = (
            float(mcp_config.timeout) if mcp_config.timeout else default_timeout
        )
        return headers, timeout

    def _broadcast_mcp_state_changed(self):
        if printr._connection_manager:
            printr.ensure_async(
                printr._connection_manager.broadcast(
                    McpStateChangedCommand(wingman_name=self.wingman_name)
                )
            )

    # ─────────────────────────── Public API ─────────────────────────────────── #

    async def enable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        if not self.mcp_client.is_available:
            return False, "MCP SDK not installed."

        if mcp_name in self.mcp_registry.get_connected_server_names():
            return True, f"MCP server '{mcp_name}' is already connected."

        central_mcp_config = self._get_mcp_config()
        mcp_configs = central_mcp_config.servers if central_mcp_config else []

        mcp_config = None
        for cfg in mcp_configs:
            if cfg.name == mcp_name:
                mcp_config = cfg
                break

        if not mcp_config:
            return False, f"MCP server '{mcp_name}' not found in mcp.yaml."

        try:
            headers, timeout = await self._prepare_connection_params(mcp_config)

            connection = await asyncio.wait_for(
                self.mcp_registry.register_server(
                    config=mcp_config,
                    headers=headers if headers else None,
                ),
                timeout=timeout,
            )

            if connection.is_connected:
                tool_count = len(connection.tools)
                return True, f"MCP server '{mcp_name}' enabled with {tool_count} tools."
            else:
                error = connection.error or "Connection failed."
                return False, f"MCP server '{mcp_name}' failed to connect: {error}"

        except asyncio.TimeoutError:
            error_msg = f"Connection timed out ({int(timeout)}s)."
            self.mcp_registry.set_server_error(mcp_name, error_msg)
            return False, f"MCP server '{mcp_name}': {error_msg}"

        except Exception as e:
            error_msg = f"Error enabling MCP '{mcp_name}': {str(e)}"
            await printr.print_async(error_msg, color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False, error_msg

    async def disable_mcp(self, mcp_name: str) -> tuple[bool, str]:
        if mcp_name not in self.mcp_registry.get_connected_server_names():
            return True, f"MCP server '{mcp_name}' is already disconnected."

        try:
            await self.mcp_registry.unregister_server(mcp_name)
            return True, f"MCP server '{mcp_name}' disabled."

        except Exception as e:
            error_msg = f"Error disabling MCP '{mcp_name}': {str(e)}"
            await printr.print_async(error_msg, color=LogType.ERROR)
            printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
            return False, error_msg

    async def init_mcps(self) -> list[WingmanInitializationError]:
        errors = []

        if not self.mcp_client.is_available:
            printr.print(
                f"[{self.wingman_name}] MCP SDK not installed, skipping MCP initialization.",
                color=LogType.WARNING,
                server_only=True,
            )
            return errors

        await self.unload_mcps()

        central_mcp_config = self._get_mcp_config()
        mcp_configs = central_mcp_config.servers if central_mcp_config else []
        if not mcp_configs:
            return errors

        discoverable_mcps = self.config.discoverable_mcps
        mcps_to_connect = [mcp for mcp in mcp_configs if mcp.name in discoverable_mcps]

        if not mcps_to_connect:
            return errors

        async def connect_mcp(mcp_config):
            local_errors = []
            try:
                headers, timeout = await self._prepare_connection_params(
                    mcp_config, log_secret_found=True
                )

                try:
                    connection = await asyncio.wait_for(
                        self.mcp_registry.register_server(
                            config=mcp_config,
                            headers=headers if headers else None,
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    error_msg = f"MCP '{mcp_config.display_name}' connection timed out ({int(timeout)}s)."
                    printr.print(
                        error_msg,
                        color=LogType.WARNING,
                        source_name=self.wingman_name,
                        server_only=True,
                    )
                    local_errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman_name,
                            message=error_msg,
                            error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                        )
                    )
                    return (False, None, local_errors)

                if connection.is_connected:
                    return (
                        True,
                        f"{mcp_config.display_name} ({len(connection.tools)} tools)",
                        local_errors,
                    )
                else:
                    error_msg = f"MCP '{mcp_config.display_name}' failed to connect: {connection.error}"
                    local_errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman_name,
                            message=error_msg,
                            error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                        )
                    )
                    return (False, None, local_errors)

            except Exception as e:
                error_msg = f"MCP '{mcp_config.name}' initialization error: {str(e)}"
                printr.print(
                    error_msg,
                    color=LogType.ERROR,
                    source_name=self.wingman_name,
                    server_only=True,
                )
                printr.print(
                    traceback.format_exc(), color=LogType.ERROR, server_only=True
                )
                local_errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman_name,
                        message=error_msg,
                        error_type=WingmanInitializationErrorType.MCP_CONNECTION_FAILED,
                    )
                )
                return (False, None, local_errors)

        connection_tasks = [connect_mcp(mcp) for mcp in mcps_to_connect]
        results = await asyncio.gather(*connection_tasks)

        connected_count = 0
        connected_names = []
        for success, connection_info, mcp_errors in results:
            if success:
                connected_count += 1
                connected_names.append(connection_info)
            errors.extend(mcp_errors)

        if connected_count > 0:
            await printr.print_async(
                f"Discoverable MCP servers connected ({connected_count}): {', '.join(connected_names)}",
                color=LogType.WINGMAN,
                source=LogSource.WINGMAN,
                source_name=self.wingman_name,
                server_only=not self.settings.debug_mode,
            )

        return errors

    async def unload_mcps(self):
        await self.mcp_registry.clear()

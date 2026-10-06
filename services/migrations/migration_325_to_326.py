"""Migration from version 3.2.5 to 3.2.6.

The hosted Elite Dangerous MCP server joins `mcp.yaml`: star systems and their
stations, services nearby, trade between two stations and engineering recipes,
from EDSM, Spansh and EDCD. `mcp.yaml` belongs to the user once it exists, so a
new template entry never reaches anyone who already has one. The server is
appended here, unless one of that name is there already: someone may have added
it by hand, and their settings win. It is not discoverable by default, so no
Wingman uses it until the user switches it on.

Nothing else changes.
"""

from services.migrations.base_migration import BaseMigration

# Kept in step with templates/configs/mcp.template.yaml, like the ElevenLabs
# entry in migration_320_to_321: a migration must produce the same config every
# time, whichever template happens to be installed.
ELITE_SERVER = {
    "name": "wingman_elite_dangerous",
    "display_name": "Elite Dangerous - Systems, Stations, Trade",
    "description": (
        "Elite Dangerous community data. Star systems and their stations, "
        "services nearby like refuel, repair or a material trader, commodity "
        "prices and modules at a station, the best cargo between two stations, "
        "and the materials and engineers for ship engineering. Not for the "
        "pilot's own ship, cargo or missions."
    ),
    "discovery_keywords": [
        "Elite Dangerous",
        "ED",
        "station",
        "nearest",
        "refuel",
        "repair",
        "material trader",
        "commodity prices",
        "trade",
        "engineering",
    ],
    "type": "http",
    "url": "https://wingman-ai-mcp-servers.wingman-ai.workers.dev/elite/mcp",
    "discoverable_by_default": False,
}


class Migration325To326(BaseMigration):
    """Migration from 3.2.5 to 3.2.6."""

    old_version = "3_2_5"
    new_version = "3_2_6"

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Keep the user's MCP servers and add the Elite Dangerous one."""
        if not old:
            # No mcp.yaml before this point, so the template is already right.
            return new
        servers = old.get("servers")
        if not isinstance(servers, list):
            self.log_warning("mcp.yaml has no server list, leaving it alone.")
            return old
        if any(
            isinstance(server, dict) and server.get("name") == ELITE_SERVER["name"]
            for server in servers
        ):
            return old
        servers.append(dict(ELITE_SERVER))
        self.log("- added the Elite Dangerous MCP server")
        return old

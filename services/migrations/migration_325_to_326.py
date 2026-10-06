"""Migration from version 3.2.5 to 3.2.6.

Two hosted MCP servers join `mcp.yaml`. The Elite Dangerous one: star systems
and their stations, services nearby, trade between two stations and engineering
recipes, from EDSM, Spansh and EDCD. The Galactapedia one: Star Citizen lore
from RSI's Galactapedia. `mcp.yaml` belongs to the user once it exists, so a new
template entry never reaches anyone who already has one. Each server is
appended here, unless one of that name is there already: someone may have added
it by hand, and their settings win. Neither is discoverable by default, so no
Wingman uses them until the user switches them on.

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

GALACTAPEDIA_SERVER = {
    "name": "wingman_galactapedia",
    "display_name": "Galactapedia - Star Citizen Lore",
    "description": (
        "Star Citizen lore from RSI's Galactapedia. People, factions, species, "
        "star systems, planets, ships and events of the Star Citizen universe "
        "and their history. Answers who is and what is questions about the "
        "lore. Not for ship stats, prices or game mechanics, which StarHead "
        "covers. Unofficial fan project, not affiliated with Cloud Imperium."
    ),
    "discovery_keywords": [
        "Star Citizen lore",
        "Galactapedia",
        "Star Citizen history",
        "UEE",
        "Vanduul",
        "Xi'an",
        "Banu",
        "Tevarin",
    ],
    "type": "http",
    "url": "https://wingman-ai-mcp-servers.wingman-ai.workers.dev/galactapedia/mcp",
    "discoverable_by_default": False,
}

NEW_SERVERS = [
    (ELITE_SERVER, "Elite Dangerous"),
    (GALACTAPEDIA_SERVER, "Galactapedia"),
]


class Migration325To326(BaseMigration):
    """Migration from 3.2.5 to 3.2.6."""

    old_version = "3_2_5"
    new_version = "3_2_6"

    def migrate_mcp(self, old: dict, new: dict) -> dict:
        """Keep the user's MCP servers and add the Elite Dangerous and Galactapedia ones."""
        if not old:
            # No mcp.yaml before this point, so the template is already right.
            return new
        servers = old.get("servers")
        if not isinstance(servers, list):
            self.log_warning("mcp.yaml has no server list, leaving it alone.")
            return old
        present = {server.get("name") for server in servers if isinstance(server, dict)}
        for server, label in NEW_SERVERS:
            if server["name"] in present:
                continue
            servers.append(dict(server))
            self.log(f"- added the {label} MCP server")
        return old

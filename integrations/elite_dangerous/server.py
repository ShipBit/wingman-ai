"""Local stdio MCP entry point. SDK stdout is reserved for MCP protocol messages."""

import argparse
import json
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from provider import PublicData
from stations import StationData
from navigation import NearbyServices
from engineering import EngineeringData


def create_server(cache_dir):
    server = FastMCP("Elite Public Data", log_level="ERROR")
    provider = PublicData(cache_dir)
    stations = StationData(provider)
    navigation = NearbyServices(provider)
    engineering = EngineeringData(provider)

    @server.tool()
    def elite_engineering_lookup(
        query: str,
        grade: int = 5,
        applications: int = 1,
        galaxy: Literal["live", "legacy", "unknown"] = "live",
    ) -> str:
        """Find up to five dated ship blueprint recipes and engineers. Query by ID, name or module. Costs cover only the explicit applications at one grade, not a full grade climb. Includes journal material symbols; verify inventory and engineer access separately."""
        return json.dumps(engineering.lookup(query, grade, applications, galaxy), ensure_ascii=False)

    @server.tool()
    def elite_nearby_services(
        system: str,
        service: Literal["refuel", "repair", "restock", "universal_cartographics", "vista_genomics",
                         "interstellar_factors", "material_trader", "technology_broker", "shipyard", "outfitting", "market"] = "refuel",
        radius_ly: int = 20,
        exclude_permit_systems: bool = False,
        galaxy: Literal["live", "legacy", "unknown"] = "live",
    ) -> str:
        """Find up to five service candidates in at most eight nearby populated Elite systems. Reports search coverage and dated observations. Not an exhaustive nearest search or jump route; verify pads/access with station lookup."""
        return json.dumps(navigation.search(system, service, radius_ly, exclude_permit_systems, galaxy), ensure_ascii=False)

    @server.tool()
    def elite_system_lookup(
        system: str,
        kind: Literal["system", "stations"] = "system",
        query: str = "",
        galaxy: Literal["live", "legacy", "unknown"] = "live",
    ) -> str:
        """Look up an Elite Live system or up to five stations, optionally filtered by name/service. Includes source and observation dates when available."""
        return json.dumps(provider.lookup(system, kind, query, galaxy), ensure_ascii=False)

    @server.tool()
    def elite_station_lookup(
        market_id: str,
        section: Literal["overview", "market", "outfitting", "shipyard"] = "overview",
        query: str = "",
        max_age_hours: float = 24,
        galaxy: Literal["live", "legacy", "unknown"] = "live",
    ) -> str:
        """Get Elite station services, commodity quotes, modules or ships from Spansh. Use the market ID from telemetry/system lookup. Filters before a five-item cap; includes dataset dates."""
        return json.dumps(stations.station(market_id, section, query, max_age_hours, galaxy), ensure_ascii=False)

    @server.tool()
    def elite_trade_compare(
        origin_market_id: str,
        destination_market_id: str,
        free_cargo_tonnes: int,
        credits: int,
        rebuy_reserve: int,
        ship_pad: Literal["S", "M", "L"],
        commodity: str = "",
        max_age_hours: float = 24,
        galaxy: Literal["live", "legacy", "unknown"] = "live",
    ) -> str:
        """Compare one specified Elite trade leg using observed free cargo, credits and rebuy reserve. Returns up to five independent cargo options. Blocks stale/unknown markets and incompatible/unknown pads. Other access conditions remain unverified."""
        return json.dumps(stations.trade(origin_market_id, destination_market_id, free_cargo_tonnes,
            credits, rebuy_reserve, ship_pad, commodity, max_age_hours, galaxy), ensure_ascii=False)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elite Dangerous public-data MCP")
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    create_server(args.cache_dir).run(transport="stdio")

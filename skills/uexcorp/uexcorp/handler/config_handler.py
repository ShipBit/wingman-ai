import os
import yaml
from typing import TYPE_CHECKING
from api.enums import WingmanInitializationErrorType
from api.interface import WingmanInitializationError
from services.file import get_writable_dir
from skills.uexcorp.uexcorp.route_planner import RANKING_PROFIT_PER_STOP, RANKINGS

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext
    from skills.uexcorp.uexcorp.helper import Helper


def get_tools() -> tuple[list, bool]:
    from skills.uexcorp.uexcorp.tool.commodity_information import CommodityInformation
    from skills.uexcorp.uexcorp.tool.commodity_route import CommodityRoute
    from skills.uexcorp.uexcorp.tool.active_trade_route import ActiveTradeRoute
    from skills.uexcorp.uexcorp.tool.item_information import ItemInformation
    from skills.uexcorp.uexcorp.tool.location_information import LocationInformation
    from skills.uexcorp.uexcorp.tool.vehicle_information import VehicleInformation
    from skills.uexcorp.uexcorp.tool.profit_calculation import ProfitCalculation

    needs_authentication = False
    tools = []
    try:
        # Enable all tools by default for now as a test with new skill discovery

        # if retrieve_custom_property_value("tool_commodity_information", errors):
        tools.append(CommodityInformation.TOOL_NAME)
        if CommodityInformation.REQUIRES_AUTHENTICATION:
            needs_authentication = True

        # if True or retrieve_custom_property_value("tool_commodity_route", errors):
        tools.append(CommodityRoute.TOOL_NAME)
        if CommodityRoute.REQUIRES_AUTHENTICATION:
            needs_authentication = True
        tools.append(ActiveTradeRoute.TOOL_NAME)

        # if True or retrieve_custom_property_value("tool_item_information", errors):
        tools.append(ItemInformation.TOOL_NAME)
        if ItemInformation.REQUIRES_AUTHENTICATION:
            needs_authentication = True

        # if True or retrieve_custom_property_value("tool_location_information", errors):
        tools.append(LocationInformation.TOOL_NAME)
        if LocationInformation.REQUIRES_AUTHENTICATION:
            needs_authentication = True

        # if True or retrieve_custom_property_value("tool_vehicle_information", errors):
        tools.append(VehicleInformation.TOOL_NAME)
        if VehicleInformation.REQUIRES_AUTHENTICATION:
            needs_authentication = True

        # if True or retrieve_custom_property_value("tool_profit_calculation", errors):
        tools.append(ProfitCalculation.TOOL_NAME)
        if ProfitCalculation.REQUIRES_AUTHENTICATION:
            needs_authentication = True
    except Exception:
        pass

    return tools, needs_authentication


class ConfigHandler:
    def __init__(
        self,
        helper: "Helper"
    ):
        self.__helper = helper
        self.__wingman: "WingmanContext | None" = None
        self.__fine_config_path: str = get_writable_dir(os.path.join(self.__helper.get_data_path(), "config"))
        self.__api_url: str = "https://data-relay.de/wingmanai/uex/v3"
        self.__api_timeout: int = 10  # seconds per connect/read, not for the whole download
        # Retries are part of the API client: Uex.MAX_RETRIES

        # Longest time a relay bundle is kept; usually refreshed earlier, when the relay has newer data.
        # Short: prices and alerts (+ game version check), long: everything else. Trade routes are derived locally.
        self.__cache_lifetime_short: int = 2 * 60 * 60 # 2 hours
        self.__cache_lifetime_long: int = 14 * 24 * 60 * 60 # 14 days

        tools, _ = get_tools()
        self.__property_retriever = None
        self.__behavior_enabled_tools: list[str] = tools
        self.__behavior_commodity_route_default_count: int = 1
        self.__behavior_commodity_route_use_estimated_availability: bool = True
        self.__behavior_commodity_route_advanced_info: bool = False
        self.__behavior_commodity_route_ranking: str = RANKING_PROFIT_PER_STOP

    async def validate(self, errors: list[WingmanInitializationError], retrieve_custom_property_value: callable) -> list[WingmanInitializationError]:
        self.__property_retriever = retrieve_custom_property_value
        try:
            self.set_behavior_commodity_route_default_count(
                retrieve_custom_property_value("commodity_route_default_count", errors)
            )

            self.set_behavior_commodity_route_use_estimated_availability(
                retrieve_custom_property_value("commodity_route_use_estimated_availability", errors)
            )

            self.set_behavior_commodity_route_advanced_info(
                retrieve_custom_property_value("commodity_route_advanced_info", errors)
            )

            # Ranking and default stops are read on demand (getters): saved configs from before these
            # options don't have them, and Core doesn't add new options to saved configs

        except Exception as e:
            self.__helper.get_handler_debug().write(f"Error while validating config: {e}", True)
            self.__helper.get_handler_error().write("ConfigHandler.validate", [errors], e)
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.get_wingman().name,
                    message=f"Error while validating config for uexcorp skill: {e}",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        return errors

    def sync_blacklists(self):
        # Without data the files would be rewritten as empty lists, losing the user's choices
        if not self.__helper.get_handler_import() or not self.__helper.get_handler_import().has_data():
            return
        self.__sync_commodity_blacklist()
        self.__sync_terminal_blacklist()

    def __sync_commodity_blacklist(self):
        from skills.uexcorp.uexcorp.data_access.commodity_data_access import CommodityDataAccess

        if not self.__helper.is_ready():
            return False

        file_path = os.path.join(
            self.__fine_config_path, "commodity_blacklist.yaml"
        )

        # sync status from file to database
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    commodity_data = yaml.safe_load(file)

                if commodity_data:
                    for index, commodity in enumerate(commodity_data):
                        commodity_model = CommodityDataAccess().load_by_property("id", commodity["id"])
                        if commodity_model is None:
                            continue
                        commodity_model.set_is_blacklisted(bool(commodity["is_blacklisted"]))
                        commodity_model.persist(index < len(commodity_data) - 1)
            except Exception as e:
                self.__helper.get_handler_debug().write(f"Error while syncing commodity blacklist: {e}", True)
                self.__helper.get_handler_error().write("ConfigHandler.__init_commodity_blacklist", [], e)
                self.__helper.get_handler_debug().write("Commodity blacklist config will be recreated.", True)

            # delete file after sync
            os.remove(file_path)

        # rewrite file to add possible new commodities
        commodities = CommodityDataAccess().add_filter_has_sell_price().add_filter_has_buy_price().load()
        commodity_data = []
        for commodity in commodities:
            commodity_data.append(
                {
                    "id": commodity.get_id(),
                    "commodity": commodity.get_name(),
                    "is_blacklisted": bool(commodity.get_is_blacklisted()),
                }
            )

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("# Only the 'is_blacklisted' value must be changed to 'true' or 'false'.")
                file.write("\n# Blacklisted commodities ('is_blacklisted: true') will be ignored in trade route calculations.")
                file.write("\n# If the yaml-format gets corrupted, the file will be deleted and recreated on the next start.")
                file.write("\n# This would reset previous set commodity blacklists.\n\n")
                file.write(yaml.dump(commodity_data))
        except Exception as e:
            # E.g. the file is open in an editor: the next import run writes it again
            self.__helper.get_handler_debug().write(f"Error while writing commodity blacklist: {e}")
            self.__helper.get_handler_error().write("ConfigHandler.__init_commodity_blacklist", [], e)

    def __sync_terminal_blacklist(self):
        from skills.uexcorp.uexcorp.data_access.terminal_data_access import TerminalDataAccess

        if not self.__helper.is_ready():
            return False

        file_path = os.path.join(
            self.__fine_config_path, "terminal_blacklist.yaml"
        )

        # sync status from file to database
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    terminal_data = yaml.safe_load(file)

                for index, terminal in enumerate(terminal_data):
                    terminal_model = TerminalDataAccess().load_by_property("id", terminal["id"])
                    if terminal_model is None:
                        continue
                    terminal_model.set_is_blacklisted(bool(terminal["is_blacklisted"]))
                    terminal_model.persist(index < len(terminal_data) - 1)

                # delete file after sync
                os.remove(file_path)
            except Exception as e:
                self.__helper.get_handler_debug().write(f"Error while syncing terminal blacklist: {e}", True)
                self.__helper.get_handler_error().write("ConfigHandler.__init_terminal_blacklist", [], e)
                self.__helper.get_handler_debug().write("Terminal blacklist config will be recreated.", True)

        # rewrite file to add possible new terminals
        terminals = TerminalDataAccess().load()
        terminal_data = []
        for terminal in terminals:
            terminal_data.append(
                {
                    "id": terminal.get_id(),
                    "system": terminal.get_star_system_name(),
                    "orbit": terminal.get_orbit_name(),
                    "faction": terminal.get_faction_name(),
                    "terminal": terminal.get_name(),
                    "is_blacklisted": bool(terminal.get_is_blacklisted()),
                }
            )

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("# Only the 'is_blacklisted' value must be changed to 'true' or 'false'.")
                file.write("\n# Blacklisted terminals ('is_blacklisted: true') will be ignored in trade route calculations and buy/sell recommendations.")
                file.write("\n# If the yaml-format gets corrupted, the file will be deleted and recreated on the next start.")
                file.write("\n# This would reset previous set terminal blacklists.\n\n")
                file.write(yaml.dump(terminal_data))
        except Exception as e:
            self.__helper.get_handler_debug().write(f"Error while writing terminal blacklist: {e}", True)
            self.__helper.get_handler_error().write("ConfigHandler.__init_terminal_blacklist", [], e)

    def is_tool_enabled(self, tool_name: str) -> bool:
        return tool_name in self.__behavior_enabled_tools

    def get_api_url(self) -> str:
        return self.__api_url

    def set_api_url(self, api_url: str):
        self.__api_url = api_url

    def get_api_timeout(self) -> int:
        return self.__api_timeout

    def set_api_timeout(self, api_timeout: int):
        self.__api_timeout = api_timeout

    def get_cache_lifetime_short(self) -> int:
        return self.__cache_lifetime_short

    def set_cache_lifetime_short(self, cache_timeout_general: int):
        self.__cache_lifetime_short = cache_timeout_general

    def get_cache_lifetime_long(self) -> int:
        return self.__cache_lifetime_long

    def set_cache_lifetime_long(self, cache_timeout_commodities: int):
        self.__cache_lifetime_long = cache_timeout_commodities

    def get_behavior_commodity_route_default_count(self) -> int:
        # Before validate() (the skill never activated) only the stored value exists.
        if not self.__property_retriever:
            return self.__behavior_commodity_route_default_count
        errors = []
        value = self.__property_retriever("commodity_route_default_count", errors)
        if not errors:
            self.set_behavior_commodity_route_default_count(value)
        return self.__behavior_commodity_route_default_count

    def set_behavior_commodity_route_default_count(self, default_count: int):
        # The same range as the tool's limit parameter
        try:
            self.__behavior_commodity_route_default_count = max(1, min(15, int(default_count)))
        except (TypeError, ValueError):
            self.__behavior_commodity_route_default_count = 1

    def get_behavior_commodity_route_default_max_stops(self) -> int:
        # Read on demand only: configs saved before this option don't have it and get 1
        errors = []
        value = self.__property_retriever("commodity_route_default_max_stops", errors) if self.__property_retriever else None
        try:
            return max(1, int(value)) if not errors and value is not None else 1
        except (TypeError, ValueError):
            return 1

    def get_behavior_commodity_route_use_estimated_availability(self) -> bool:
        # Before validate() (the skill never activated) only the stored value exists.
        if not self.__property_retriever:
            return self.__behavior_commodity_route_use_estimated_availability
        errors = []
        value = self.__property_retriever("commodity_route_use_estimated_availability", errors)
        if not errors:
            self.set_behavior_commodity_route_use_estimated_availability(value)
        return self.__behavior_commodity_route_use_estimated_availability

    def set_behavior_commodity_route_use_estimated_availability(self, use_estimated_availability: bool):
        self.__behavior_commodity_route_use_estimated_availability = use_estimated_availability

    def get_behavior_commodity_route_advanced_info(self) -> bool:
        # Before validate() (the skill never activated) only the stored value exists.
        if not self.__property_retriever:
            return self.__behavior_commodity_route_advanced_info
        errors = []
        value = self.__property_retriever("commodity_route_advanced_info", errors)
        if not errors:
            self.set_behavior_commodity_route_advanced_info(value)
        return self.__behavior_commodity_route_advanced_info

    def set_behavior_commodity_route_advanced_info(self, advanced_info: bool):
        self.__behavior_commodity_route_advanced_info = advanced_info

    def get_behavior_commodity_route_ranking(self) -> str:
        errors = []
        value = self.__property_retriever("commodity_route_ranking", errors) if self.__property_retriever else None
        if not errors and value is not None:
            self.set_behavior_commodity_route_ranking(value)
        return self.__behavior_commodity_route_ranking

    def set_behavior_commodity_route_ranking(self, ranking: str | None):
        # Unknown or missing values (e.g. config from before this option) fall back to the default
        self.__behavior_commodity_route_ranking = ranking if ranking in RANKINGS else RANKING_PROFIT_PER_STOP

    def set_wingman(self, wingman: "WingmanContext"):
        self.__wingman = wingman

    def get_wingman(self) -> "WingmanContext":
        return self.__wingman
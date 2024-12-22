import os
import yaml
import traceback
from typing import TYPE_CHECKING
from api.enums import WingmanInitializationErrorType
from api.interface import WingmanInitializationError
from services.file import get_writable_dir

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman
    try:
        from skills.uexcorp_beta.uexcorp.helper import Helper
    except ImportError:
        from uexcorp_beta.uexcorp.helper import Helper

class ConfigHandler:
    def __init__(
        self,
        helper: "Helper"
    ):
        self.__helper = helper
        self.__wingman: "OpenAiWingman" | None = None
        self.__fine_config_path: str = get_writable_dir(os.path.join(self.__helper.get_data_path(), "config"))
        self.__api_url: str = "https://uexcorp.space/api/2.0"
        self.__api_use_key: bool = False
        self.__api_key: str | None = None
        self.__api_timeout: int = 10
        self.__api_retries: int = 2

        self.__cache_lifetime_short: int = 60 * 60# 30 minutes
        self.__cache_lifetime_mid: int = 24 * 60 * 60 # 24 hours
        self.__cache_lifetime_long: int = 14 * 24 * 60 * 60 # 14 days

        self.__behavior_commodity_route_start_location_mandatory: bool = True
        self.__behavior_commodity_route_default_count: int = 1
        self.__behavior_commodity_route_use_estimated_availability: bool = True
        self.__behavior_commodity_route_advanced_info: bool = False

    async def validate(self, errors: list[WingmanInitializationError], retrieve_custom_property_value: callable) -> list[WingmanInitializationError]:
        try:
            api_use_key = retrieve_custom_property_value("api_use_key", errors)
            self.set_api_use_key(api_use_key)

            if self.get_api_use_key():
                api_key = await self.__helper.get_handler_secret().retrieve(
                    requester="UEX config service",
                    key="uex",
                    prompt_if_missing=True
                )
                if api_key:
                    self.set_api_key(api_key)

            self.set_behavior_commodity_route_start_location_mandatory(
                retrieve_custom_property_value("commodity_route_start_location_mandatory", errors)
            )

            self.set_behavior_commodity_route_default_count(
                retrieve_custom_property_value("commodity_route_default_count", errors)
            )

            self.set_behavior_commodity_route_use_estimated_availability(
                retrieve_custom_property_value("commodity_route_use_estimated_availability", errors)
            )

            self.set_behavior_commodity_route_advanced_info(
                retrieve_custom_property_value("commodity_route_advanced_info", errors)
            )
        except Exception as e:
            self.__helper.get_handler_debug().write(f"Error while validating config: {e}", True)
            self.__helper.get_handler_error().write("ConfigHandler.validate", [errors], e, traceback.format_exc())
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.get_wingman().name,
                    message=f"Error while validating config for uexcorp skill: {e}",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        return errors

    def sync_blacklists(self):
        self.__sync_commodity_blacklist()
        self.__sync_terminal_blacklist()

    def __sync_commodity_blacklist(self):
        try:
            from skills.uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess
        except ImportError:
            from uexcorp_beta.uexcorp.data_access.commodity_data_access import CommodityDataAccess

        if not self.__helper.is_ready():
            return False

        file_path = os.path.join(
            self.__fine_config_path, "commodity_blacklist.yaml"
        )

        # sync status from file to database
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
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
                self.__helper.get_handler_error().write("ConfigHandler.__init_commodity_blacklist", [], e, traceback.format_exc())
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

        with open(file_path, 'w') as file:
            file.write("# Only the 'is_blacklisted' value must be changed to 'true' or 'false'.")
            file.write("\n# Blacklisted commodities ('is_blacklisted: true') will be ignored in trade route calculations.")
            file.write("\n# If the yaml-format gets corrupted, the file will be deleted and recreated on the next start.")
            file.write("\n# This would reset previous set commodity blacklists.\n\n")
            file.write(yaml.dump(commodity_data))

    def __sync_terminal_blacklist(self):
        try:
            from skills.uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess
        except ImportError:
            from uexcorp_beta.uexcorp.data_access.terminal_data_access import TerminalDataAccess

        if not self.__helper.is_ready():
            return False

        file_path = os.path.join(
            self.__fine_config_path, "terminal_blacklist.yaml"
        )

        # sync status from file to database
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    terminal_data = yaml.safe_load(file)

                for index, terminal in enumerate(terminal_data):
                    terminal_model = TerminalDataAccess().load_by_property("id", terminal["id"])
                    if terminal_model is None:
                        continue
                    terminal_model.set_is_blacklisted(bool(terminal["is_blacklisted"]))
                    terminal_model.persist(index < len(terminal_data) - 1)
            except Exception as e:
                self.__helper.get_handler_debug().write(f"Error while syncing terminal blacklist: {e}", True)
                self.__helper.get_handler_error().write("ConfigHandler.__init_terminal_blacklist", [], e, traceback.format_exc())
                self.__helper.get_handler_debug().write("Terminal blacklist config will be recreated.", True)

            # delete file after sync
            os.remove(file_path)

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

        with open(file_path, "w") as file:
            file.write("# Only the 'is_blacklisted' value must be changed to 'true' or 'false'.")
            file.write("\n# Blacklisted terminals ('is_blacklisted: true') will be ignored in trade route calculations and buy/sell recommendations.")
            file.write("\n# If the yaml-format gets corrupted, the file will be deleted and recreated on the next start.")
            file.write("\n# This would reset previous set terminal blacklists.\n\n")
            file.write(yaml.dump(terminal_data))

    def handle_secret_change(self, api_key: str):
        self.set_api_key(api_key)

    def get_api_url(self) -> str:
        return self.__api_url

    def set_api_url(self, api_url: str):
        self.__api_url = api_url

    def get_api_use_key(self) -> bool:
        return self.__api_use_key and self.__api_key is not None

    def set_api_use_key(self, api_use_key: bool):
        self.__api_use_key = api_use_key

    def get_api_key(self) -> str | None:
        return self.__api_key

    def set_api_key(self, api_key: str):
        self.__api_key = api_key

    def get_api_timeout(self) -> int:
        return self.__api_timeout

    def set_api_timeout(self, api_timeout: int):
        self.__api_timeout = api_timeout

    def get_api_retries(self) -> int:
        return self.__api_retries

    def set_api_retries(self, api_retries: int):
        self.__api_retries = api_retries

    def get_cache_lifetime_short(self) -> int:
        return self.__cache_lifetime_short

    def set_cache_lifetime_short(self, cache_timeout_general: int):
        self.__cache_lifetime_short = cache_timeout_general

    def get_cache_lifetime_mid(self) -> int:
        return self.__cache_lifetime_mid

    def set_cache_lifetime_mid(self, cache_timeout_routes: int):
        self.__cache_lifetime_mid = cache_timeout_routes

    def get_cache_lifetime_long(self) -> int:
        return self.__cache_lifetime_long

    def set_cache_lifetime_long(self, cache_timeout_commodities: int):
        self.__cache_lifetime_long = cache_timeout_commodities

    def get_behavior_commodity_route_start_location_mandatory(self) -> bool:
        return self.__behavior_commodity_route_start_location_mandatory

    def set_behavior_commodity_route_start_location_mandatory(self, mandatory: bool):
        self.__behavior_commodity_route_start_location_mandatory = mandatory

    def get_behavior_commodity_route_default_count(self) -> int:
        return self.__behavior_commodity_route_default_count

    def set_behavior_commodity_route_default_count(self, default_count: int):
        self.__behavior_commodity_route_default_count = default_count

    def get_behavior_commodity_route_use_estimated_availability(self) -> bool:
        return self.__behavior_commodity_route_use_estimated_availability

    def set_behavior_commodity_route_use_estimated_availability(self, use_estimated_availability: bool):
        self.__behavior_commodity_route_use_estimated_availability = use_estimated_availability

    def get_behavior_commodity_route_advanced_info(self) -> bool:
        return self.__behavior_commodity_route_advanced_info

    def set_behavior_commodity_route_advanced_info(self, advanced_info: bool):
        self.__behavior_commodity_route_advanced_info = advanced_info

    def set_wingman(self, wingman: "OpenAiWingman"):
        self.__wingman = wingman

    def get_wingman(self) -> "OpenAiWingman":
        return self.__wingman
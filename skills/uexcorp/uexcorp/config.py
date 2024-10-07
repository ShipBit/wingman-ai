from skills.uexcorp.uexcorp.helper import Helper


class Config:
    def __init__(
        self,
        helper: Helper,#
    ):
        self.helper = helper

        # initialize config values
        self.api_url: str = None
        self.api_key: int = None
        self.api_timeout: int = 10
        self.api_retries: int = 2
        self.cache: bool = True
        self.cache_timeout_general: int = 86400
        self.cache_timeout_gameversion: int = 300
        self.cache_timeout_prices: int = 1800
        self.behavior_summarize_commodity: bool = True
        self.behavior_trade_mandatory_start_location: bool = True
        self.behavior_trade_blacklist: list = []
        self.behavior_trade_default_count: int = 2
        self.behavior_trade_use_estimated_availability: bool = True
        self.behavior_lore: bool = False

    def get_api_url(self):
        return self.api_url
    def set_api_url(self, api_url: str):
        self.api_url = api_url

    def get_api_key(self):
        return self.api_key
    def set_api_key(self, api_key: int):
        self.api_key = api_key

    def get_api_timeout(self):
        return self.api_timeout
    def set_api_timeout(self, api_timeout: int):
        self.api_timeout = api_timeout

    def get_api_retries(self):
        return self.api_retries
    def set_api_retries(self, api_retries: int):
        self.api_retries = api_retries

    def get_cache(self):
        return self.cache
    def set_cache(self, cache: bool):
        self.cache = cache

    def get_cache_timeout_general(self):
        return self.cache_timeout_general
    def set_cache_timeout_general(self, cache_timeout_general: int):
        self.cache_timeout_general = cache_timeout_general

    def get_cache_timeout_prices(self):
        return self.cache_timeout_prices
    def set_cache_timeout_prices(self, cache_timeout_prices: int):
        self.cache_timeout_prices = cache_timeout_prices

    def get_behavior_summarize_commodity(self):
        return self.behavior_summarize_commodity
    def set_behavior_summarize_commodity(self, behavior_summarize_commodity: bool):
        self.behavior_summarize_commodity = behavior_summarize_commodity

    def get_behavior_trade_mandatory_start_location(self):
        return self.behavior_trade_mandatory_start_location
    def set_behavior_trade_mandatory_start_location(self, behavior_trade_mandatory_start_location: bool):
        self.behavior_trade_mandatory_start_location = behavior_trade_mandatory_start_location

    def get_behavior_trade_blacklist(self):
        return self.behavior_trade_blacklist
    def set_behavior_trade_blacklist(self, behavior_trade_blacklist: list):
        self.behavior_trade_blacklist = behavior_trade_blacklist

    def get_behavior_trade_default_count(self):
        return self.behavior_trade_default_count
    def set_behavior_trade_default_count(self, behavior_trade_default_count: int):
        self.behavior_trade_default_count = behavior_trade_default_count

    def get_behavior_trade_use_estimated_availability(self):
        return self.behavior_trade_use_estimated_availability
    def set_behavior_trade_use_estimated_availability(self, behavior_trade_use_estimated_availability: bool):
        self.behavior_trade_use_estimated_availability = behavior_trade_use_estimated_availability

    def get_behavior_lore(self):
        return self.behavior_lore
    def set_behavior_lore(self, behavior_lore: bool):
        self.behavior_lore = behavior_lore

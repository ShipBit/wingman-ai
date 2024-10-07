from skills.uexcorp.uexcorp.helper import Helper


class Api:
    GAME_VERSION = 'game_versions'
    VEHICLES = 'vehicles'
    STAR_SYSTEMS = 'star_systems'
    PLANETS = 'planets'
    MOONS = 'moons'
    CITIES = 'cities'
    TERMINALS = 'terminals'
    COMMODITIES = 'commodities'
    VEHICLE_PRICES_BUY = 'vehicles_purchases_prices_all'
    VEHICLE_PRICES_RENT = 'vehicles_rentals_prices_all'
    COMMODITY_PRICES = 'commodities_prices'

    def __init__(
        self,
        helper: Helper,
    ):
        self.helper = helper

    def fetch(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        """
        Fetches data from the specified endpoint.

        Args:
            endpoint (str): The API endpoint to fetch data from.
            params (Optional[dict[str, any]]): Optional parameters to include in the request.

        Returns:
            list[dict[str, any]]: The fetched data as a list of dictionaries.
        """
        url = f"{self.uexcorp_api_url}/{endpoint}"
        await self._print(f"Fetching data from {url} ...", True)

        request_count = 1
        timeout_error = False
        requests_error = False

        while request_count == 1 or (
                request_count <= (self.uexcorp_api_timeout_retries + 1) and timeout_error
        ):
            if requests_error:
                await self._print(f"Retrying request #{request_count}...", True)
                requests_error = False

            timeout_error = False
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=(self.uexcorp_api_timeout * request_count),
                    headers=self._get_header(),
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                await self._print(f"Error while retrieving data from {url}: {e}")
                requests_error = True
                if isinstance(e, requests.exceptions.Timeout):
                    timeout_error = True
            request_count += 1

        if requests_error:
            return []

        response_json = response.json()
        if "status" not in response_json or response_json["status"] != "ok":
            await self._print(f"Error while retrieving data from {url}")
            return []

        return response_json.get("data", [])
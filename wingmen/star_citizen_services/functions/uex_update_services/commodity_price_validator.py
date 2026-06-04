from wingmen.star_citizen_services.helper import find_best_match as search


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class CommodityPriceValidator:
    @staticmethod
    def normalize_numeric_value(value, default=0):
        if value is None or value == "":
            return default
        if isinstance(value, (int, float)):
            return value

        normalized = str(value).strip()
        if not normalized:
            return default

        normalized = normalized.replace("\u00a0", " ").replace(" ", "")
        if "," in normalized and "." in normalized:
            normalized = normalized.replace(",", "")
        elif "," in normalized:
            normalized = normalized.replace(",", "")

        try:
            parsed = float(normalized)
        except ValueError:
            return default

        if parsed.is_integer():
            return int(parsed)
        return parsed

    @staticmethod
    def normalize_price_for_display(value, multiplier=None):
        normalized = CommodityPriceValidator.normalize_numeric_value(value)
        try:
            if CommodityPriceValidator._normalized_multiplier(multiplier):
                return CommodityPriceValidator._normalize_uex_price(normalized)
            return int(round(float(normalized)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalized_multiplier(multiplier):
        if not multiplier:
            return None
        multiplier = str(multiplier).strip()
        if not multiplier or multiplier.lower() == "none":
            return None
        first_character = multiplier.lower()[0]
        if first_character in {"k", "m"}:
            return first_character
        return None

    @staticmethod
    def _multiplier_factor(multiplier):
        normalized_multiplier = CommodityPriceValidator._normalized_multiplier(multiplier)
        if normalized_multiplier == "m":
            return 1000000
        if normalized_multiplier == "k":
            return 1000
        return 1

    @staticmethod
    def _normalize_uex_price(value):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return int(numeric_value)
        return round(numeric_value, 8)

    @staticmethod
    def _price_candidates(price_to_check, multiplier):
        raw_price = CommodityPriceValidator.normalize_numeric_value(price_to_check, default=None)
        if raw_price is None:
            return []

        raw_price = float(raw_price)
        normalized_multiplier = CommodityPriceValidator._normalized_multiplier(multiplier)
        factor = CommodityPriceValidator._multiplier_factor(multiplier)
        candidates = []

        def add_candidate(display_price, uex_price):
            normalized_display = CommodityPriceValidator._normalize_uex_price(display_price)
            normalized_uex = CommodityPriceValidator._normalize_uex_price(uex_price)
            candidate_key = (normalized_display, normalized_uex)
            if candidate_key not in {(item["display_price"], item["uex_price"]) for item in candidates}:
                candidates.append(
                    {
                        "display_price": normalized_display,
                        "uex_price": normalized_uex,
                    }
                )

        if normalized_multiplier:
            # Multiplied terminal prices may legitimately contain decimals, e.g. 3.984 K.
            add_candidate(raw_price, raw_price * factor)
            return candidates

        # Non-multiplied terminal prices do not have decimals. A comma is a
        # thousands separator; if OCR turned it into a decimal point, keep both
        # plausible interpretations and let UEX proximity decide.
        rounded_price = int(round(raw_price))
        add_candidate(rounded_price, rounded_price)
        if not raw_price.is_integer() and 0 < raw_price < 1000:
            thousands_price = int(round(raw_price * 1000))
            add_candidate(thousands_price, thousands_price)

        sanitize_price = raw_price
        for _ in range(2):
            sanitize_price *= 10
            add_candidate(int(round(sanitize_price)), int(round(sanitize_price)))

        return candidates

    @staticmethod
    def calculate_uex_price(price_per_unit, multiplier=None):
        price = CommodityPriceValidator.normalize_numeric_value(price_per_unit, default=0)
        factor = CommodityPriceValidator._multiplier_factor(multiplier)
        return CommodityPriceValidator._normalize_uex_price(float(price) * factor)

    @staticmethod
    def validate_price_information(commodities_price_info_raw, terminal_prices, operation):
        validated_prices = []
        invalid_prices = []
        all_prices = []
        terminal_prices = list(terminal_prices or [])

        for price_info_raw in commodities_price_info_raw:
            print_debug(f"checking {price_info_raw}")
            if not price_info_raw.get("commodity_name", False):
                print_debug("missing commodity attribute, skipping")
                continue

            price_info_raw["available_SCU_quantity"] = CommodityPriceValidator.normalize_price_for_display(
                price_info_raw.get("available_SCU_quantity")
            )

            commodity_raw_name = price_info_raw.get("commodity_name")

            # we want to find the commodity in the terminal prices list
            match_result, success = search.find_best_match(commodity_raw_name, terminal_prices, attributes=["commodity_name"])
            
            if not success:
                print_debug(f"{commodity_raw_name} ... skipping")
                price_info_raw["validation_result"] = "commodity not found"
                price_info_raw["code"] = ""
                invalid_prices.append(price_info_raw)
                all_prices.append(price_info_raw)
                continue

            current_commodity_price_object = match_result["root_object"]
           
            price_raw = price_info_raw.get("price_per_unit")
            multiplier = price_info_raw.get("multiplier")

            price_validation = CommodityPriceValidator.validate_price(
                current_commodity_price_object,
                price_raw,
                multiplier,
                operation,
            )
            new_price = price_validation["uex_price"]
            display_price = price_validation["display_price"]
            success = price_validation["success"]

            # inject found information 
            price_info_raw["code"] = current_commodity_price_object["id_commodity"]
            price_info_raw["commodity_name"] = current_commodity_price_object["commodity_name"]
            
            if not success:
                print_debug(f"{new_price} not plausible ... skipping")
                price_info_raw["price_per_unit"] = display_price
                price_info_raw["validation_result"] = "price not plausible"
                invalid_prices.append(price_info_raw)
                all_prices.append(price_info_raw)
                
            else:               
                price_info_raw["price_per_unit"] = display_price
                price_info_raw["uex_price"] = new_price
                price_info_raw["validation_result"] = "all plausible"
                validated_prices.append(price_info_raw)
                all_prices.append(price_info_raw)

        return all_prices, validated_prices, invalid_prices, True

    @staticmethod
    def validate_price(uex_current_price_object, price_to_check, multiplier, operation):
        if not price_to_check:
            return {"uex_price": 0, "display_price": 0, "success": False}
        
        uex_price = uex_current_price_object[f"price_{operation}"]
        candidates = CommodityPriceValidator._price_candidates(price_to_check, multiplier)
        if not candidates:
            return {"uex_price": 0, "display_price": 0, "success": False}

        best_candidate = min(candidates, key=lambda candidate: abs(uex_price - candidate["uex_price"]))
        difference = abs(uex_price - best_candidate["uex_price"])
        success = difference < 0.4 * uex_price
        return {
            "uex_price": best_candidate["uex_price"],
            "display_price": best_candidate["display_price"],
            "success": success,
        }

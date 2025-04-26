from wingmen.star_citizen_services.helper import find_best_match as search


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class CommodityPriceValidator:
    @staticmethod
    def validate_price_information(commodities_price_info_raw, terminal_prices, operation):
        validated_prices = []
        invalid_prices = []
        all_prices = []

        for price_info_raw in commodities_price_info_raw:
            print_debug(f"checking {price_info_raw}")
            if not price_info_raw.get("commodity_name", False):
                print_debug("missing commodity attribute, skipping")
                continue

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

            new_price, success = CommodityPriceValidator.validate_price(current_commodity_price_object, price_raw, multiplier, operation)

            # inject found information 
            price_info_raw["code"] = current_commodity_price_object["id_commodity"]
            price_info_raw["commodity_name"] = current_commodity_price_object["commodity_name"]
            
            if not success:
                print_debug(f"{new_price} not plausible ... skipping")
                price_info_raw["validation_result"] = "price not plausible"
                invalid_prices.append(price_info_raw)
                all_prices.append(price_info_raw)
                
            else:               
                price_info_raw["uex_price"] = new_price
                price_info_raw["validation_result"] = "all plausible"
                validated_prices.append(price_info_raw)
                all_prices.append(price_info_raw)

        return all_prices, validated_prices, invalid_prices, True

    @staticmethod
    def validate_price(uex_current_price_object, price_to_check, multiplier, operation):
        if not price_to_check:
            return 0, False
        
        uex_price = uex_current_price_object[f"price_{operation}"]
        
        # we check, if the raw price is within 20% of the current price
        difference = abs(uex_price - price_to_check)

        if difference < 0.2 * uex_price:  # as of uex api tolerance for price changes
            return price_to_check, True
        
        # we can check, if we would be in range, if we apply the given multiplicator
        if multiplier and multiplier.lower()[0] == "m":
            price_to_check = price_to_check * 1000000
        
        if multiplier and multiplier.lower()[0] == "k":
            price_to_check = price_to_check * 1000

        difference = abs(uex_price - price_to_check)

        if difference < 0.4 * uex_price:  # prices with 20% variance are ok and will be accepted, higher variance is subject to validation at UEX, we accept up to 40% before we reject.
            return price_to_check, True
        
        # sometimes, we receive . price. instead of 168 for instance 1.68. we try to multiply in 10 steps 2 times and see if we get a plausible price with low variance, then we accept it
        index = 1
        sanitize_price = price_to_check
        while index <= 2:
            sanitize_price = sanitize_price * 10

            difference = abs(uex_price - sanitize_price)

            if difference < 0.2 * uex_price:  # prices with 20% variance are ok 
                return sanitize_price, True
            
            index += 1

        return sanitize_price, False

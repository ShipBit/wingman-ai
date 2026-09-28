"""Stable field types at the reader/state boundary; never parse game wording here."""

import math

TEXT_FIELDS = frozenset(
    [
        "mission_id",
        "mission_name",
        "objective",
        "objective_id",
        "body_part",
        "severity",
        "player_name",
        "player_geid",
        "shard",
        "location",
        "location_guid",
        "loc_from",
        "loc_to",
        "action",
        "channel_raw",
        "entity_class",
        "vehicle",
        "player_id",
        "shop_id",
        "kiosk_id",
        "source_provider",
        "currency",
        "currency_type",
        "result_text",
        "transaction_type",
        "item_name",
        "blueprint_name",
        "recipient",
        "jurisdiction",
        "ship_name",
        "ship_class",
        "owner",
        "notification_id",
        "game_build",
    ]
)
NUMERIC_FIELDS = frozenset(
    ["amount", "price", "quantity", "quantity_cscu", "tier", "player_pilot"]
)


def field_errors(fields, kind=None):
    if not isinstance(fields, dict):
        return ["invalid:fields"]
    errors = []
    for name, value in fields.items():
        valid = True
        if (
            name in TEXT_FIELDS
            or name == "result"
            and kind == "shop_transaction_result"
        ):
            valid = isinstance(value, str) and len(value) <= 65536
        elif name in NUMERIC_FIELDS:
            try:
                valid = not isinstance(value, bool) and math.isfinite(float(value))
            except (TypeError, ValueError, OverflowError):
                valid = False
        elif name == "healed_parts":
            valid = (
                isinstance(value, dict)
                and len(value) <= 32
                and all(
                    isinstance(k, str) and type(v) is bool for k, v in value.items()
                )
            )
        if not valid:
            errors.append("invalid:" + name)
    return errors

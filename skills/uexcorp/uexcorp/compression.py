import json

# Values that carry no information and are dropped from AI tool responses to
# save tokens. The convention "omitted field = unknown / not available" is
# documented once in the tool help prompt, so stripping these is lossless.
_EMPTY_STRINGS = {"", "n/a", "na", "unknown", "none", "null"}


def _is_empty(value) -> bool:
    # Note: 0 and False are meaningful values and are intentionally NOT empty.
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _EMPTY_STRINGS
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def number(value):
    """Return whole floats as int (110000.0 -> 110000). For embedding in strings."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def compact(value):
    """Recursively remove keys/items that carry no information.

    Drops None, empty strings, the sentinels "N/A"/"unknown"/etc. and empty
    containers. Keeps 0 and False, which are meaningful. Whole floats are
    emitted as ints. Lossless under the documented convention that an omitted
    field is unknown / not available.
    """
    if isinstance(value, dict):
        cleaned = {}
        for key, val in value.items():
            val = compact(val)
            if not _is_empty(val):
                cleaned[key] = val
        return cleaned
    if isinstance(value, (list, tuple)):
        cleaned = [compact(item) for item in value]
        return [item for item in cleaned if not _is_empty(item)]
    return number(value)


def dumps(value) -> str:
    """Serialize for AI consumption: empties stripped, no whitespace padding."""
    return json.dumps(compact(value), separators=(",", ":"), ensure_ascii=False)

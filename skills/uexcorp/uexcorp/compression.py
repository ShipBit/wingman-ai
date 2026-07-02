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


# Key shortening: repeated long snake_case keys are replaced by their initials
# and a legend {short: full} is prepended under this key, so the response stays
# self-describing. Only keys where the abbreviation saves more characters than
# its legend entry costs are shortened.
LEGEND_KEY = "keys"

# Only multi-word snake_case keys of at least this length are considered.
# Short single words ("name", "scu") tokenize to ~1 token either way, so
# abbreviating them saves nothing and only hurts readability.
_MIN_KEY_LENGTH = 10


def _count_keys(value, counts: dict) -> None:
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(key, str):
                counts[key] = counts.get(key, 0) + 1
            _count_keys(val, counts)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _count_keys(item, counts)


def _key_tokens(key: str) -> float:
    # snake_case words tokenize at roughly 4 chars/token (plus quotes/colon).
    return len(key) / 4 + 1


def _short_tokens(short: str) -> float:
    # Letter-soup abbreviations tokenize much denser, roughly 2 chars/token.
    return len(short) / 2 + 1


def _build_key_map(counts: dict) -> dict:
    """Map full key -> short key for every abbreviation that nets a saving."""
    used = set(counts)  # never collide with a key that exists in the data
    mapping = {}
    # Biggest total footprint first, name as tie-breaker for determinism.
    for key in sorted(counts, key=lambda k: (-len(k) * counts[k], k)):
        if len(key) < _MIN_KEY_LENGTH or "_" not in key:
            continue
        short = "".join(part[0] for part in key.split("_") if part)
        candidate = short
        suffix = 2
        while candidate in used:
            candidate = f"{short}{suffix}"
            suffix += 1
        # Estimated token saving across all occurrences vs. the cost of the
        # legend entry ("short":"full",). Chars mislead here: abbreviations
        # tokenize worse per char than words, so demand a clear margin.
        saved = counts[key] * (_key_tokens(key) - _short_tokens(candidate))
        legend_cost = _short_tokens(candidate) + _key_tokens(key) + 1
        if saved > legend_cost * 1.5:
            mapping[key] = candidate
            used.add(candidate)
    return mapping


def _rename_keys(value, mapping: dict):
    if isinstance(value, dict):
        return {mapping.get(key, key): _rename_keys(val, mapping) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rename_keys(item, mapping) for item in value]
    return value


def dumps(value) -> str:
    """Serialize for AI consumption: empties stripped, no whitespace padding.

    Repeated long keys are shortened and documented in a leading "keys" legend:
    {"keys":{"bpft":"buy_price_from_terminal",...},"data":...}
    """
    value = compact(value)

    counts = {}
    _count_keys(value, counts)
    mapping = _build_key_map(counts)
    if mapping:
        total_saved = sum(
            counts[full] * (_key_tokens(full) - _short_tokens(short))
            - (_short_tokens(short) + _key_tokens(full) + 1)
            for full, short in mapping.items()
        )
        # The wrapper object itself costs ~10 tokens; only shorten when there
        # is a real net saving.
        if total_saved > 20:
            value = {
                LEGEND_KEY: {short: full for full, short in mapping.items()},
                "data": _rename_keys(value, mapping),
            }

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

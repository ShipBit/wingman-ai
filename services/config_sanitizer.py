"""Keeps a config loadable when it names something that no longer exists.

A config is a YAML file the user has been carrying since 2.1.1, and almost every
provider field in it is a Pydantic `Enum`. Pydantic rejects an unknown enum value
outright, so a single stale word stops the whole wingman from loading — and the
message it produces points at a line the user never wrote by hand.

The Azure removal made this concrete: `azure`, `azure_speech` and `whisper` were
all valid in 3.1.6 and none of them exist now. The migration rewrites those, but
a migration only helps for the cases we thought of. This runs on every load and
covers the ones we did not: a provider dropped next year, a model name retired
by its vendor, a hand-edited file with a typo.

The rule is always the same — an unknown value becomes a known one, and the
substitution is logged. Nothing here ever raises.
"""

import types
from enum import Enum
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined


def _is_union(origin: Any) -> bool:
    """True for both spellings of a union.

    ``Optional[X]`` and ``Union[X, None]`` have ``typing.Union`` as their origin.
    ``X | None`` does not — since Python 3.10 that is a ``types.UnionType``, a
    different object. Checking only for ``typing.Union`` silently skips every
    field written in the pipe form, which is the form anyone adds today.
    """
    return origin is Union or origin is types.UnionType


def _unwrap_optional(annotation: Any) -> Any:
    """`Optional[X]` and `X | None` both arrive as a union with NoneType."""
    if _is_union(get_origin(annotation)):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _is_enum(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, Enum)


def _model_candidates(annotation: Any) -> tuple[list[type], list[type]]:
    """The models a Union could hold, split into plain and list-of.

    `CustomProperty.value` is a union of eleven things, one of which is
    `VoiceSelection` and another `list[VoiceSelection]`. That is where the voice
    changer skill keeps its voices, so it is exactly where a 2.1.1 user's
    `provider: azure` survives. Guessing the branch is fine here because we only
    ever recurse — picking wrong changes nothing.
    """
    plain: list[type] = []
    listed: list[type] = []
    for arg in get_args(annotation):
        if arg is type(None):
            continue
        inner = _unwrap_optional(arg)
        if _is_model(inner):
            plain.append(inner)
        elif get_origin(inner) in (list, set, tuple):
            item_args = get_args(inner)
            if item_args and _is_model(_unwrap_optional(item_args[0])):
                listed.append(_unwrap_optional(item_args[0]))
    return plain, listed


def _best_match(candidates: list[type], value: dict) -> type | None:
    """The model whose fields cover this dict, most specific first. None when no
    branch fits — a value we do not recognise is left exactly as it is."""
    fitting = [c for c in candidates if set(value.keys()) <= set(c.model_fields.keys())]
    return min(fitting, key=lambda c: len(c.model_fields)) if fitting else None


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _valid(enum_cls: type[Enum], value: Any) -> bool:
    if isinstance(value, enum_cls):
        return True
    try:
        enum_cls(value)
        return True
    except ValueError:
        return False


def _replacement(enum_cls: type[Enum], field, fallback: Any) -> Any:
    """What a rejected value becomes.

    The template config first: it is what a fresh install would have, so it keeps
    a repaired config close to the one the user would get today. Then the field's
    own default. Failing both, the first member — arbitrary, but every enum has
    one, and any valid value beats refusing to start.
    """
    if fallback is not None and _valid(enum_cls, fallback):
        return fallback.value if isinstance(fallback, Enum) else fallback

    default = getattr(field, "default", PydanticUndefined)
    if default is not PydanticUndefined and default is not None and _valid(enum_cls, default):
        return default.value if isinstance(default, Enum) else default

    first = next(iter(enum_cls))
    return first.value


def sanitize(
    model_cls: type[BaseModel],
    data: Any,
    fallback: Any = None,
    path: str = "",
) -> list[str]:
    """Replaces unknown enum values in `data` in place.

    `fallback` is the matching slice of the default config, used as the preferred
    replacement. Returns one line per change, for the caller to log.
    """
    if not isinstance(data, dict) or not _is_model(model_cls):
        return []

    changes: list[str] = []
    fallback_dict = fallback if isinstance(fallback, dict) else {}

    for name, field in model_cls.model_fields.items():
        if name not in data:
            continue
        value = data[name]
        annotation = _unwrap_optional(field.annotation)
        here = f"{path}.{name}" if path else name
        sub_fallback = fallback_dict.get(name)

        if _is_enum(annotation):
            # None on an optional field means "not set", which is a valid state
            # and not something to repair.
            if value is None:
                continue
            if not _valid(annotation, value):
                data[name] = _replacement(annotation, field, sub_fallback)
                changes.append(f"{here}: '{value}' is unknown, using '{data[name]}'")
            continue

        if _is_model(annotation):
            changes += sanitize(annotation, value, sub_fallback, here)
            continue

        origin = get_origin(annotation)

        # A union of several real types, not just `X | None`. `_unwrap_optional`
        # left it alone, so pick the branch that fits what is actually stored.
        if _is_union(origin):
            plain, listed = _model_candidates(annotation)
            if isinstance(value, dict) and plain:
                match = _best_match(plain, value)
                if match:
                    changes += sanitize(match, value, sub_fallback, here)
            elif isinstance(value, list) and listed:
                for index, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    match = _best_match(listed, item)
                    if match:
                        changes += sanitize(match, item, None, f"{here}[{index}]")
            continue

        if origin in (list, set, tuple):
            args = get_args(annotation)
            if not args or not isinstance(value, list):
                continue
            item_type = _unwrap_optional(args[0])
            if _is_model(item_type):
                for index, item in enumerate(value):
                    # Lists have no stable identity across configs, so an element
                    # gets no fallback of its own — field defaults carry it.
                    changes += sanitize(item_type, item, None, f"{here}[{index}]")
            elif _is_enum(item_type):
                kept = []
                for item in value:
                    if _valid(item_type, item):
                        kept.append(item)
                    else:
                        # Dropping beats substituting here: a list is a set of
                        # choices, and inventing one the user never made would be
                        # worse than the entry disappearing.
                        changes.append(f"{here}: dropped unknown entry '{item}'")
                if len(kept) != len(value):
                    data[name] = kept
            continue

        if origin is dict:
            args = get_args(annotation)
            if len(args) != 2 or not isinstance(value, dict):
                continue
            value_type = _unwrap_optional(args[1])
            if _is_model(value_type):
                for key, item in value.items():
                    inner_fallback = sub_fallback.get(key) if isinstance(sub_fallback, dict) else None
                    changes += sanitize(value_type, item, inner_fallback, f"{here}.{key}")

    return changes

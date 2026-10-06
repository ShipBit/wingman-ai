"""Strict decimal and text values shared by ERP domains."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

ZERO = Decimal("0")


def now():
    return datetime.now(timezone.utc).isoformat()


def number(value, *, signed=False, places=2):
    if isinstance(value, bool) or value is None:
        raise ValueError("A finite number is required")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal("1000000000000000"):
            raise ValueError("Number is outside the supported range")
        if not signed and result < 0:
            raise ValueError("Amount must not be negative")
        return result.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, TypeError):
        raise ValueError("A finite number is required") from None


def money(value):
    return format(number(value, signed=True), ".2f")


def quantity(value, *, positive=True):
    value = number(value, places=6)
    if positive and value <= 0:
        raise ValueError("Quantity must be greater than zero")
    return value


def text(value, default="", maximum=500):
    if value is None:
        value = default
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Invalid text value")
    return value.strip()

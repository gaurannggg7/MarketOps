"""Central Decimal market math. All rounding rules for prices and spreads live here.

- Prices are quantized to 4 decimal places (``PRICE_QUANTUM``) with ROUND_HALF_EVEN.
- mid = (bid + ask) / 2, quantized to 6 decimal places.
- spread_bps = ((ask - bid) / mid) * 10_000, quantized to 2 decimal places with ROUND_HALF_EVEN.
- A WIDE_SPREAD rule breaches when the *rounded* spread_bps is strictly greater than the
  threshold; a value exactly equal to the threshold is not a breach.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

PRICE_QUANTUM = Decimal("0.0001")
MID_QUANTUM = Decimal("0.000001")
BPS_QUANTUM = Decimal("0.01")
BPS_FACTOR = Decimal(10_000)


class InvalidQuoteError(ValueError):
    """Raised when a quote violates the positive-price / ask >= bid invariants."""


def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def validate_quote(bid: Decimal, ask: Decimal) -> None:
    if bid <= 0 or ask <= 0:
        raise InvalidQuoteError("prices must be positive")
    if ask < bid:
        raise InvalidQuoteError("ask must be greater than or equal to bid")


def mid_price(bid: Decimal, ask: Decimal) -> Decimal:
    validate_quote(bid, ask)
    return ((bid + ask) / 2).quantize(MID_QUANTUM, rounding=ROUND_HALF_EVEN)


def spread_bps(bid: Decimal, ask: Decimal) -> Decimal:
    validate_quote(bid, ask)
    mid = (bid + ask) / 2
    return ((ask - bid) / mid * BPS_FACTOR).quantize(BPS_QUANTUM, rounding=ROUND_HALF_EVEN)


def spread_breaches(bid: Decimal, ask: Decimal, threshold_bps: Decimal) -> bool:
    return spread_bps(bid, ask) > threshold_bps


def stale_breaches(age_seconds: float, threshold_seconds: Decimal) -> bool:
    """A quote is stale when its backend-receipt age is strictly greater than the threshold."""
    return Decimal(str(age_seconds)) > threshold_seconds


def fmt(value: Decimal) -> str:
    """Decimal → API decimal string without exponent notation."""
    return format(value, "f")

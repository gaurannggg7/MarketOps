from decimal import Decimal

import pytest

from app.services.market_math import (
    InvalidQuoteError,
    mid_price,
    spread_bps,
    spread_breaches,
    stale_breaches,
)


def test_mid_and_spread_use_decimal_rounding() -> None:
    bid, ask = Decimal("100.00"), Decimal("100.10")
    assert mid_price(bid, ask) == Decimal("100.050000")
    # (0.10 / 100.05) * 10000 = 9.99500249... → 10.00
    assert spread_bps(bid, ask) == Decimal("10.00")
    # Exactly 1.245 bps rounds half-even to 1.24 (half-up would give 1.25).
    assert spread_bps(Decimal("199.98755"), Decimal("200.01245")) == Decimal("1.24")


def test_zero_spread_is_allowed() -> None:
    assert spread_bps(Decimal("5"), Decimal("5")) == Decimal("0.00")


@pytest.mark.parametrize(("bid", "ask"), [("0", "1"), ("-1", "1"), ("10", "9.99")])
def test_invalid_quotes_rejected(bid: str, ask: str) -> None:
    with pytest.raises(InvalidQuoteError):
        spread_bps(Decimal(bid), Decimal(ask))


def test_spread_threshold_boundary_is_strict() -> None:
    # bid 99.75, ask 100.25 → mid 100, spread exactly 50.00 bps
    bid, ask = Decimal("99.75"), Decimal("100.25")
    assert spread_bps(bid, ask) == Decimal("50.00")
    assert not spread_breaches(bid, ask, Decimal(50))
    assert spread_breaches(bid, ask, Decimal("49.99"))


def test_stale_threshold_boundary_is_strict() -> None:
    assert not stale_breaches(10.0, Decimal(10))
    assert stale_breaches(10.1, Decimal(10))

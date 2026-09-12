from datetime import datetime, timedelta, timezone

from app.domain import MarketQuote, to_float


def test_to_float_handles_invalid_values() -> None:
    assert to_float("12.5") == 12.5
    assert to_float(None, 7.0) == 7.0
    assert to_float("bad", 3.0) == 3.0


def test_market_quote_stale_detection() -> None:
    fresh = MarketQuote(symbol="AAPL", asset_class="stock", price=200.0)
    assert fresh.is_stale is False

    old = MarketQuote(
        symbol="AAPL",
        asset_class="stock",
        price=200.0,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=6),
    )
    assert old.is_stale is True

import pytest

from app.market import MarketService, YFinanceProvider


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("AAPL", "stock"),
        ("^GSPC", "index"),
        ("GC=F", "commodity"),
        ("BTC-USD", "crypto"),
        ("BTCUSD", "crypto"),
        ("EURUSD", "forex"),
        ("XAUUSD", "metal"),
    ],
)
def test_yfinance_asset_classification(symbol: str, expected: str) -> None:
    assert YFinanceProvider._classify(symbol) == expected


def test_biquote_is_preferred_for_supported_non_stock_symbols() -> None:
    service = MarketService()
    assert service._prefer_biquote("EURUSD") is True
    assert service._prefer_biquote("BTCUSD") is True
    assert service._prefer_biquote("XAUUSD") is True
    assert service._prefer_biquote("AAPL") is False

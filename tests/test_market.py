import pytest

from app.market import YFinanceProvider


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

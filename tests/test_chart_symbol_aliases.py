import pytest

from app.chart_display_symbols import normalise_market_symbol


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BTC", "BTCUSD"),
        ("btc", "BTCUSD"),
        ("BTC/USD", "BTCUSD"),
        ("BTC-USD", "BTCUSD"),
        ("BTCUSD", "BTCUSD"),
        ("ETH", "ETHUSD"),
        ("ETH/USD", "ETHUSD"),
        ("XAU", "XAUUSD"),
        ("XAU/USD", "XAUUSD"),
        ("AAPL", "AAPL"),
    ],
)
def test_normalise_market_symbol(raw: str, expected: str) -> None:
    assert normalise_market_symbol(raw) == expected


def test_normalise_market_symbol_preserves_provider_syntax() -> None:
    assert normalise_market_symbol("^GSPC") == "^GSPC"
    assert normalise_market_symbol("GC=F") == "GC=F"

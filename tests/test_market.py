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

def test_stock_4h_aggregation_uses_regular_session_only() -> None:
    import pandas as pd

    index = pd.to_datetime(
        [
            "2026-09-17 08:30:00+00:00",
            "2026-09-17 13:30:00+00:00",
            "2026-09-17 14:30:00+00:00",
            "2026-09-17 15:30:00+00:00",
            "2026-09-17 16:30:00+00:00",
            "2026-09-17 17:30:00+00:00",
            "2026-09-17 18:30:00+00:00",
            "2026-09-17 19:30:00+00:00",
            "2026-09-17 20:30:00+00:00",
        ]
    )
    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105, 106, 107, 999],
            "High": [100, 101, 102, 103, 104, 105, 106, 107, 999],
            "Low": [100, 101, 102, 103, 104, 105, 106, 107, 999],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 999],
            "Volume": [1, 10, 20, 30, 40, 50, 60, 70, 999],
        },
        index=index,
    )

    result = YFinanceProvider._resample_stock_4h(frame)

    assert result.index.tz is not None
    assert result.index.tz.zone == "UTC"
    assert list(result["Open"]) == [101.0, 105.0]
    assert list(result["Close"]) == [104.0, 107.0]
    assert list(result["Volume"]) == [100.0, 180.0]


import numpy as np
import pandas as pd

from app.indicators import add_advanced_indicators, add_basic_indicators


def sample_ohlcv(rows: int = 60) -> pd.DataFrame:
    close = pd.Series(np.linspace(100, 160, rows), dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.full(rows, 1_000_000.0),
        }
    )


def test_basic_indicators_add_expected_columns() -> None:
    out = add_basic_indicators(sample_ohlcv())
    for column in ["SMA20", "EMA20", "EMA50", "RSI14", "MACD", "MACD_SIGNAL"]:
        assert column in out.columns
    assert out["EMA20"].notna().all()
    assert out["MACD"].notna().all()


def test_advanced_indicators_add_expected_columns() -> None:
    out = add_advanced_indicators(sample_ohlcv())
    for column in ["BB_MID", "BB_UPPER", "BB_LOWER", "ATR14", "STOCH14"]:
        assert column in out.columns
    assert out["BB_UPPER"].iloc[-1] > out["BB_MID"].iloc[-1]
    assert out["BB_LOWER"].iloc[-1] < out["BB_MID"].iloc[-1]
    assert out["ATR14"].iloc[-1] > 0


def test_indicator_functions_do_not_mutate_input() -> None:
    source = sample_ohlcv()
    original = source.copy(deep=True)
    add_basic_indicators(source)
    add_advanced_indicators(source)
    pd.testing.assert_frame_equal(source, original)

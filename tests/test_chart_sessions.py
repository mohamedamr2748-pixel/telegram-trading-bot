import pandas as pd

from app import charts


def _frame():
    idx = pd.date_range("2026-09-11 08:00", periods=5, freq="15min", tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({
        "Open": [100, 101, 102, 103, 104],
        "High": [101, 102, 103, 104, 105],
        "Low": [99, 100, 101, 102, 103],
        "Close": [100, 101, 102, 103, 104],
        "Volume": [1, 1, 1, 1, 1],
    }, index=idx)


def test_display_index_converts_aware_stock_timestamps_to_new_york():
    frame = _frame()
    displayed = charts._display_index(frame.index, "AAPL")
    assert displayed[0].hour == 8
    assert displayed[0].tz is None


def test_regular_session_mask_uses_new_york_time():
    idx = pd.to_datetime([
        "2026-09-11 08:00-04:00",
        "2026-09-11 09:30-04:00",
        "2026-09-11 15:45-04:00",
        "2026-09-11 16:00-04:00",
        "2026-09-11 18:00-04:00",
    ], utc=True)
    mask = charts._regular_session_mask(idx)
    assert mask.tolist() == [False, True, True, False, False]


def test_compressed_positions_are_continuous():
    idx = pd.to_datetime([
        "2026-09-11 08:00-04:00",
        "2026-09-11 09:30-04:00",
        "2026-09-11 16:00-04:00",
        "2026-09-11 16:15-04:00",
    ], utc=True)
    positions = charts._compressed_intraday_positions(idx)
    assert positions == [0.0, 1.0, 2.0, 3.0]

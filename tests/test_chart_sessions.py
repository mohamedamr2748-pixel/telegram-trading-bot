import pandas as pd

from app import charts


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

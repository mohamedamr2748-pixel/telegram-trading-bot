from datetime import date

import pandas as pd

from app import chart_sessions as cs
from app import charts


def test_asset_classification():
    assert cs.classify_asset("AAPL") is cs.AssetKind.US_EQUITY
    assert cs.classify_asset("SP500") is cs.AssetKind.US_EQUITY
    assert cs.classify_asset("^GSPC") is cs.AssetKind.US_EQUITY
    assert cs.classify_asset("BTC-USD") is cs.AssetKind.CRYPTO
    assert cs.classify_asset("USDBTC") is cs.AssetKind.CRYPTO
    assert cs.classify_asset("EURUSD=X") is cs.AssetKind.FOREX
    assert cs.classify_asset("EURUSD", "stock") is cs.AssetKind.FOREX
    assert cs.classify_asset("GC=F") is cs.AssetKind.COMMODITY


def test_est_and_edt_session_frames_are_dst_safe():
    winter = cs.build_us_equity_frame(pd.Timestamp("2026-01-12 12:00", tz="UTC"))
    assert winter.regular_utc == (
        pd.Timestamp("2026-01-12 14:30", tz="UTC"),
        pd.Timestamp("2026-01-12 21:00", tz="UTC"),
    )
    assert winter.x_min_utc == pd.Timestamp("2026-01-12 09:00", tz="UTC")
    assert winter.x_max_utc == pd.Timestamp("2026-01-13 01:00", tz="UTC")

    summer = cs.build_us_equity_frame(pd.Timestamp("2026-07-13 12:00", tz="UTC"))
    assert summer.regular_utc == (
        pd.Timestamp("2026-07-13 13:30", tz="UTC"),
        pd.Timestamp("2026-07-13 20:00", tz="UTC"),
    )
    assert summer.x_min_utc == pd.Timestamp("2026-07-13 08:00", tz="UTC")
    assert summer.x_max_utc == pd.Timestamp("2026-07-14 00:00", tz="UTC")


def test_weekend_uses_previous_weekday():
    frame = cs.build_us_equity_frame(pd.Timestamp("2026-09-12 15:00", tz="UTC"))
    assert frame.trading_date == date(2026, 9, 11)


def test_session_classification():
    frame = cs.build_us_equity_frame(pd.Timestamp("2026-09-11 18:00", tz="UTC"))
    d = frame.trading_date
    assert cs.classify_timestamp(pd.Timestamp("2026-09-11 12:00", tz="UTC"), d) is cs.SessionKind.PREMARKET
    assert cs.classify_timestamp(pd.Timestamp("2026-09-11 14:30", tz="UTC"), d) is cs.SessionKind.REGULAR
    assert cs.classify_timestamp(pd.Timestamp("2026-09-11 20:30", tz="UTC"), d) is cs.SessionKind.REGULAR
    assert cs.classify_timestamp(pd.Timestamp("2026-09-11 21:00", tz="UTC"), d) is cs.SessionKind.AFTERMARKET
    assert cs.classify_timestamp(pd.Timestamp("2026-09-12 00:30", tz="UTC"), d) is cs.SessionKind.CLOSED


def test_non_us_assets_do_not_get_us_frame():
    when = pd.Timestamp("2026-09-11 18:00", tz="UTC")
    assert cs.build_frame("BTC-USD", when) is None
    assert cs.build_frame("EURUSD=X", when) is None
    assert cs.build_frame("GC=F", when) is None


def test_regular_session_mask_uses_centralized_classifier():
    idx = pd.to_datetime([
        "2026-09-11 12:00Z",
        "2026-09-11 13:30Z",
        "2026-09-11 19:45Z",
        "2026-09-11 20:00Z",
        "2026-09-11 23:00Z",
    ], utc=True)
    assert charts._regular_session_mask(idx).tolist() == [False, True, True, True, False]

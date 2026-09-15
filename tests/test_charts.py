import pandas as pd
import pytest

from app import charts


def _series(index, values):
    return pd.DataFrame({"Close": values}, index=index)


def test_price_cleaning_keeps_only_real_observations():
    idx = pd.date_range("2026-09-11 14:30", periods=4, freq="15min", tz="UTC")
    df = _series(idx, [100, 101, 102, 103])
    work = charts._prepare_price_series(df)
    assert len(work) == 4
    assert work.index.max() == idx.max()
    assert work["Close"].iloc[-1] == 103


def test_sub_cent_formatting_never_uses_scientific_notation():
    for value in (1e-2, 1e-4, 1e-6, 1e-8):
        text = charts._fmt_value(value)
        assert "e" not in text.lower()
    assert charts._fmt_value(0.001234) == "0.001234"
    assert charts._fmt_value(12.5) == "12.50"


@pytest.mark.asyncio
async def test_full_day_chart_uses_us_session_frame(monkeypatch):
    idx = pd.date_range("2026-09-11 14:30", periods=4, freq="15min", tz="UTC")
    df = _series(idx, [100, 101, 102, 103])
    captured = {}
    original = charts._configure_us_equity_x_axis

    def spy(ax, frame):
        captured["min"] = frame.x_min_utc
        captured["max"] = frame.x_max_utc
        return original(ax, frame)

    monkeypatch.setattr(charts, "_configure_us_equity_x_axis", spy)
    image = await charts.render_google_finance_chart(df, "AAPL", "1d/15m", prev_close=99, price=103)
    assert image.getbuffer().nbytes > 0
    assert captured["min"] == pd.Timestamp("2026-09-11 08:00", tz="UTC")
    assert captured["max"] == pd.Timestamp("2026-09-12 00:00", tz="UTC")


@pytest.mark.asyncio
async def test_crypto_does_not_use_us_equity_frame(monkeypatch):
    idx = pd.date_range("2026-09-11 00:00", periods=6, freq="4h", tz="UTC")
    df = _series(idx, [50000, 50100, 50200, 50150, 50000, 49900])
    called = False
    original = charts._configure_us_equity_x_axis

    def spy(ax, frame):
        nonlocal called
        called = True
        return original(ax, frame)

    monkeypatch.setattr(charts, "_configure_us_equity_x_axis", spy)
    image = await charts.render_google_finance_chart(df, "BTC-USD", "1d/4h", prev_close=50200, price=49900)
    assert image.getbuffer().nbytes > 0
    assert called is False


@pytest.mark.asyncio
async def test_single_point_chart_does_not_crash():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-09-11 15:00", tz="UTC")])
    image = await charts.render_google_finance_chart(_series(idx, [100]), "AAPL", "1d/15m", prev_close=99, price=100)
    assert image.getbuffer().nbytes > 0


def test_empty_data_raises():
    df = pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([], tz="UTC"))
    with pytest.raises(ValueError):
        charts._prepare_price_series(df)

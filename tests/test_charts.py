import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import pytest

from app import charts
from app.chart_reference_style import configure_observed_bounds
from app.chart_sessions import SessionKind, build_frame, classify_timestamp


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


def test_us_frame_uses_real_observed_bounds():
    idx = pd.date_range("2026-09-11 13:00", periods=44, freq="15min", tz="UTC")
    frame = build_frame("NFE", idx[-1], "stock", observed_index=idx)
    assert frame is not None
    assert frame.x_min_utc == idx[0]
    assert frame.x_max_utc == idx[-1]
    assert frame.premarket_utc[0] == pd.Timestamp("2026-09-11 08:00", tz="UTC")
    assert frame.regular_utc[0] == pd.Timestamp("2026-09-11 13:30", tz="UTC")
    assert frame.aftermarket_utc[0] == pd.Timestamp("2026-09-11 20:00", tz="UTC")


def test_reference_axis_uses_observed_bounds_and_adaptive_utc_ticks():
    idx = pd.date_range("2026-09-11 13:00", periods=44, freq="15min", tz="UTC")
    frame = build_frame("NFE", idx[-1], "stock", observed_index=idx)
    fig, ax = plt.subplots()
    ax._chart_observed_bounds = (idx[0], idx[-1])
    configure_observed_bounds(ax, frame)
    left, right = ax.get_xlim()
    assert left == pytest.approx(mdates.date2num(idx[0].to_pydatetime()))
    assert right == pytest.approx(mdates.date2num(idx[-1].to_pydatetime()))
    assert isinstance(ax.xaxis.get_major_locator(), mdates.AutoDateLocator)
    plt.close(fig)


def test_session_line_colours_extended_hours_gray_regular_hours_red_or_green():
    idx = pd.date_range("2026-09-11 13:00", "2026-09-11 20:30", freq="15min", tz="UTC")
    frame = build_frame("NFE", idx[-1], "stock", observed_index=idx)
    assert frame is not None

    fig, ax = plt.subplots()
    charts._plot_session_coloured_line(
        ax,
        idx,
        [100 + i * 0.1 for i in range(len(idx))],
        frame,
        charts._REGULAR_RED,
        99.0,
    )

    line_colours = {line.get_color().lower() for line in ax.lines}
    assert charts._EXTENDED_GREY.lower() in line_colours
    assert charts._REGULAR_RED.lower() in line_colours

    assert classify_timestamp(pd.Timestamp("2026-09-11 13:15", tz="UTC"), frame.trading_date) is SessionKind.PREMARKET
    assert classify_timestamp(pd.Timestamp("2026-09-11 13:30", tz="UTC"), frame.trading_date) is SessionKind.REGULAR
    assert classify_timestamp(pd.Timestamp("2026-09-11 20:00", tz="UTC"), frame.trading_date) is SessionKind.AFTERMARKET
    plt.close(fig)


def test_session_line_colours_regular_green_for_positive_period():
    idx = pd.date_range("2026-09-11 13:00", "2026-09-11 20:30", freq="15min", tz="UTC")
    frame = build_frame("NFE", idx[-1], "stock", observed_index=idx)
    assert frame is not None

    fig, ax = plt.subplots()
    charts._plot_session_coloured_line(
        ax,
        idx,
        [100 + i * 0.1 for i in range(len(idx))],
        frame,
        charts._REGULAR_GREEN,
        99.0,
    )
    line_colours = {line.get_color().lower() for line in ax.lines}
    assert charts._EXTENDED_GREY.lower() in line_colours
    assert charts._REGULAR_GREEN.lower() in line_colours
    plt.close(fig)


@pytest.mark.asyncio
async def test_full_day_chart_uses_observed_bounds_not_fixed_full_frame(monkeypatch):
    idx = pd.date_range("2026-09-11 13:30", periods=15, freq="15min", tz="UTC")
    df = _series(idx, [100 + i for i in range(len(idx))])
    image = await charts.render_google_finance_chart(df, "SP500", "1d/15m", prev_close=99, price=114)
    assert image.getbuffer().nbytes > 0


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

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


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        ("1M/chart", (1, "m")),
        ("5M/chart", (5, "m")),
        ("15M/chart", (15, "m")),
        ("30M/chart", (30, "m")),
        ("1H/chart", (1, "h")),
        ("4H/chart", (4, "h")),
        ("1D/chart", (1, "d")),
        ("1W/chart", (1, "w")),
        ("1MO/chart", (1, "mo")),
        ("1mo/5m", (5, "m")),
        ("1y/4h", (4, "h")),
    ],
)
def test_timeframe_interval_parses_production_and_legacy_chart_values(timeframe, expected):
    assert charts._timeframe_interval(timeframe) == expected


@pytest.mark.parametrize(
    ("timeframe", "frequency", "periods", "maximum_tick_gap"),
    [
        ("5M/chart", "5min", 120, pd.Timedelta(hours=3)),
        ("4H/chart", "4h", 120, pd.Timedelta(days=5)),
    ],
)
def test_timestamp_ticks_follow_intraday_candle_intervals(timeframe, frequency, periods, maximum_tick_gap):
    idx = pd.date_range("2026-09-01 00:00", periods=periods, freq=frequency, tz="UTC")
    fig, ax = plt.subplots()

    charts._configure_observed_timestamp_ticks(ax, idx, timeframe)

    tick_positions = ax.xaxis.get_majorticklocs()
    tick_times = pd.to_datetime(mdates.num2date(tick_positions), utc=True)
    assert set(tick_times).issubset(set(idx))
    assert 5 <= len(tick_times) <= 9
    assert tick_times.to_series().diff().iloc[1:].max() <= maximum_tick_gap
    plt.close(fig)


@pytest.mark.parametrize(
    ("timeframe", "frequency", "periods", "expected_label"),
    [
        ("1D/chart", "1D", 31, "01 Jan"),
        ("1W/chart", "7D", 12, "Jan"),
        ("1MO/chart", "30D", 12, "2026"),
    ],
)
def test_timestamp_ticks_use_daily_weekly_monthly_label_semantics(timeframe, frequency, periods, expected_label):
    idx = pd.date_range("2026-01-01", periods=periods, freq=frequency, tz="UTC")
    fig, ax = plt.subplots()

    charts._configure_observed_timestamp_ticks(ax, idx, timeframe)

    labels = [label.get_text() for label in ax.get_xticklabels()]
    assert labels
    assert any(expected_label in label for label in labels)
    assert len(labels) <= 9
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


def test_regular_session_performance_ignores_extended_hours_movement():
    idx = pd.to_datetime([
        "2026-09-11 13:15Z",
        "2026-09-11 13:30Z",
        "2026-09-11 19:45Z",
        "2026-09-11 20:00Z",
    ], utc=True)
    frame = build_frame("NFE", idx[-1], "stock", observed_index=idx)
    assert frame is not None

    performance = charts._regular_session_performance(
        idx,
        [105.0, 100.0, 99.0, 120.0],
        frame,
    )

    assert performance == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_us_chart_colour_uses_regular_session_not_aftermarket_price(monkeypatch):
    idx = pd.to_datetime([
        "2026-09-11 13:15Z",
        "2026-09-11 13:30Z",
        "2026-09-11 19:45Z",
        "2026-09-11 20:00Z",
    ], utc=True)
    captured = {}
    original = charts._plot_session_coloured_line

    def spy(ax, index, values, frame, regular_colour, bottom):
        captured["colour"] = regular_colour
        return original(ax, index, values, frame, regular_colour, bottom)

    monkeypatch.setattr(charts, "_plot_session_coloured_line", spy)
    image = await charts.render_google_finance_chart(
        _series(idx, [105.0, 100.0, 99.0, 120.0]),
        "NFE",
        "1d/15m",
        prev_close=105.0,
        price=120.0,
        change_percent=14.29,
    )

    assert image.getbuffer().nbytes > 0
    assert captured["colour"] == charts._REGULAR_RED


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

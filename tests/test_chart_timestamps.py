import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import pytest

from app.chart_timestamps import TIMESTAMP_RULES, configure_price_x_axis, timeframe_key


def test_all_price_buttons_have_timestamp_rules():
    assert set(TIMESTAMP_RULES) == {"1M", "5M", "15M", "30M", "1H", "4H", "1D", "1W", "1MO"}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1M/chart", "1M"),
        ("5M/chart", "5M"),
        ("15M/chart", "15M"),
        ("30M/chart", "30M"),
        ("1H/chart", "1H"),
        ("4H/chart", "4H"),
        ("1D/chart", "1D"),
        ("1W/chart", "1W"),
        ("1MO/chart", "1MO"),
    ],
)
def test_timeframe_key(value, expected):
    assert timeframe_key(value) == expected


def _labels(ax):
    fig = ax.figure
    fig.canvas.draw()
    return [label.get_text() for label in ax.get_xticklabels() if label.get_text()]


def test_intraday_ticks_are_based_on_real_observations_and_show_time():
    idx = pd.date_range("2026-09-17 12:00", periods=120, freq="5min", tz="UTC")
    fig, ax = plt.subplots()
    configure_price_x_axis(ax, "5M/chart", idx)

    tick_values = ax.xaxis.get_major_locator().tick_values(*ax.get_xlim())
    observed_nums = set(mdates.date2num(idx.to_pydatetime()))
    assert set(round(value, 9) for value in tick_values).issubset({round(value, 9) for value in observed_nums})
    assert any(":" in text for text in _labels(ax))
    plt.close(fig)


def test_1d_ticks_use_dates_not_intraday_times():
    idx = pd.date_range("2026-05-01", periods=120, freq="B", tz="UTC")
    fig, ax = plt.subplots()
    configure_price_x_axis(ax, "1D/chart", idx)

    labels = _labels(ax)
    assert labels
    assert all(":" not in text for text in labels)
    assert all(" " in text for text in labels)
    plt.close(fig)


def test_1w_ticks_include_year_to_avoid_ambiguous_dates():
    idx = pd.date_range("2024-01-05", periods=120, freq="W-FRI", tz="UTC")
    fig, ax = plt.subplots()
    configure_price_x_axis(ax, "1W/chart", idx)

    labels = _labels(ax)
    assert labels
    assert any("\n" in text for text in labels)
    assert any("202" in text for text in labels)
    plt.close(fig)


def test_1mo_ticks_use_month_and_year():
    idx = pd.date_range("2017-01-31", periods=120, freq="ME", tz="UTC")
    fig, ax = plt.subplots()
    configure_price_x_axis(ax, "1MO/chart", idx)

    labels = _labels(ax)
    assert labels
    assert all(" " in text for text in labels)
    assert all(":" not in text for text in labels)
    plt.close(fig)

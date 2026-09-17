import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from app import charts


def test_price_timeframe_x_axis_contract():
    idx = pd.date_range("2026-09-17 08:00", periods=8, freq="15min", tz="UTC")
    expected = {
        "1M": "%H:%M",
        "5M": "%d %b\n%H:%M",
        "15M": "%d %b\n%H:%M",
        "30M": "%d %b\n%H:%M",
        "1H": "%d %b\n%H:%M",
        "4H": "%d %b\n%H:%M",
        "1D": "%d %b",
        "1W": "%d %b",
        "1MO": "%b %Y",
    }

    for timeframe, fmt in expected.items():
        fig, ax = plt.subplots()
        charts._configure_price_x_axis(ax, f"{timeframe}/chart", idx)
        assert isinstance(ax.xaxis.get_major_locator(), mdates.AutoDateLocator)
        assert ax.xaxis.get_major_formatter().fmt == fmt
        plt.close(fig)


def test_price_timeframe_key_ignores_renderer_suffix():
    assert charts._timeframe_key("4H/chart") == "4H"
    assert charts._timeframe_key("1MO/chart") == "1MO"
    assert charts._timeframe_key("1D/chart") == "1D"


def test_one_day_price_chart_is_not_treated_as_session_intraday():
    assert charts._is_session_intraday_chart("1D/chart") is False
    assert charts._is_session_intraday_chart("1d/15m") is True

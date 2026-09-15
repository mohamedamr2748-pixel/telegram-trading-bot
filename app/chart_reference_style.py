"""Reference-style intraday chart framing."""
from __future__ import annotations

import matplotlib.dates as mdates
import pandas as pd

from app.chart_sessions import TradingFrame, UTC


def configure_observed_bounds(ax, frame: TradingFrame) -> None:
    """Frame the chart to real observations and use adaptive UTC ticks."""
    observed = getattr(ax, "_chart_observed_bounds", None)
    if observed is None:
        x_min, x_max = frame.x_min_utc, frame.x_max_utc
    else:
        x_min, x_max = observed

    x_min = pd.Timestamp(x_min)
    x_max = pd.Timestamp(x_max)
    if x_min.tzinfo is None:
        x_min = x_min.tz_localize(UTC)
    else:
        x_min = x_min.tz_convert(UTC)
    if x_max.tzinfo is None:
        x_max = x_max.tz_localize(UTC)
    else:
        x_max = x_max.tz_convert(UTC)

    if x_max <= x_min:
        x_max = x_min + pd.Timedelta(minutes=30)

    ax.set_xlim(x_min.to_pydatetime(), x_max.to_pydatetime())
    locator = mdates.AutoDateLocator(minticks=6, maxticks=8, interval_multiples=True)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=UTC))
    ax.xaxis.get_offset_text().set_visible(False)

from __future__ import annotations

from datetime import time

import pandas as pd

_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)


def _should_extend(index: pd.DatetimeIndex) -> bool:
    if len(index) < 2:
        return False
    aware = pd.DatetimeIndex(index)
    if aware.tz is None:
        aware = aware.tz_localize("UTC")
    ny = aware.tz_convert("America/New_York")
    times = ny.time
    # Only extend a live regular-session chart.  If the history already
    # contains post-market data, leave its natural full-day range untouched.
    if times[0] > _REGULAR_OPEN:
        return False
    if times[-1] >= _REGULAR_CLOSE:
        return False
    return all(_REGULAR_OPEN <= value < _REGULAR_CLOSE for value in times)


def install() -> None:
    from app import charts

    if getattr(charts, "_full_day_frame_installed", False):
        return

    original_plot = charts._plot_full_day_continuous
    original_config = charts._configure_full_day_axis

    def plot_full_day_continuous(ax, index, y, regular_color, bottom):
        x = original_plot(ax, index, y, regular_color, bottom)
        if not _should_extend(index):
            return x

        aware = pd.DatetimeIndex(index)
        if aware.tz is None:
            aware = aware.tz_localize("UTC")
        ny = aware.tz_convert("America/New_York")
        interval = pd.Series(ny).diff().dropna().median()
        if pd.isna(interval) or interval <= pd.Timedelta(0):
            return x

        remaining = int(round((pd.Timestamp.combine(ny[-1].date(), _REGULAR_CLOSE) - ny[-1].replace(tzinfo=None)) / interval))
        if remaining > 0:
            x = list(x) + [x[-1] + float(i) for i in range(1, remaining + 1)]
        return x

    def configure_full_day_axis(ax, index, x_positions):
        if not _should_extend(index):
            return original_config(ax, index, x_positions)

        count = len(x_positions)
        if count <= 1:
            return original_config(ax, index, x_positions)

        # The x positions are 15-minute slots beginning at 09:30 New York.
        # Keep the full regular-session frame visible even when the market is
        # still open; future slots contain no fabricated prices.
        tick_indices = list(range(0, count, max(1, round((count - 1) / 6))))
        if tick_indices[-1] != count - 1:
            tick_indices.append(count - 1)
        tick_indices = list(dict.fromkeys(tick_indices))
        start = pd.Timestamp(index[0])
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        start_ny = start.tz_convert("America/New_York")
        labels = [(start_ny + i * (pd.Series(pd.DatetimeIndex(index).tz_convert("America/New_York")).diff().dropna().median() if len(index) > 1 else pd.Timedelta(minutes=15))).strftime("%H:%M") for i in tick_indices]
        ax.set_xticks([x_positions[i] for i in tick_indices])
        ax.set_xticklabels(labels)
        ax.xaxis.get_offset_text().set_visible(False)

    charts._plot_full_day_continuous = plot_full_day_continuous
    charts._configure_full_day_axis = configure_full_day_axis
    charts._full_day_frame_installed = True

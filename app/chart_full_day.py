from __future__ import annotations

from datetime import datetime, time

import pandas as pd


def install() -> None:
    """Keep 1D intraday charts framed across the full US trading session.

    The data remains exactly as returned by the market provider. When the
    market is still open, the future part of the session is simply empty
    space; it is not fabricated. Once extended-hours data exists beyond the
    regular close, the existing chart naturally expands to include it.
    """
    from app import charts

    if getattr(charts, "_chart_full_day_installed", False):
        return

    original_configure = charts._configure_full_day_axis

    def configure_full_day_axis(ax, index, x_positions):
        original_configure(ax, index, x_positions)

        if len(index) <= 1 or len(x_positions) <= 1:
            return

        try:
            timestamps = pd.DatetimeIndex(index)
            if timestamps.tz is None:
                timestamps = timestamps.tz_localize("UTC")
            else:
                timestamps = timestamps.tz_convert("UTC")

            # Only extend a chart that is visibly a short intraday window.
            # Completed days such as a full regular + extended session are
            # left untouched.
            current_right = float(max(x_positions))
            first_utc = timestamps[0]
            first_ny = first_utc.tz_convert("America/New_York")
            close_ny = first_ny.replace(hour=16, minute=0, second=0, microsecond=0)
            close_utc = close_ny.tz_convert("UTC")

            interval = timestamps.to_series().diff().dropna().median()
            if pd.isna(interval) or interval <= pd.Timedelta(0):
                return

            regular_end_position = (close_utc - first_utc) / interval
            regular_end_position = float(regular_end_position)

            # Do not alter charts whose data already reaches/passes regular
            # close. This preserves the established full-day NFE behaviour.
            if regular_end_position <= current_right + 1.0:
                return

            # Give the plot the complete regular-session frame. No future
            # price points are added; only the x-axis is extended.
            left = -0.5
            right = regular_end_position + 0.5
            ax.set_xlim(left, right)

            # Build clean hourly labels across the full regular session.
            tick_times = []
            tick_positions = []
            cursor = first_utc
            while cursor <= close_utc:
                position = float((cursor - first_utc) / interval)
                tick_times.append(cursor)
                tick_positions.append(position)
                cursor += pd.Timedelta(hours=1)

            if tick_times:
                ax.set_xticks(tick_positions)
                ax.set_xticklabels([t.tz_convert("UTC").strftime("%H:%M") for t in tick_times])
                ax.xaxis.get_offset_text().set_visible(False)
        except Exception:
            # Chart rendering must never fail because axis framing is optional.
            return

    charts._configure_full_day_axis = configure_full_day_axis
    charts._chart_full_day_installed = True

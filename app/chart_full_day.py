from __future__ import annotations

from datetime import time

import pandas as pd

_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)


def install() -> None:
    """Frame live 1D/15m US charts across the complete regular session."""
    from app import charts

    if getattr(charts, "_chart_full_day_installed", False):
        return

    original_configure = charts._configure_full_day_axis

    def configure_full_day_axis(ax, index, x_positions):
        # First let the existing UTC axis implementation configure fonts and
        # basic labels. We then replace only the x-range/ticks when the
        # regular session is still in progress.
        original_configure(ax, index, x_positions)

        if len(index) < 2 or len(x_positions) < 2:
            return

        try:
            timestamps = pd.DatetimeIndex(index)
            if timestamps.tz is None:
                timestamps = timestamps.tz_localize("UTC")
            else:
                timestamps = timestamps.tz_convert("UTC")

            ny = timestamps.tz_convert("America/New_York")
            interval = timestamps.to_series().diff().dropna().median()
            if pd.isna(interval) or interval <= pd.Timedelta(0):
                return

            # This layer is used by the 1D full-day renderer for US stocks and
            # indices. Only extend when the current data is still inside the
            # regular session. Never add synthetic price points.
            if ny[0].time() > _REGULAR_OPEN or ny[-1].time() >= _REGULAR_CLOSE:
                return
            if not all(_REGULAR_OPEN <= stamp.time() < _REGULAR_CLOSE for stamp in ny):
                return

            # The compressed x-axis starts at the first real observation.
            # For the normal US 15-minute session this is 09:30 NY, giving
            # 27 slots through 16:00 NY. Calculate the endpoint from the real
            # interval so this also remains correct if the provider changes
            # the intraday interval.
            session_open = ny[0].replace(hour=9, minute=30, second=0, microsecond=0)
            session_close = ny[0].replace(hour=16, minute=0, second=0, microsecond=0)
            if ny[0] != session_open:
                return

            regular_end_position = float((session_close - ny[0]) / interval)
            current_right = float(max(x_positions))
            if regular_end_position <= current_right:
                return

            ax.set_xlim(-0.5, regular_end_position + 0.5)

            # Hourly UTC labels across the complete regular US session.
            tick_positions = []
            tick_labels = []
            cursor = ny[0]
            while cursor <= session_close:
                tick_positions.append(float((cursor - ny[0]) / interval))
                tick_labels.append(cursor.tz_convert("UTC").strftime("%H:%M"))
                cursor += pd.Timedelta(hours=1)

            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels)
            ax.xaxis.get_offset_text().set_visible(False)
        except Exception:
            # Framing is optional and must never break chart rendering.
            return

    charts._configure_full_day_axis = configure_full_day_axis
    charts._chart_full_day_installed = True

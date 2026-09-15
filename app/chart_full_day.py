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
        # labels. The base renderer later calls ax.set_xlim() again, so the
        # full-day endpoint must be enforced at the axes-instance level.
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

            # Only extend a live regular-session chart. Completed sessions and
            # histories containing extended-hours data keep their natural span.
            if ny[0].time() > _REGULAR_OPEN or ny[-1].time() >= _REGULAR_CLOSE:
                return
            if not all(_REGULAR_OPEN <= stamp.time() < _REGULAR_CLOSE for stamp in ny):
                return

            session_open = ny[0].replace(hour=9, minute=30, second=0, microsecond=0)
            session_close = ny[0].replace(hour=16, minute=0, second=0, microsecond=0)
            if ny[0] != session_open:
                return

            regular_end_position = float((session_close - ny[0]) / interval)
            current_right = float(max(x_positions))
            if regular_end_position <= current_right:
                return

            # charts.py calls ax.set_xlim(x_positions[0], x_positions[-1])
            # after this function returns. Override only this axes instance so
            # that call cannot collapse the chart back to the latest point.
            original_set_xlim = ax.set_xlim
            state = {"applied": False}

            def set_xlim_full_day(*args, **kwargs):
                if not state["applied"]:
                    state["applied"] = True
                    return original_set_xlim(-0.5, regular_end_position + 0.5)
                return original_set_xlim(*args, **kwargs)

            ax.set_xlim = set_xlim_full_day

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

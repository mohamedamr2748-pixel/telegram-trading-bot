from __future__ import annotations

import pandas as pd


def _utc_display_index(index: pd.DatetimeIndex, symbol: str) -> pd.DatetimeIndex:
    """Keep all user-facing chart timestamps in UTC."""
    work = pd.DatetimeIndex(index)
    if getattr(work, "tz", None) is None:
        return work.tz_localize("UTC")
    return work.tz_convert("UTC")


def _configure_full_day_axis_utc(ax, index: pd.DatetimeIndex, x_positions: list[float]) -> None:
    """Use UTC labels on the compressed full-day chart axis."""
    if len(index) <= 1:
        ax.set_xticks(x_positions)
        return
    count = min(8, len(index))
    sample = [round(i * (len(index) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    sample = list(dict.fromkeys(sample))
    ax.set_xticks([x_positions[i] for i in sample])
    labels = []
    for i in sample:
        stamp = pd.Timestamp(index[i])
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        labels.append(stamp.tz_convert("UTC").strftime("%H:%M"))
    ax.set_xticklabels(labels)
    ax.xaxis.get_offset_text().set_visible(False)


def install() -> None:
    """Patch the existing chart renderer so user-facing chart times are UTC."""
    from app import charts
    charts._display_index = _utc_display_index
    charts._configure_full_day_axis = _configure_full_day_axis_utc

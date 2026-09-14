from __future__ import annotations

import asyncio

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


async def _render_with_utc_axis_labels(original_render, *args, **kwargs):
    """Render charts with time-of-day labels for intraday and date labels otherwise."""
    timeframe = str(args[2] if len(args) > 2 else kwargs.get("timeframe", ""))
    upper = timeframe.upper()
    intraday = upper.startswith("1D") or upper.startswith("5D")

    from app import charts

    original_formatter = charts.mdates.DateFormatter
    if not intraday:
        def date_formatter(fmt, *formatter_args, **formatter_kwargs):
            if fmt == "%H:%M":
                fmt = "%b %Y"
            return original_formatter(fmt, *formatter_args, **formatter_kwargs)
        charts.mdates.DateFormatter = date_formatter
    try:
        return await original_render(*args, **kwargs)
    finally:
        if not intraday:
            charts.mdates.DateFormatter = original_formatter


async def _locked_render(original_render, lock, *args, **kwargs):
    async with lock:
        return await _render_with_utc_axis_labels(original_render, *args, **kwargs)


def install() -> None:
    """Patch the existing chart renderer so user-facing chart times are UTC."""
    from app import charts

    charts._display_index = _utc_display_index
    charts._configure_full_day_axis = _configure_full_day_axis_utc

    if getattr(charts, "_utc_axis_labels_installed", False):
        return

    original_render = charts.render_google_finance_chart
    lock = asyncio.Lock()

    async def render_with_utc_labels(*args, **kwargs):
        return await _locked_render(original_render, lock, *args, **kwargs)

    charts.render_google_finance_chart = render_with_utc_labels
    charts._utc_axis_labels_installed = True

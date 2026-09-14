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
    """Render charts with UTC labels and selected-period performance colour."""
    df = args[0] if args else kwargs.get("df")
    timeframe = str(args[2] if len(args) > 2 else kwargs.get("timeframe", ""))
    upper = timeframe.upper()
    intraday = upper.startswith("1D") or upper.startswith("5D")

    # For longer ranges, the chart line/headline must reflect the selected
    # period rather than today's move. The existing renderer derives its
    # colour from price / previous_close, so temporarily make that previous
    # close equal to the first close in the selected range. This preserves the
    # real current price and all market metadata while changing only the
    # performance reference used by the chart renderer.
    original_correct_previous = None
    if isinstance(df, pd.DataFrame) and not intraday and "Close" in df.columns:
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if not close.empty:
            period_start = float(close.iloc[0])
            kwargs["prev_close"] = period_start

            from app import charts
            original_correct_previous = charts._correct_yfinance_previous_close

            async def _period_start_previous(symbol, quote, frame):
                if not str(frame).upper().startswith("1D"):
                    return period_start
                return await original_correct_previous(symbol, quote, frame)

            charts._correct_yfinance_previous_close = _period_start_previous

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
        if original_correct_previous is not None:
            charts._correct_yfinance_previous_close = original_correct_previous
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

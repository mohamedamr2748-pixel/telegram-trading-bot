from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import FixedFormatter, FixedLocator

from app import _legacy_charts as legacy
from app.chart_sessions import TradingFrame, UTC, build_frame
from app.domain import MarketQuote

_CANDLE_UP = "#55e982"
_CANDLE_DOWN = "#f26b63"
_NEUTRAL = "#9aa0a6"
_GRID = "#34373b"
_BG = "#202124"
# PRO_CHART_V2


def _display_ticks(index: pd.DatetimeIndex, timeframe: str) -> tuple[pd.DatetimeIndex, list[str]]:
    observed = legacy._display_index(index, "")
    if not len(observed):
        return observed, []
    observed = observed.drop_duplicates().sort_values()
    count, unit = legacy._timeframe_interval(timeframe)

    if (unit == "m" and count in {15, 30}) or (unit == "h" and count in {1, 4}):
        # Intraday labels must refer to real observed candles. We deliberately
        # do not create synthetic timestamps for missing market periods.
        tick_count = min(7, len(observed))
        if tick_count == 1:
            ticks = pd.DatetimeIndex([observed[0]])
        else:
            positions = [round(i * (len(observed) - 1) / (tick_count - 1)) for i in range(tick_count)]
            ticks = pd.DatetimeIndex([observed[position] for position in positions])

        if count == 4 and unit == "h":
            # 4H stock charts are rendered on compact candle slots, so repeated
            # clock labels from different sessions can become visually confusing.
            # Keep the candle positions untouched, but choose a label set with
            # unique clock values whenever the selected ticks permit it.
            unique_ticks = []
            seen_labels = set()
            for timestamp in ticks:
                label = timestamp.strftime("%H:%M")
                if label not in seen_labels:
                    unique_ticks.append(timestamp)
                    seen_labels.add(label)
            if len(unique_ticks) >= 4:
                ticks = pd.DatetimeIndex(unique_ticks)
            labels = [timestamp.strftime("%H:%M") for timestamp in ticks]
        else:
            span = ticks[-1] - ticks[0]
            date_format = "%d %b\n%H:%M" if span >= pd.Timedelta(days=2) else "%H:%M"
            labels = [timestamp.strftime(date_format) for timestamp in ticks]
        return ticks, labels

    step = legacy._timestamp_tick_step(timeframe, observed[-1] - observed[0])
    ticks = [observed[0]]
    next_target = observed[0] + step
    for timestamp in observed[1:]:
        if timestamp >= next_target:
            ticks.append(timestamp)
            next_target = timestamp + step
    if ticks[-1] != observed[-1]:
        ticks.append(observed[-1])
    ticks = pd.DatetimeIndex(ticks)
    if len(ticks) <= 1:
        return ticks, [ticks[0].strftime("%H:%M")] if len(ticks) else []
    span = ticks[-1] - ticks[0]
    if unit == "mo":
        date_format = "%b %Y"
    else:
        date_format = "%b %Y" if span >= pd.Timedelta(days=365) else "%d %b"
    return ticks, [timestamp.strftime(date_format) for timestamp in ticks]


def _candle_width_days(index: pd.DatetimeIndex, timeframe: str) -> float:
    count, unit = legacy._timeframe_interval(timeframe)
    base_days = count * {
        "m": 1.0 / (24.0 * 60.0),
        "h": 1.0 / 24.0,
        "d": 1.0,
        "w": 7.0,
        "wk": 7.0,
        "mo": 30.0,
    }[unit]
    if len(index) > 1:
        values = pd.DatetimeIndex(index).asi8
        gaps = (values[1:] - values[:-1]) / 86_400_000_000_000
        positive = gaps[gaps > 0]
        if len(positive):
            base_days = min(base_days, float(pd.Series(positive).median()))
    return max(base_days * 0.72, 1.0 / (24.0 * 60.0) * 0.55)


def _plot_candles(ax, work: pd.DataFrame, timeframe: str, compact: bool = False) -> None:
    ohlc = work[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()
    if ohlc.empty:
        return
    width = 0.72 if compact else _candle_width_days(ohlc.index, timeframe)
    x_values = list(range(len(ohlc))) if compact else mdates.date2num(ohlc.index.to_pydatetime())
    for x_value, row in zip(x_values, ohlc.itertuples(index=False)):
        opening, high, low, close = map(float, row)
        candle_colour = _CANDLE_UP if close >= opening else _CANDLE_DOWN
        ax.vlines(x_value, low, high, color=candle_colour, linewidth=1.1, alpha=0.95, zorder=4)
        body_bottom = min(opening, close)
        body_height = abs(close - opening)
        if body_height <= 0:
            ax.hlines(close, x_value - width * 0.38, x_value + width * 0.38, color=candle_colour, linewidth=2.0, zorder=5)
            continue
        ax.add_patch(
            Rectangle(
                (x_value - width / 2.0, body_bottom),
                width,
                body_height,
                facecolor=candle_colour,
                edgecolor=candle_colour,
                linewidth=0.65,
                zorder=5,
            )
        )


def _plot_volume(ax, work: pd.DataFrame, timeframe: str, compact: bool = False) -> None:
    if "Volume" not in work.columns:
        return
    volume = pd.to_numeric(work["Volume"], errors="coerce").fillna(0)
    if not (volume > 0).any():
        return
    width = (0.82 if compact else _candle_width_days(work.index, timeframe) * 0.82)
    x_values = list(range(len(work))) if compact else mdates.date2num(work.index.to_pydatetime())
    for x_value, row in zip(x_values, work[["Open", "Close", "Volume"]].itertuples(index=False)):
        opening, close, amount = map(float, row)
        if amount <= 0:
            continue
        candle_colour = _CANDLE_UP if close >= opening else _CANDLE_DOWN
        ax.bar(x_value, amount, width=width, align="center", color=candle_colour, alpha=0.38, edgecolor="none", linewidth=0, zorder=2)
    ax.text(0.0, 0.88, "Volume", transform=ax.transAxes, ha="left", va="top", fontsize=7.8, color="#8f96a3")


def _configure_x_axis(
    ax,
    index: pd.DatetimeIndex,
    timeframe: str,
    visible_bounds: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    compact: bool = False,
) -> None:
    observed = legacy._display_index(index, "")
    if visible_bounds is not None:
        lower, upper = visible_bounds
        observed = observed[(observed >= lower) & (observed <= upper)]
    ticks, labels = _display_ticks(observed, timeframe)
    if not len(ticks):
        return
    if compact:
        positions = observed.get_indexer(ticks)
        positions = [int(position) for position in positions if position >= 0]
    else:
        positions = mdates.date2num(ticks.to_pydatetime())
    ax.xaxis.set_major_locator(FixedLocator(positions))
    ax.xaxis.set_major_formatter(FixedFormatter(labels[:len(positions)]))
    ax.xaxis.get_offset_text().set_visible(False)


async def render_google_finance_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
    quote: MarketQuote | None = None,
) -> io.BytesIO:
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        return await legacy.render_google_finance_chart(
            df,
            symbol,
            timeframe,
            prev_close=prev_close,
            price=price,
            currency=currency,
            change_percent=change_percent,
            quote=quote,
        )

    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True, errors="coerce")
    work = work[work.index.notna()].sort_index()
    work = work[~work.index.duplicated(keep="last")]
    work[["Open", "High", "Low", "Close"]] = work[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce")
    work = work.dropna(subset=["Open", "High", "Low", "Close"])
    if "Volume" in work.columns:
        work["Volume"] = pd.to_numeric(work["Volume"], errors="coerce").fillna(0)
    if work.empty:
        raise ValueError("No valid OHLC data available for chart")
    if len(work) > 2500:
        work = work.iloc[-2500:]

    if quote is None and (prev_close is None or price is None or change_percent is None):
        try:
            from app.market import MarketService
            quote = await MarketService().get_quote(symbol)
        except Exception:
            quote = None

    if quote is not None:
        price = quote.price if price is None else price
        currency = currency or ("USD" if quote.asset_class in {"stock", "index", "commodity", "metal", "forex", "market"} else None)
        if prev_close is None and quote.previous_close is not None:
            prev_close = quote.previous_close
        if prev_close and prev_close > 0 and price is not None:
            change_percent = (price / prev_close - 1.0) * 100.0
        elif change_percent is None:
            change_percent = quote.change_percent

    # Treat 1D as the daily candle interval used by /price. Only a true
    # intraday 1-day chart such as 1d/15m should use the US-session frame.
    interval_count, interval_unit = legacy._timeframe_interval(timeframe)
    is_1d = timeframe.upper().startswith("1D") and interval_unit in {"m", "h"}
    is_daily_candles = interval_count == 1 and interval_unit == "d"
    frame: TradingFrame | None = build_frame(
        symbol,
        work.index[-1],
        quote.asset_class if quote else None,
        observed_index=work.index,
    ) if is_1d else None
    trading_date_iso = frame.trading_date.isoformat() if frame and frame.trading_date else None

    if quote is not None and quote.source == "yfinance" and is_1d:
        corrected_previous = await legacy._correct_yfinance_previous_close(symbol, quote, timeframe, trading_date_iso)
        if corrected_previous is not None:
            prev_close = corrected_previous
            if price is not None and prev_close > 0:
                change_percent = (price / prev_close - 1.0) * 100.0

    last_price = float(price) if price is not None else float(work["Close"].iloc[-1])
    previous = float(prev_close) if prev_close and prev_close > 0 else None
    first_close = float(work["Close"].iloc[0])
    if is_1d:
        if change_percent is None and previous:
            change_percent = (last_price / previous - 1.0) * 100.0
        elif change_percent is None and first_close > 0 and len(work) >= 2:
            change_percent = (last_price / first_close - 1.0) * 100.0
    else:
        if first_close > 0:
            change_percent = (last_price / first_close - 1.0) * 100.0
        # Keep the existing chart baseline for intraday/historical views. For
        # the daily candle button, retain the quote's real previous close when
        # available instead of relabelling the first historical candle as
        # "Prev close". This changes no candle data.
        if is_daily_candles and prev_close is not None and prev_close > 0:
            previous = float(prev_close)
        else:
            previous = first_close

    compact_x = frame is None and ((interval_unit == "m" and interval_count in {15, 30}) or (interval_unit == "h" and interval_count in {1, 4}))
    period_perf = legacy._period_performance(work["Close"], timeframe, change_percent)
    regular_perf = legacy._regular_session_performance(work.index, work["Close"], frame) if frame is not None else None
    colour_perf = regular_perf if frame is not None else period_perf
    session_colour = legacy._REGULAR_GREEN if colour_perf is not None and colour_perf > 1e-12 else legacy._REGULAR_RED if colour_perf is not None and colour_perf < -1e-12 else _NEUTRAL
    stats = legacy._regular_session_stats(work, frame, symbol) if frame is not None else legacy._session_stats(work, symbol)
    digits = legacy._price_digits(symbol, quote)
    currency_text = f" {currency}" if currency else ""

    fig = plt.figure(figsize=legacy._STANDARD_FIGSIZE, dpi=legacy._STANDARD_DPI, facecolor=_BG)
    has_volume = "Volume" in work.columns and bool((pd.to_numeric(work["Volume"], errors="coerce").fillna(0) > 0).any())
    if has_volume:
        ax = fig.add_axes([0.035, 0.39, 0.865, 0.47])
        volume_ax = fig.add_axes([0.035, 0.30, 0.865, 0.075], sharex=ax)
        volume_ax.set_facecolor(_BG)
        volume_ax.tick_params(axis="y", left=False, labelleft=False, right=False, labelright=False, length=0)
        for spine in volume_ax.spines.values():
            spine.set_visible(False)
        volume_ax.grid(axis="y", color=_GRID, linestyle="-", linewidth=0.5, alpha=0.35)
    else:
        ax = fig.add_axes([0.035, 0.30, 0.865, 0.56])
        volume_ax = None
    ax.set_facecolor(_BG)

    low_series = work["Low"].to_numpy(dtype=float)
    high_series = work["High"].to_numpy(dtype=float)
    baseline = float(min(low_series.min(), previous if previous is not None else low_series.min(), last_price))
    ceiling = float(max(high_series.max(), previous if previous is not None else high_series.max(), last_price))
    spread = ceiling - baseline
    padding = max(spread * 0.22, abs(last_price) * 0.0025, 0.01)
    chart_bottom, chart_top = baseline - padding, ceiling + padding

    if frame is not None:
        legacy._draw_session_bands(ax, frame, session_colour)
    _plot_candles(ax, work, timeframe, compact=compact_x)
    if volume_ax is not None:
        _plot_volume(volume_ax, work, timeframe, compact=compact_x)

    if previous is not None:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (5, 6)), color="#e4e7eb", alpha=0.85, zorder=2)
        ax.text(1.002, previous, f"Prev close\n{legacy._fmt_value(previous, digits)}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.5, color="#d5d8de", linespacing=1.08)

    ax.axhline(last_price, linewidth=0.9, linestyle=(0, (2, 4)), color=session_colour, alpha=0.72, zorder=3)
    ax.text(1.002, last_price, legacy._fmt_value(last_price, digits), transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.5, color=session_colour)

    ax.set_ylim(chart_bottom, chart_top)
    ax.grid(axis="y", color=_GRID, linestyle="-", linewidth=0.65, alpha=0.75)
    ax.grid(axis="x", color=_GRID, linestyle="--", linewidth=0.55, alpha=0.55)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#d7dbe2", labelsize=8.5, length=0, pad=8)
    ax.yaxis.tick_right()

    tick_ax = volume_ax if volume_ax is not None else ax
    if frame is not None:
        xmin = mdates.date2num(frame.x_min_utc.to_pydatetime())
        xmax = mdates.date2num(frame.x_max_utc.to_pydatetime())
        ax.set_xlim(xmin, xmax)
        _configure_x_axis(tick_ax, work.index, timeframe, visible_bounds=(frame.x_min_utc, frame.x_max_utc))
    else:
        if compact_x:
            ax.set_xlim(-0.85, max(len(work) - 0.15, 0.85))
        else:
            x = work.index.to_pydatetime()
            if len(x) > 1:
                ax.set_xlim(x[0], x[-1])
        _configure_x_axis(tick_ax, work.index, timeframe, compact=compact_x)
    if volume_ax is not None:
        ax.tick_params(axis="x", labelbottom=False)

    price_line = f"{legacy._fmt_value(last_price, digits)}{currency_text}"
    if period_perf is not None:
        price_line += f"  {period_perf:+.2f}%"
    ax.text(0.0, 1.19, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", fontsize=20, fontweight="bold", color="#f8fafc")
    ax.text(0.0, 1.065, price_line, transform=ax.transAxes, ha="left", va="bottom", fontsize=18, fontweight="bold", color=session_colour if period_perf is not None else "#f8fafc")

    display_timeframe = timeframe.split("/", 1)[0].strip().upper()
    chart_date = work.index[-1].tz_convert(UTC).strftime("%Y-%b-%d")
    ax.text(0.985, 1.18, f"{display_timeframe}/Chart • UTC • {chart_date}", transform=ax.transAxes, ha="right", va="center", fontsize=9.5, fontweight="bold", color="#cfd4dc")

    fig.add_artist(plt.Line2D([0.035, 0.93], [0.262, 0.262], transform=fig.transFigure, color="#34373b", linewidth=0.9))

    rows = legacy._asset_stats_rows(symbol, quote, stats, period_perf)
    y_positions = [0.225, 0.182, 0.139]
    x_positions_text = [0.055, 0.36, 0.66]
    for ypos, row in zip(y_positions, rows):
        for xpos, (label, value) in zip(x_positions_text, row):
            fig.text(xpos, ypos, label, ha="left", va="center", fontsize=9.0, color="#9aa0a6")
            fig.text(xpos + 0.10, ypos, value, ha="left", va="center", fontsize=10.0, fontweight="bold", color="#f8fafc")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=legacy._STANDARD_DPI, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf


async def render_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    advanced: bool = False,
    *,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
    quote: MarketQuote | None = None,
) -> io.BytesIO:
    if advanced:
        return await legacy.render_chart(
            df,
            symbol,
            timeframe,
            advanced=True,
            prev_close=prev_close,
            price=price,
            currency=currency,
            change_percent=change_percent,
            quote=quote,
        )
    return await render_google_finance_chart(
        df,
        symbol,
        timeframe,
        prev_close=prev_close,
        price=price,
        currency=currency,
        change_percent=change_percent,
        quote=quote,
    )

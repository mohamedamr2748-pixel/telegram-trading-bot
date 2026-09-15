from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

import app.charts as charts


_BODY_UP = "#55e982"
_BODY_DOWN = "#f26b63"
_EXTENDED = "#9aa0a6"
_BG = "#202124"
_GRID = "#34373b"
_TEXT = "#f8fafc"
_MUTED = "#9aa0a6"


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Chart requires OHLC data: missing {', '.join(missing)}")
    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    keep = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in work.columns]
    work = work[keep].apply(pd.to_numeric, errors="coerce")
    work = work.dropna(subset=required)
    work = work[~work.index.duplicated(keep="last")].sort_index()
    if work.empty:
        raise ValueError("No valid OHLC data available for chart")
    if "Volume" in work.columns:
        work["Volume"] = work["Volume"].fillna(0)
    return work


def _is_1d_us(symbol: str, quote, timeframe: str) -> bool:
    return charts._is_full_day_us_intraday(symbol, quote, timeframe)


def _regular_mask(index: pd.DatetimeIndex) -> pd.Series:
    return charts._regular_session_mask(index)


def _compressed_x(index: pd.DatetimeIndex, compact: bool) -> list[float]:
    if compact:
        return [float(i) for i in range(len(index))]
    return mdates.date2num(index.tz_convert("UTC").tz_localize(None).to_pydatetime())


def _candle_width(x: list[float], compact: bool) -> float:
    if len(x) <= 1:
        return 0.45 if compact else 0.02
    spacings = [x[i + 1] - x[i] for i in range(len(x) - 1) if x[i + 1] > x[i]]
    spacing = min(spacings) if spacings else 1.0
    return spacing * (0.62 if compact else 0.58)


def _draw_candles(ax, x: list[float], frame: pd.DataFrame, compact: bool, regular: pd.Series | None = None) -> None:
    width = _candle_width(x, compact)
    spread = max(float(frame["High"].max() - frame["Low"].min()), 1e-9)
    min_height = max(spread * 0.0012, 0.005)
    for i, (_, row) in enumerate(frame.iterrows()):
        open_ = float(row["Open"])
        close = float(row["Close"])
        high = float(row["High"])
        low = float(row["Low"])
        base_colour = _BODY_UP if close >= open_ else _BODY_DOWN
        colour = base_colour if regular is None or bool(regular.iloc[i]) else _EXTENDED
        ax.vlines(x[i], low, high, color=colour, linewidth=1.15, zorder=4, antialiased=True)
        body_bottom = min(open_, close)
        body_height = max(abs(close - open_), min_height)
        ax.add_patch(
            Rectangle(
                (x[i] - width / 2, body_bottom),
                width,
                body_height,
                facecolor=colour,
                edgecolor=colour,
                linewidth=0.55,
                zorder=5,
            )
        )


def _draw_volume(ax, x: list[float], frame: pd.DataFrame, compact: bool, regular: pd.Series | None = None) -> None:
    if "Volume" not in frame.columns:
        ax.set_visible(False)
        return
    width = _candle_width(x, compact) * 0.82
    volume = frame["Volume"].to_numpy(dtype=float)
    max_volume = float(volume.max()) if len(volume) else 0.0
    for i, value in enumerate(volume):
        base_colour = _BODY_UP if float(frame["Close"].iloc[i]) >= float(frame["Open"].iloc[i]) else _BODY_DOWN
        colour = base_colour if regular is None or bool(regular.iloc[i]) else _EXTENDED
        ax.bar(x[i], value, width=width, color=colour, alpha=0.45, align="center", zorder=2)
    ax.set_ylim(0, max(max_volume * 1.18, 1.0))
    ax.set_yticks([])
    ax.grid(False)


def _axis_labels(ax, frame: pd.DataFrame, x: list[float], compact: bool) -> None:
    if len(x) <= 1:
        ax.set_xticks(x)
        return
    count = min(8, len(x))
    sample = [round(i * (len(x) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    sample = list(dict.fromkeys(sample))
    ticks = [x[i] for i in sample]
    ax.set_xticks(ticks)
    labels = [
        pd.Timestamp(frame.index[i]).tz_convert("UTC").strftime("%H:%M" if compact else "%d %b")
        for i in sample
    ]
    ax.set_xticklabels(labels)
    ax.tick_params(axis="x", colors="#d7dbe2", labelsize=8.5, length=0, pad=8)


def _limits(frame: pd.DataFrame, previous: float | None) -> tuple[float, float]:
    low = float(frame["Low"].min())
    high = float(frame["High"].max())
    if previous is not None:
        low = min(low, previous)
        high = max(high, previous)
    spread = high - low
    padding = max(spread * 0.18, abs(high) * 0.0025, 0.01)
    return low - padding, high + padding


async def render_enhanced_google_finance_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
    quote=None,
) -> io.BytesIO:
    frame = _prepare_ohlcv(df)
    if len(frame) > 2500:
        frame = frame.iloc[-2500:]

    if quote is None and (prev_close is None or price is None or change_percent is None):
        try:
            from app.market import MarketService
            quote = await MarketService().get_quote(symbol)
        except Exception:
            quote = None

    if quote is not None:
        price = quote.price if price is None else price
        currency = currency or ("USD" if quote.asset_class in {"stock", "index", "commodity", "metal", "forex", "market"} else None)
        corrected_previous = await charts._correct_yfinance_previous_close(symbol, quote, timeframe)
        if prev_close is None or quote.source == "yfinance":
            prev_close = corrected_previous
        if prev_close and prev_close > 0:
            change_percent = ((price if price is not None else quote.price) / prev_close - 1.0) * 100.0
        elif change_percent is None:
            change_percent = quote.change_percent

    last_price = price if price is not None else float(frame["Close"].iloc[-1])
    previous = prev_close if prev_close and prev_close > 0 else None
    if change_percent is None and previous:
        change_percent = (last_price / previous - 1.0) * 100.0
    period_perf = charts._period_performance(frame["Close"], timeframe, change_percent)
    compact = _is_1d_us(symbol, quote, timeframe)
    regular = _regular_mask(frame.index) if compact else None
    stats = charts._regular_session_stats(frame, symbol) if compact else charts._session_stats(frame, symbol)
    digits = charts._price_digits(symbol, quote)
    currency_text = f" {currency}" if currency else ""

    fig = plt.figure(figsize=(16.0, 8.8), dpi=240, facecolor=_BG)
    ax = fig.add_axes([0.035, 0.34, 0.865, 0.49])
    vol_ax = fig.add_axes([0.035, 0.275, 0.865, 0.05], sharex=ax)
    ax.set_facecolor(_BG)
    vol_ax.set_facecolor(_BG)

    x = _compressed_x(frame.index, compact)
    chart_bottom, chart_top = _limits(frame, previous)
    _draw_candles(ax, x, frame, compact, regular)
    _draw_volume(vol_ax, x, frame, compact, regular)

    line_colour = _BODY_UP if (change_percent is not None and change_percent > 0) else _BODY_DOWN if (change_percent is not None and change_percent < 0) else _EXTENDED
    if previous is not None:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (5, 6)), color="#e4e7eb", alpha=0.78, zorder=2)
        ax.text(1.002, previous, f"Prev close\n{previous:.{digits}f}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.5, color="#d5d8de", linespacing=1.08)

    latest_colour = line_colour if regular is None else (line_colour if bool(regular.iloc[-1]) else _EXTENDED)
    ax.scatter([x[-1]], [last_price], s=48, color=latest_colour, edgecolor=_BG, linewidth=1.4, zorder=7)
    ax.set_ylim(chart_bottom, chart_top)
    ax.grid(axis="y", color=_GRID, linestyle="-", linewidth=0.65, alpha=0.75)
    ax.grid(axis="x", color=_GRID, linestyle="--", linewidth=0.50, alpha=0.50)
    for axis in (ax, vol_ax):
        for spine in axis.spines.values():
            spine.set_visible(False)
    ax.tick_params(axis="y", colors="#d7dbe2", labelsize=8.5, length=0, pad=8)
    ax.yaxis.tick_right()
    vol_ax.tick_params(axis="y", length=0, labelleft=False, labelright=False)
    _axis_labels(vol_ax, frame, x, compact)
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.set_xlim(x[0], x[-1])

    price_line = f"{last_price:.{digits}f}{currency_text}"
    if change_percent is not None:
        price_line += f"  {change_percent:+.2f}%"
    ax.text(0.0, 1.21, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", fontsize=20, fontweight="bold", color=_TEXT)
    ax.text(0.0, 1.075, price_line, transform=ax.transAxes, ha="left", va="bottom", fontsize=18, fontweight="bold", color=line_colour)
    ax.text(0.0, 0.99, "Candles  •  Volume", transform=ax.transAxes, ha="left", va="top", fontsize=8.5, color=_MUTED)

    selector = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y"]
    selected = charts._selector_key(timeframe)
    start_x = 0.67
    step = 0.047
    for idx, item in enumerate(selector):
        xpos = start_x + idx * step
        ax.text(xpos, 1.19, item, transform=ax.transAxes, ha="center", va="center", fontsize=10.5, fontweight="bold" if item == selected else "normal", color=_TEXT if item == selected else "#c7ccd4")

    chart_date = pd.Timestamp(frame.index[-1]).tz_convert("UTC").strftime("%Y-%b-%d")
    ax.text(1.0, -0.10, chart_date, transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#b9bec7")
    ax.text(1.0, -0.14, timeframe.upper(), transform=ax.transAxes, ha="right", va="top", color="#b8bdc7", fontsize=8.0, fontweight="bold")

    fig.add_artist(plt.Line2D([0.035, 0.93], [0.292, 0.292], transform=fig.transFigure, color=_GRID, linewidth=0.9))
    rows = charts._asset_stats_rows(symbol, quote, stats, period_perf if not timeframe.upper().startswith("1D") else change_percent)
    y_positions = [0.25, 0.207, 0.164]
    x_positions_text = [0.055, 0.36, 0.66]
    for ypos, row in zip(y_positions, rows):
        for xpos, (label, value) in zip(x_positions_text, row):
            fig.text(xpos, ypos, label, ha="left", va="center", fontsize=9.0, color=_MUTED)
            fig.text(xpos + 0.10, ypos, value, ha="left", va="center", fontsize=10.0, fontweight="bold", color=_TEXT)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=240, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf


def install() -> None:
    charts.render_google_finance_chart = render_enhanced_google_finance_chart

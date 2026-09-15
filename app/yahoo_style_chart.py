from __future__ import annotations

import io
from datetime import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

from app.domain import MarketQuote


_BG = "#202124"
_GRID = "#34373b"
_TEXT = "#f8fafc"
_MUTED = "#aeb4bd"
_GREEN = "#22c55e"
_RED = "#ef6a64"
_EXTENDED = "#8f969f"
_PREV = "#d9dde3"

_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required OHLC columns: {', '.join(missing)}")
    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    for column in required + (["Volume"] if "Volume" in work.columns else []):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=required).sort_index()
    work = work[~work.index.duplicated(keep="last")]
    if work.empty:
        raise ValueError("No valid OHLC data available for chart")
    if "Volume" not in work.columns:
        work["Volume"] = 0.0
    work["Volume"] = work["Volume"].fillna(0.0)
    return work


def _fmt_price(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    if abs(value) >= 1:
        return f"{value:.{digits}f}"
    return f"{value:.{max(digits, 4)}f}"


def _fmt_volume(value: float | None) -> str:
    if value is None:
        return "n/a"
    value = float(value)
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _digits(symbol: str, quote: MarketQuote | None) -> int:
    asset = (quote.asset_class if quote else "").lower()
    normalized = symbol.upper().replace("/", "").replace("-", "")
    if asset == "forex" or normalized in {
        "EURUSD", "USDEUR", "GBPUSD", "USDGBP", "USDJPY", "JPYUSD",
        "AUDUSD", "USDAUD", "AUUSD", "USDCAD", "CADUSD", "USDCHF",
        "CHFUSD", "NZDUSD", "USDNZD",
    }:
        return 3 if "JPY" in normalized else 5
    return 2


def _regular_mask(index: pd.DatetimeIndex) -> list[bool]:
    ny = index.tz_convert("America/New_York")
    return [(_time >= _REGULAR_OPEN and _time < _REGULAR_CLOSE) for _time in ny.time]


def _is_us_intraday(symbol: str, quote: MarketQuote | None, timeframe: str) -> bool:
    if not timeframe.upper().startswith("1D"):
        return False
    asset = (quote.asset_class if quote else "").lower()
    return asset in {"stock", "index"} or symbol.upper().startswith("^")


def _range_labels(timeframe: str) -> list[str]:
    # Matches the practical Yahoo Finance range-bar vocabulary while keeping
    # the Telegram chart compact.
    return ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "All"]


def _selected_range(timeframe: str) -> str | None:
    upper = timeframe.upper().replace("MO", "M")
    for item in _range_labels(timeframe):
        if upper.startswith(item.upper()):
            return item
    return None


def _time_axis(ax, frame: pd.DataFrame, x: list[float], timeframe: str) -> None:
    if not x:
        return
    count = min(7, len(x))
    if count == 1:
        sample = [0]
    else:
        sample = list(dict.fromkeys(round(i * (len(x) - 1) / (count - 1)) for i in range(count)))
    ticks = [x[i] for i in sample]
    labels: list[str] = []
    if timeframe.upper().startswith("1D"):
        labels = [frame.index[i].strftime("%H:%M") for i in sample]
    elif timeframe.upper().startswith(("5D", "1M", "3M", "6M", "YTD")):
        labels = [frame.index[i].strftime("%b %d") for i in sample]
    else:
        labels = [frame.index[i].strftime("%b %Y") for i in sample]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.tick_params(axis="x", colors=_MUTED, labelsize=8.5, length=0, pad=7)


def _stats(frame: pd.DataFrame, quote: MarketQuote | None, previous: float | None) -> list[tuple[str, str]]:
    opening = float(frame["Open"].iloc[0])
    high = float(frame["High"].max())
    low = float(frame["Low"].min())
    volume = float(frame["Volume"].sum())
    market_cap = getattr(quote, "market_cap", None) if quote else None
    pe_ratio = getattr(quote, "pe_ratio", None) if quote else None
    year_high = getattr(quote, "year_high", None) if quote else None
    year_low = getattr(quote, "year_low", None) if quote else None
    after_hours = getattr(quote, "post_market_price", None) if quote else None
    after_move = ((after_hours / quote.price) - 1.0) * 100.0 if after_hours and quote and quote.price else None
    avg_volume = None
    if len(frame) > 1:
        avg_volume = float(frame["Volume"].mean())
    return [
        ("Previous close", _fmt_price(previous)),
        ("Open", _fmt_price(opening)),
        ("Volume", _fmt_volume(volume)),
        ("Day's range", f"{_fmt_price(low)} – {_fmt_price(high)}"),
        ("52-week range", f"{_fmt_price(year_low)} – {_fmt_price(year_high)}" if year_low and year_high else "n/a"),
        ("Avg. volume", _fmt_volume(avg_volume)),
        ("Mkt cap", _fmt_volume(market_cap)),
        ("P/E ratio", f"{pe_ratio:.2f}" if pe_ratio is not None else "n/a"),
        ("After hours", f"{_fmt_price(after_hours)}  ({_fmt_pct(after_move)})" if after_hours is not None else "n/a"),
    ]


async def render_yahoo_style_chart(
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
        raise ValueError("Yahoo-style renderer is for standard charts")

    frame = _clean(df)
    digits = _digits(symbol, quote)
    if quote is not None:
        price = quote.price if price is None else price
        if prev_close is None:
            prev_close = quote.previous_close
        if change_percent is None and prev_close:
            change_percent = (price / prev_close - 1.0) * 100.0
    if price is None:
        price = float(frame["Close"].iloc[-1])
    if prev_close is None or prev_close <= 0:
        prev_close = None
    if change_percent is None and prev_close:
        change_percent = (price / prev_close - 1.0) * 100.0

    frame = frame.iloc[-2500:]
    is_us_intraday = _is_us_intraday(symbol, quote, timeframe)
    regular = _regular_mask(frame.index) if is_us_intraday else [True] * len(frame)
    x = [float(i) for i in range(len(frame))]

    fig = plt.figure(figsize=(16.0, 8.6), dpi=240, facecolor=_BG)
    ax = fig.add_axes([0.045, 0.355, 0.87, 0.48], facecolor=_BG)
    av = fig.add_axes([0.045, 0.275, 0.87, 0.075], facecolor=_BG, sharex=ax)

    for axis in (ax, av):
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.tick_params(colors=_MUTED, length=0)
        axis.grid(axis="y", color=_GRID, linewidth=0.65, alpha=0.8)
        axis.grid(axis="x", color=_GRID, linewidth=0.45, linestyle=":", alpha=0.45)

    high = max(float(frame["High"].max()), prev_close or float(frame["High"].max()), float(price))
    low = min(float(frame["Low"].min()), prev_close or float(frame["Low"].min()), float(price))
    spread = max(high - low, abs(price) * 0.001, 0.01)
    pad = spread * 0.10
    ax.set_ylim(low - pad, high + pad)
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", colors=_MUTED, labelsize=8.5, pad=7)
    av.tick_params(axis="y", left=False, labelleft=False, labelright=False)

    if prev_close is not None:
        ax.axhline(prev_close, color=_PREV, linewidth=1.0, linestyle=(0, (5, 6)), alpha=0.8, zorder=1)
        ax.text(1.002, prev_close, f"Prev close\n{_fmt_price(prev_close, digits)}", transform=ax.get_yaxis_transform(), ha="left", va="center", color=_MUTED, fontsize=8.5, linespacing=1.0)

    # A Yahoo-like candle body/wick view. Extended-hours U.S. candles use a
    # neutral grey so the regular market session remains visually dominant.
    candle_width = 0.62 if len(frame) >= 10 else 0.45
    for i, (_, row) in enumerate(frame.iterrows()):
        opened = float(row["Open"])
        closed = float(row["Close"])
        high_i = float(row["High"])
        low_i = float(row["Low"])
        if is_us_intraday and not regular[i]:
            colour = _EXTENDED
            alpha = 0.72
        else:
            colour = _GREEN if closed >= opened else _RED
            alpha = 0.95
        ax.vlines(x[i], low_i, high_i, color=colour, linewidth=1.15, alpha=alpha, zorder=3)
        bottom = min(opened, closed)
        height = max(abs(closed - opened), spread * 0.0025)
        ax.add_patch(Rectangle((x[i] - candle_width / 2, bottom), candle_width, height, facecolor=colour, edgecolor=colour, linewidth=0.65, alpha=alpha, zorder=4))

        volume = float(row["Volume"])
        av.bar(x[i], volume, width=candle_width, color=colour, alpha=0.50 if colour != _EXTENDED else 0.24, align="center")

    av.set_ylim(0, max(float(frame["Volume"].max()) * 1.25, 1.0))
    av.axhline(0, color=_GRID, linewidth=0.7)
    av.text(0.0, 1.10, "Volume", transform=av.transAxes, ha="left", va="bottom", color=_MUTED, fontsize=8.5)
    av.set_xticklabels([])
    _time_axis(ax, frame, x, timeframe)
    ax.set_xlim(x[0] - 0.8, x[-1] + 0.8)

    headline_currency = f" {currency}" if currency else " USD" if (quote and quote.asset_class in {"stock", "index", "commodity", "metal", "market"}) else ""
    headline = f"{_fmt_price(float(price), digits)}{headline_currency}"
    if change_percent is not None:
        headline += f"  {_fmt_pct(change_percent)}"
    headline_colour = _GREEN if (change_percent or 0) > 0 else _RED if (change_percent or 0) < 0 else _MUTED

    ax.text(0.0, 1.23, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", color=_TEXT, fontsize=20, fontweight="bold")
    ax.text(0.0, 1.12, headline, transform=ax.transAxes, ha="left", va="bottom", color=headline_colour, fontsize=18, fontweight="bold")

    selector = _range_labels(timeframe)
    selected = _selected_range(timeframe)
    start = 0.66
    step = 0.042
    for index, item in enumerate(selector):
        xpos = start + index * step
        if item == selected:
            ax.text(xpos, 1.225, item, transform=ax.transAxes, ha="center", va="center", color=_TEXT, fontsize=10.2, fontweight="bold", bbox={"boxstyle": "round,pad=0.35", "facecolor": "#344054", "edgecolor": "none"})
        else:
            ax.text(xpos, 1.225, item, transform=ax.transAxes, ha="center", va="center", color="#c8ccd3", fontsize=10.0)

    date_label = frame.index[-1].strftime("%Y-%b-%d")
    ax.text(1.0, -0.34, date_label, transform=ax.transAxes, ha="right", va="top", color=_MUTED, fontsize=8.5)
    ax.text(1.0, -0.40, timeframe.upper(), transform=ax.transAxes, ha="right", va="top", color=_MUTED, fontsize=8.0, fontweight="bold")

    fig.add_artist(plt.Line2D([0.045, 0.915], [0.235, 0.235], transform=fig.transFigure, color=_GRID, linewidth=0.9))

    stats = _stats(frame, quote, prev_close)
    left_x = 0.06
    right_x = 0.54
    y_rows = [0.205, 0.166, 0.127]
    for row_index, (label, value) in enumerate(stats):
        column = 0 if row_index < 3 else 1 if row_index < 6 else 2
        local_row = row_index % 3
        xpos = [left_x, 0.32, 0.66][column]
        ypos = y_rows[local_row]
        fig.text(xpos, ypos, label, color=_MUTED, fontsize=9.0, ha="left", va="center")
        fig.text(xpos + 0.105, ypos, value, color=_TEXT, fontsize=9.8, fontweight="bold", ha="left", va="center")

    footer = "UTC Timezone"
    if is_us_intraday and any(not value for value in regular):
        footer += " • grey candles = extended hours"
    fig.text(0.045, 0.055, footer, color=_MUTED, fontsize=8.3, ha="left", va="center")

    output = io.BytesIO()
    fig.savefig(output, format="png", dpi=240, bbox_inches="tight", pad_inches=0.08, facecolor=_BG, edgecolor="none")
    plt.close(fig)
    output.seek(0)
    return output


def install() -> None:
    import app.charts as charts

    original = charts.render_chart

    async def render_chart_router(*args, **kwargs):
        advanced = bool(kwargs.get("advanced", False))
        if not advanced and len(args) >= 3:
            df, symbol, timeframe = args[:3]
            return await render_yahoo_style_chart(df, symbol, timeframe, False, **{key: kwargs[key] for key in ("prev_close", "price", "currency", "change_percent", "quote") if key in kwargs})
        if not advanced:
            return await render_yahoo_style_chart(
                kwargs.get("df"), kwargs.get("symbol"), kwargs.get("timeframe"), False,
                **{key: kwargs[key] for key in ("prev_close", "price", "currency", "change_percent", "quote") if key in kwargs},
            )
        return await original(*args, **kwargs)

    charts.render_chart = render_chart_router
    try:
        import app.bot as bot_module
        bot_module.render_chart = render_chart_router
    except Exception:
        pass

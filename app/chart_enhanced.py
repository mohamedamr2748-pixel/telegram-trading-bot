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
_PREV = "#d9dde3"


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
    if "Volume" not in work.columns:
        work["Volume"] = 0.0
    work["Volume"] = work["Volume"].fillna(0.0)
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
        ax.vlines(x[i], low, high, color=colour, linewidth=1.05, zorder=4, antialiased=True)
        body_bottom = min(open_, close)
        body_height = max(abs(close - open_), min_height)
        ax.add_patch(
            Rectangle(
                (x[i] - width / 2, body_bottom),
                width,
                body_height,
                facecolor=colour,
                edgecolor=colour,
                linewidth=0.5,
                zorder=5,
            )
        )


def _draw_volume(ax, x: list[float], frame: pd.DataFrame, compact: bool, regular: pd.Series | None = None) -> None:
    width = _candle_width(x, compact) * 0.82
    volume = frame["Volume"].to_numpy(dtype=float)
    max_volume = float(volume.max()) if len(volume) else 0.0
    for i, value in enumerate(volume):
        base_colour = _BODY_UP if float(frame["Close"].iloc[i]) >= float(frame["Open"].iloc[i]) else _BODY_DOWN
        colour = base_colour if regular is None or bool(regular.iloc[i]) else _EXTENDED
        ax.bar(x[i], value, width=width, color=colour, alpha=0.43 if colour != _EXTENDED else 0.22, align="center", zorder=2)
    ax.set_ylim(0, max(max_volume * 1.22, 1.0))
    ax.set_yticks([])
    ax.grid(False)
    ax.text(0.0, 1.08, "Volume", transform=ax.transAxes, ha="left", va="bottom", color=_MUTED, fontsize=8.5)


def _axis_labels(ax, frame: pd.DataFrame, x: list[float], compact: bool) -> None:
    if len(x) <= 1:
        ax.set_xticks(x)
        return
    count = min(8, len(x))
    sample = [round(i * (len(x) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    sample = list(dict.fromkeys(sample))
    ticks = [x[i] for i in sample]
    if compact:
        labels = [pd.Timestamp(frame.index[i]).tz_convert("UTC").strftime("%H:%M") for i in sample]
    elif len(frame) <= 12:
        labels = [pd.Timestamp(frame.index[i]).tz_convert("UTC").strftime("%d %b") for i in sample]
    elif len(frame) <= 140:
        labels = [pd.Timestamp(frame.index[i]).tz_convert("UTC").strftime("%d %b") for i in sample]
    else:
        labels = [pd.Timestamp(frame.index[i]).tz_convert("UTC").strftime("%b %Y") for i in sample]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.tick_params(axis="x", colors="#d7dbe2", labelsize=8.5, length=0, pad=8)


def _range_selection(timeframe: str) -> str | None:
    upper = timeframe.upper().replace("MO", "M")
    mapping = {"1D": "1D", "5D": "5D", "1M": "1M", "3M": "3M", "6M": "6M", "YTD": "YTD", "1Y": "1Y", "5Y": "5Y", "ALL": "All"}
    for key, value in mapping.items():
        if upper.startswith(key.upper()):
            return value
    return None


def _fmt_price(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _fmt_volume(value: float | None) -> str:
    if value is None:
        return "n/a"
    number = float(value)
    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.0f}K"
    return f"{number:.0f}"


def _yahoo_stats(frame: pd.DataFrame, quote, previous: float | None, *, compact: bool) -> list[tuple[str, str]]:
    opening = float(frame["Open"].iloc[0])
    high = float(frame["High"].max())
    low = float(frame["Low"].min())
    volume = float(frame["Volume"].sum())
    avg_volume = float(frame["Volume"].mean()) if len(frame) > 1 else None
    year_high = getattr(quote, "year_high", None) if quote else None
    year_low = getattr(quote, "year_low", None) if quote else None
    market_cap = getattr(quote, "market_cap", None) if quote else None
    pe_ratio = getattr(quote, "pe_ratio", None) if quote else None
    after_hours = getattr(quote, "post_market_price", None) if quote else None
    after_move = ((after_hours / quote.price) - 1.0) * 100.0 if after_hours and quote and quote.price else None
    if compact:
        day_range = f"{_fmt_price(low)} – {_fmt_price(high)}"
    else:
        day_range = f"{_fmt_price(low)} – {_fmt_price(high)}"
    after_text = "n/a"
    if after_hours is not None:
        after_text = f"{_fmt_price(after_hours)}  ({after_move:+.2f}%)" if after_move is not None else _fmt_price(after_hours)
    return [
        ("Previous close", _fmt_price(previous)),
        ("Open", _fmt_price(opening)),
        ("Volume", _fmt_volume(volume)),
        ("Day's range", day_range),
        ("52-week range", f"{_fmt_price(year_low)} – {_fmt_price(year_high)}" if year_low is not None and year_high is not None else "n/a"),
        ("Avg. volume", _fmt_volume(avg_volume)),
        ("Mkt cap", _fmt_volume(market_cap)),
        ("P/E ratio", f"{pe_ratio:.2f}" if pe_ratio is not None else "n/a"),
        ("After hours", after_text),
    ]


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

    compact = _is_1d_us(symbol, quote, timeframe)
    regular = _regular_mask(frame.index) if compact else None
    digits = charts._price_digits(symbol, quote)
    chart_start = float(frame["Low"].min())
    chart_end = float(frame["High"].max())
    if previous is not None:
        chart_start = min(chart_start, previous)
        chart_end = max(chart_end, previous)
    chart_start = min(chart_start, float(last_price))
    chart_end = max(chart_end, float(last_price))
    spread = max(chart_end - chart_start, abs(last_price) * 0.001, 0.01)
    chart_bottom = chart_start - spread * 0.09
    chart_top = chart_end + spread * 0.09

    x = _compressed_x(frame.index, compact)
    width = 0.62 if compact else _candle_width(x, compact)

    fig = plt.figure(figsize=(16.0, 8.8), dpi=240, facecolor=_BG)
    ax = fig.add_axes([0.035, 0.355, 0.865, 0.47], facecolor=_BG)
    vol_ax = fig.add_axes([0.035, 0.275, 0.865, 0.065], sharex=ax, facecolor=_BG)

    for axis in (ax, vol_ax):
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.tick_params(colors=_MUTED, length=0)
        axis.grid(axis="y", color=_GRID, linewidth=0.65, alpha=0.8)
        axis.grid(axis="x", color=_GRID, linewidth=0.45, linestyle=":", alpha=0.38)

    ax.set_ylim(chart_bottom, chart_top)
    ax.yaxis.tick_right()
    ax.tick_params(axis="y", colors="#d7dbe2", labelsize=8.5, pad=8)
    vol_ax.tick_params(axis="y", left=False, labelleft=False, labelright=False)

    _draw_candles(ax, x, frame, compact, regular)
    _draw_volume(vol_ax, x, frame, compact, regular)

    line_colour = _BODY_UP if (change_percent or 0.0) > 0 else _BODY_DOWN if (change_percent or 0.0) < 0 else _EXTENDED
    if previous is not None:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (5, 6)), color=_PREV, alpha=0.8, zorder=2)
        ax.text(1.002, previous, f"Prev close\n{_fmt_price(previous, digits)}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.4, color="#d5d8de", linespacing=1.0)

    # Match the current-price marker used by modern finance chart UIs.
    ax.axhline(last_price, linewidth=0.75, linestyle=(0, (3, 4)), color=line_colour, alpha=0.42, zorder=2)
    ax.text(1.002, last_price, _fmt_price(float(last_price), digits), transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.6, color=_BG, bbox={"boxstyle": "round,pad=0.25", "facecolor": line_colour, "edgecolor": "none"}, zorder=8)

    latest_colour = line_colour if regular is None or bool(regular.iloc[-1]) else _EXTENDED
    ax.scatter([x[-1]], [float(frame["Close"].iloc[-1])], s=38, color=latest_colour, edgecolor=_BG, linewidth=1.2, zorder=7)

    _axis_labels(vol_ax, frame, x, compact)
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.set_xlim(x[0] - (0.8 if compact else width), x[-1] + (0.8 if compact else width))

    headline_currency = f" {currency}" if currency else " USD" if quote and quote.asset_class in {"stock", "index", "commodity", "metal", "market"} else ""
    headline = f"{_fmt_price(float(last_price), digits)}{headline_currency}"
    if change_percent is not None:
        headline += f"  {change_percent:+.2f}%"
    ax.text(0.0, 1.20, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", fontsize=20, fontweight="bold", color=_TEXT)
    ax.text(0.0, 1.085, headline, transform=ax.transAxes, ha="left", va="bottom", fontsize=18, fontweight="bold", color=line_colour)

    selector = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "All"]
    selected = _range_selection(timeframe)
    for idx, item in enumerate(selector):
        xpos = 0.655 + idx * 0.0405
        ax.text(xpos, 1.185, item, transform=ax.transAxes, ha="center", va="center", fontsize=9.9, fontweight="bold" if item == selected else "normal", color=_TEXT if item == selected else "#c7ccd4", bbox={"boxstyle": "round,pad=0.27" if item == selected else "square,pad=0.0", "facecolor": "#344054" if item == selected else _BG, "edgecolor": "none"} if item == selected else None)

    chart_date = pd.Timestamp(frame.index[-1]).tz_convert("UTC").strftime("%Y-%b-%d")
    ax.text(1.0, -0.20, chart_date, transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#b9bec7")
    ax.text(1.0, -0.25, f"{timeframe.upper()} • UTC Timezone", transform=ax.transAxes, ha="right", va="top", color="#b8bdc7", fontsize=8.0, fontweight="bold")

    fig.add_artist(plt.Line2D([0.035, 0.93], [0.24, 0.24], transform=fig.transFigure, color=_GRID, linewidth=0.9))
    stats = _yahoo_stats(frame, quote, previous, compact=compact)
    y_positions = [0.208, 0.166, 0.124]
    x_positions = [0.055, 0.36, 0.66]
    for idx, (label, value) in enumerate(stats):
        column = idx % 3
        row = idx // 3
        xpos = x_positions[column]
        ypos = y_positions[row]
        fig.text(xpos, ypos, label, ha="left", va="center", fontsize=8.9, color=_MUTED)
        fig.text(xpos + 0.10, ypos, value, ha="left", va="center", fontsize=9.8, fontweight="bold", color=_TEXT)

    footer = "Candlesticks • Volume • Previous close"
    if compact and regular is not None and any(not value for value in regular):
        footer += " • Grey = extended hours"
    fig.text(0.045, 0.053, footer, color=_MUTED, fontsize=8.2, ha="left", va="center")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=240, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf


def install() -> None:
    charts.render_google_finance_chart = render_enhanced_google_finance_chart

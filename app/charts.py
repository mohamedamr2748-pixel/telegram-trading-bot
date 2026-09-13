from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import FancyBboxPatch

from app.domain import MarketQuote
from app.indicators import add_advanced_indicators

_STANDARD_FIGSIZE = (16.0, 8.0)
_STANDARD_DPI = 240
_ADVANCED_DPI = 220

_CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    facecolor="#111827",
    figcolor="#0b1220",
    gridcolor="#263246",
    gridstyle=":",
    gridaxis="both",
    y_on_right=True,
    rc={"axes.labelsize": 10, "axes.titlesize": 15, "xtick.labelsize": 9, "ytick.labelsize": 9, "font.size": 10, "figure.dpi": _ADVANCED_DPI, "savefig.dpi": _ADVANCED_DPI},
)


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required OHLC columns: {', '.join(missing)}")
    work = df.copy()
    work.index = pd.to_datetime(work.index)
    if getattr(work.index, "tz", None) is not None:
        work.index = work.index.tz_convert("UTC").tz_localize(None)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in work.columns]
    work = work[keep].apply(pd.to_numeric, errors="coerce")
    work = work[~work.index.duplicated(keep="last")].sort_index().dropna(subset=required)
    if work.empty:
        raise ValueError("No valid OHLC data available for chart")
    if "Volume" in work.columns:
        work["Volume"] = work["Volume"].fillna(0)
    return work


def _line(series: pd.Series, panel: int, color: str, width: float = 1.0, linestyle: str = "-"):
    return mpf.make_addplot(series, panel=panel, color=color, width=width, linestyle=linestyle, secondary_y=False)


def _display_index(index: pd.DatetimeIndex, symbol: str) -> pd.DatetimeIndex:
    upper = symbol.upper()
    if upper.endswith("-USD") or upper in {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD"}:
        return index
    try:
        return index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    except TypeError:
        return index


def _fmt_value(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.2f}T"
    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number:,.0f}"
    return f"{number:.{digits}f}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _fmt_meta(value: float | None, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%" if percent else _fmt_value(value)


def _period_performance(series: pd.Series, timeframe: str, daily_change: float | None) -> float | None:
    if series.empty:
        return None
    if timeframe.upper().startswith("1D"):
        return daily_change
    first = float(series.iloc[0])
    last = float(series.iloc[-1])
    return (last / first - 1.0) * 100.0 if first else None


def _session_stats(df: pd.DataFrame, symbol: str) -> dict[str, str]:
    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    work.index = _display_index(work.index, symbol)
    work = work.sort_index()
    intraday = len(work) > 1 and (work.index[-1] - work.index[-2]) <= pd.Timedelta(hours=2)
    if intraday:
        latest_date = work.index[-1].date()
        session = work[work.index.date == latest_date]
        if session.empty:
            session = work.iloc[-1:]
        opening = session["Open"].iloc[0]
        high = session["High"].max()
        low = session["Low"].min()
        volume = session["Volume"].sum() if "Volume" in session.columns else None
    else:
        row = work.iloc[-1]
        opening, high, low = row.get("Open"), row.get("High"), row.get("Low")
        volume = row.get("Volume") if "Volume" in work.columns else None
    return {"Open": _fmt_value(opening), "High": _fmt_value(high), "Low": _fmt_value(low), "Volume": _fmt_value(volume, 0)}


def _status_text(quote: MarketQuote | None) -> str:
    if quote is None:
        return "n/a"
    if quote.is_stale:
        return "STALE"
    return (quote.market_status or "LIVE").replace("_", " ").upper()


def _after_hours(quote: MarketQuote | None) -> str:
    if not quote or quote.post_market_price is None:
        return "n/a"
    move = ((quote.post_market_price / quote.price) - 1) * 100 if quote.price else None
    return f"{_fmt_value(quote.post_market_price)}  ({_fmt_percent(move)})" if move is not None else _fmt_value(quote.post_market_price)


def _pre_market(quote: MarketQuote | None) -> str:
    if not quote or quote.pre_market_price is None:
        return "n/a"
    move = ((quote.pre_market_price / quote.previous_close) - 1) * 100 if quote.previous_close else None
    return f"{_fmt_value(quote.pre_market_price)}  ({_fmt_percent(move)})" if move is not None else _fmt_value(quote.pre_market_price)


async def _correct_yfinance_previous_close(symbol: str, quote: MarketQuote | None, timeframe: str) -> float | None:
    if quote is None or quote.source != "yfinance" or not timeframe.upper().startswith("1D"):
        return quote.previous_close if quote else None
    try:
        from app.market import MarketService
        daily = await MarketService().get_history(symbol, period="5d", interval="1d")
        if "Close" not in daily.columns:
            return quote.previous_close
        daily = daily.copy()
        daily["Close"] = pd.to_numeric(daily["Close"], errors="coerce")
        daily = daily.dropna(subset=["Close"]).sort_index()
        if len(daily) >= 2:
            return float(daily["Close"].iloc[-2])
    except Exception:
        pass
    return quote.previous_close


def _selector_key(timeframe: str) -> str | None:
    upper = timeframe.upper().replace("MO", "M")
    mapping = [("1D", "1D"), ("5D", "5D"), ("1M", "1M"), ("6M", "6M"), ("YTD", "YTD"), ("1Y", "1Y"), ("5Y", "5Y")]
    return next((label for prefix, label in mapping if upper.startswith(prefix)), None)


async def render_google_finance_chart(df: pd.DataFrame, symbol: str, timeframe: str, prev_close: float | None = None, price: float | None = None, currency: str | None = None, change_percent: float | None = None, quote: MarketQuote | None = None) -> io.BytesIO:
    if "Close" not in df.columns:
        raise ValueError("Chart requires a Close/price series")
    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    work["Close"] = pd.to_numeric(work["Close"], errors="coerce")
    work = work.dropna(subset=["Close"]).sort_index()
    work = work[~work.index.duplicated(keep="last")]
    if work.empty:
        raise ValueError("No valid price points available for chart")
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
        corrected_previous = await _correct_yfinance_previous_close(symbol, quote, timeframe)
        if prev_close is None or quote.source == "yfinance":
            prev_close = corrected_previous
        if prev_close and prev_close > 0:
            change_percent = ((price if price is not None else quote.price) / prev_close - 1.0) * 100.0
        elif change_percent is None:
            change_percent = quote.change_percent
    display_index = _display_index(work.index, symbol)
    series = pd.Series(work["Close"].to_numpy(dtype=float), index=display_index)
    last_price = price if price is not None else float(series.iloc[-1])
    previous = prev_close if prev_close and prev_close > 0 else None
    if change_percent is None and previous:
        change_percent = (last_price / previous - 1.0) * 100.0
    period_perf = _period_performance(series, timeframe, change_percent)
    stats = _session_stats(work, symbol)
    currency_text = f" {currency}" if currency else ""

    fig = plt.figure(figsize=_STANDARD_FIGSIZE, dpi=_STANDARD_DPI, facecolor="#202124")
    ax = fig.add_axes([0.035, 0.30, 0.865, 0.56])
    ax.set_facecolor("#202124")
    x = series.index.to_pydatetime()
    y = series.to_numpy(dtype=float)
    baseline = float(min(y.min(), previous if previous else y.min()))
    ceiling = float(max(y.max(), previous if previous else y.max()))
    spread = ceiling - baseline
    padding = max(spread * 0.22, abs(last_price) * 0.0025, 0.01)
    chart_bottom, chart_top = baseline - padding, ceiling + padding
    if change_percent is None or abs(change_percent) < 1e-12:
        line_color = "#9aa0a6"
    elif change_percent > 0:
        line_color = "#55e982"
    else:
        line_color = "#f26b63"
    ax.plot(x, y, linewidth=2.55, color=line_color, solid_capstyle="round", solid_joinstyle="round", antialiased=True, zorder=4)
    ax.fill_between(x, y, chart_bottom, color=line_color, alpha=0.11, zorder=1, antialiased=True)
    if previous is not None:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (5, 6)), color="#e4e7eb", alpha=0.85, zorder=2)
        ax.text(1.002, previous, f"Prev close\n{previous:.2f}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.5, color="#d5d8de", linespacing=1.08)
    ax.scatter([x[-1]], [y[-1]], s=50, color=line_color, edgecolor="#202124", linewidth=1.5, zorder=6, antialiased=True)
    ax.set_ylim(chart_bottom, chart_top)
    ax.grid(axis="y", color="#34373b", linestyle="-", linewidth=0.65, alpha=0.75)
    ax.grid(axis="x", color="#34373b", linestyle="--", linewidth=0.55, alpha=0.55)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#d7dbe2", labelsize=8.5, length=0, pad=8)
    ax.yaxis.tick_right()
    locator = mdates.AutoDateLocator(minticks=4, maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_xlim(x[0], x[-1])

    price_line = f"{last_price:.2f}{currency_text}"
    if change_percent is not None:
        price_line += f"  {change_percent:+.2f}%"
    ax.text(0.0, 1.19, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", fontsize=20, fontweight="bold", color="#f8fafc")
    ax.text(0.0, 1.065, price_line, transform=ax.transAxes, ha="left", va="bottom", fontsize=18, fontweight="bold", color=line_color if change_percent is not None else "#f8fafc")

    # Reference-style timeframe selector.
    selector = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y"]
    selected = _selector_key(timeframe)
    start_x = 0.67
    step = 0.047
    for idx, item in enumerate(selector):
        xpos = start_x + idx * step
        if item == selected:
            pill = FancyBboxPatch(
                (xpos - 0.020, 1.145), 0.040, 0.085,
                boxstyle="round,pad=0.008,rounding_size=0.018",
                transform=ax.transAxes,
                linewidth=0,
                facecolor="#30343a",
                edgecolor="none",
                zorder=8,
            )
            ax.add_patch(pill)
            ax.text(xpos, 1.19, item, transform=ax.transAxes, ha="center", va="center", fontsize=10.5, fontweight="bold", color="#f8fafc", zorder=9)
        else:
            ax.text(xpos, 1.19, item, transform=ax.transAxes, ha="center", va="center", fontsize=10.5, color="#c7ccd4", zorder=8)

    chart_date = pd.Timestamp(x[-1]).strftime("%Y-%b-%d")
    ax.text(1.0, 1.19, chart_date, transform=ax.transAxes, ha="right", va="center", fontsize=8.5, color="#b9bec7")
    ax.text(1.0, -0.10, timeframe.upper(), transform=ax.transAxes, ha="right", va="top", color="#b8bdc7", fontsize=8.5, fontweight="bold")

    fig.add_artist(plt.Line2D([0.035, 0.93], [0.262, 0.262], transform=fig.transFigure, color="#34373b", linewidth=0.9))

    rows = [
        [("Open", stats["Open"]), ("Mkt cap", _fmt_value(quote.market_cap) if quote else "n/a"), ("Dividend", _fmt_meta(quote.dividend_yield, percent=True) if quote else "n/a")],
        [("High", stats["High"]), ("P/E ratio", _fmt_meta(quote.pe_ratio) if quote else "n/a"), ("After hours", _after_hours(quote))],
        [("Low", stats["Low"]), ("52-wk high", _fmt_value(quote.year_high) if quote else "n/a"), ("52-wk low", _fmt_value(quote.year_low) if quote else "n/a")],
    ]
    y_positions = [0.222, 0.180, 0.138]
    x_positions = [0.048, 0.37, 0.685]
    value_offsets = [0.105, 0.105, 0.105]
    for ypos, row in zip(y_positions, rows):
        for xpos, (label, value), offset in zip(x_positions, row, value_offsets):
            fig.text(xpos, ypos, label, ha="left", va="center", fontsize=8.9, color="#9aa0a6")
            fig.text(xpos + offset, ypos, value, ha="left", va="center", fontsize=9.7, fontweight="bold", color="#f8fafc")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_STANDARD_DPI, bbox_inches="tight", pad_inches=0.06, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf


async def render_chart(df: pd.DataFrame, symbol: str, timeframe: str, advanced: bool = False, *, prev_close: float | None = None, price: float | None = None, currency: str | None = None, change_percent: float | None = None, quote: MarketQuote | None = None) -> io.BytesIO:
    if not advanced:
        return await render_google_finance_chart(df, symbol, timeframe, prev_close=prev_close, price=price, currency=currency, change_percent=change_percent, quote=quote)
    work = _clean_ohlcv(df)
    enriched = add_advanced_indicators(work)
    has_volume = "Volume" in enriched.columns
    volume_panel = 1 if has_volume else 0
    rsi_panel = 2 if has_volume else 1
    macd_panel = 3 if has_volume else 2
    plots = []
    if "EMA20" in enriched:
        plots.append(_line(enriched["EMA20"], 0, "#fbbf24", 1.15))
    if "EMA50" in enriched:
        plots.append(_line(enriched["EMA50"], 0, "#60a5fa", 1.15))
    if "BB_UPPER" in enriched:
        plots.append(_line(enriched["BB_UPPER"], 0, "#a78bfa", 0.9))
    if "BB_LOWER" in enriched:
        plots.append(_line(enriched["BB_LOWER"], 0, "#a78bfa", 0.9))
    if "RSI14" in enriched:
        plots.extend([_line(enriched["RSI14"], rsi_panel, "#22d3ee", 1.05), _line(pd.Series(70.0, index=enriched.index), rsi_panel, "#ef4444", 0.65, "--"), _line(pd.Series(30.0, index=enriched.index), rsi_panel, "#22c55e", 0.65, "--"), _line(pd.Series(50.0, index=enriched.index), rsi_panel, "#64748b", 0.5, ":")])
    if {"MACD", "MACD_SIGNAL"}.issubset(enriched.columns):
        histogram = enriched["MACD"] - enriched["MACD_SIGNAL"]
        plots.extend([mpf.make_addplot(histogram.clip(lower=0), type="bar", panel=macd_panel, color="#22c55e", alpha=0.55, width=0.7), mpf.make_addplot(histogram.clip(upper=0), type="bar", panel=macd_panel, color="#ef4444", alpha=0.55, width=0.7), _line(enriched["MACD"], macd_panel, "#60a5fa", 1.0), _line(enriched["MACD_SIGNAL"], macd_panel, "#f59e0b", 1.0), _line(pd.Series(0.0, index=enriched.index), macd_panel, "#64748b", 0.5, "--")])
    ratios = [6]
    if has_volume:
        ratios.append(1.8)
    ratios.extend([2, 2])
    fig, _ = mpf.plot(enriched, type="candle", style=_CHART_STYLE, addplot=plots or None, volume=has_volume, volume_panel=volume_panel if has_volume else 0, panel_ratios=ratios, figsize=(14.0, 9.8), title=f"{symbol.upper()}  •  {timeframe}  •  Advanced", ylabel="Price", ylabel_lower="Volume" if has_volume else "", xrotation=0, datetime_format="%d %b\n%H:%M", tight_layout=True, returnfig=True, warn_too_much_data=10000)
    fig.set_dpi(_ADVANCED_DPI)
    fig.suptitle(f"{symbol.upper()}  •  {timeframe}  •  Advanced", x=0.055, y=0.985, ha="left", fontsize=15, fontweight="bold", color="#f8fafc")
    fig.subplots_adjust(top=0.94, left=0.05, right=0.96, bottom=0.07, hspace=0.08)
    fig.text(0.055, 0.018, "EMA20 / EMA50  •  Bollinger Bands  •  RSI14  •  MACD", ha="left", va="bottom", fontsize=8.0, color="#94a3b8")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_ADVANCED_DPI, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf

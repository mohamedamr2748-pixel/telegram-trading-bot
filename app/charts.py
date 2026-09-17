from __future__ import annotations

import io
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import FixedFormatter, FixedLocator

from app.chart_sessions import SessionKind, TradingFrame, UTC, build_frame, classify_timestamp
from app.domain import MarketQuote
from app.indicators import add_advanced_indicators

_STANDARD_FIGSIZE = (16.0, 8.0)
_STANDARD_DPI = 240
_ADVANCED_DPI = 220
_EXTENDED_GREY = "#9aa0a6"
_REGULAR_GREEN = "#55e982"
_REGULAR_RED = "#f26b63"

_TIMEFRAME_RE = re.compile(r"^(?P<count>\d+)(?P<unit>mo|wk|w|d|h|m)$", re.IGNORECASE)

_CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    facecolor="#111827",
    figcolor="#0b1220",
    gridcolor="#263246",
    gridstyle=":",
    gridaxis="both",
    y_on_right=True,
    rc={
        "axes.labelsize": 10,
        "axes.titlesize": 15,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "font.size": 10,
        "figure.dpi": _ADVANCED_DPI,
        "savefig.dpi": _ADVANCED_DPI,
    },
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


def _prepare_price_series(df: pd.DataFrame) -> pd.DataFrame:
    if "Close" not in df.columns:
        raise ValueError("Chart requires a Close/price series")
    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index, utc=True, errors="coerce")
    else:
        if work.index.tz is None:
            work.index = work.index.tz_localize("UTC")
        else:
            work.index = work.index.tz_convert("UTC")
    work = work[work.index.notna()]
    work["Close"] = pd.to_numeric(work["Close"], errors="coerce")
    work = work.dropna(subset=["Close"])
    work = work[~work.index.duplicated(keep="last")].sort_index()
    if len(work) > 2500:
        work = work.iloc[-2500:]
    if work.empty:
        raise ValueError("No valid price points available for chart")
    return work


def _line(series: pd.Series, panel: int, color: str, width: float = 1.0, linestyle: str = "-"):
    return mpf.make_addplot(series, panel=panel, color=color, width=width, linestyle=linestyle, secondary_y=False)


def _display_index(index: pd.DatetimeIndex, symbol: str) -> pd.DatetimeIndex:
    work = pd.DatetimeIndex(index)
    if work.tz is None:
        return work.tz_localize(UTC)
    return work.tz_convert(UTC)


def _fmt_value(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    magnitude = abs(number)
    if magnitude >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.2f}T"
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{number:,.0f}"
    if digits != 2:
        return f"{number:.{digits}f}"
    if magnitude >= 1:
        return f"{number:,.2f}"
    if magnitude >= 0.01:
        return f"{number:.4f}"
    if magnitude >= 0.0001:
        return f"{number:.6f}"
    return f"{number:.8f}"


def _fmt_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _fmt_meta(value: float | None, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%" if percent else _fmt_value(value)


def _price_digits(symbol: str, quote: MarketQuote | None) -> int:
    asset = (quote.asset_class if quote else "").lower()
    normalized = symbol.upper().replace("/", "").replace("-", "")
    forex_symbols = {
        "EURUSD", "USDEUR", "GBPUSD", "USDGBP", "USDJPY", "JPYUSD",
        "AUDUSD", "USDAUD", "AUUSD", "USDCAD", "CADUSD", "USDCHF",
        "CHFUSD", "NZDUSD", "USDNZD",
    }
    if asset == "forex" or normalized in forex_symbols:
        return 5 if "JPY" not in normalized else 3
    return 2


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
    work = work.sort_index()
    intraday = len(work) > 1 and (work.index[-1] - work.index[-2]) <= pd.Timedelta(hours=2)
    if intraday:
        latest_date = work.index[-1].date()
        session = work[work.index.date == latest_date]
        if session.empty:
            session = work.iloc[-1:]
    else:
        session = work.iloc[-1:]
    row = session.iloc[0]
    opening = session["Open"].iloc[0] if "Open" in session.columns else row["Close"]
    high = session["High"].max() if "High" in session.columns else session["Close"].max()
    low = session["Low"].min() if "Low" in session.columns else session["Close"].min()
    volume = session["Volume"].sum() if "Volume" in session.columns else None
    return {
        "Open": _fmt_value(opening),
        "High": _fmt_value(high),
        "Low": _fmt_value(low),
        "Volume": _fmt_value(volume, 0),
    }


def _regular_session_stats(df: pd.DataFrame, frame: TradingFrame, symbol: str) -> dict[str, str]:
    if frame.regular_utc is None:
        return _session_stats(df, symbol)
    start, end = frame.regular_utc
    regular = df[(df.index >= start) & (df.index < end)]
    if regular.empty:
        return _session_stats(df, symbol)
    opening = regular["Open"].iloc[0] if "Open" in regular.columns else regular["Close"].iloc[0]
    high = regular["High"].max() if "High" in regular.columns else regular["Close"].max()
    low = regular["Low"].min() if "Low" in regular.columns else regular["Close"].min()
    volume = regular["Volume"].sum() if "Volume" in regular.columns else None
    return {
        "Open": _fmt_value(opening),
        "High": _fmt_value(high),
        "Low": _fmt_value(low),
        "Volume": _fmt_value(volume, 0),
    }


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


def _asset_stats_rows(symbol: str, quote: MarketQuote | None, stats: dict[str, str], change_percent: float | None) -> list[list[tuple[str, str]]]:
    asset = (quote.asset_class if quote else "stock").lower()
    normalized = symbol.upper().replace("/", "").replace("-", "")
    digits = _price_digits(symbol, quote)
    forex_symbols = {
        "EURUSD", "USDEUR", "GBPUSD", "USDGBP", "USDJPY", "JPYUSD",
        "AUDUSD", "USDAUD", "AUUSD", "USDCAD", "CADUSD", "USDCHF",
        "CHFUSD", "NZDUSD", "USDNZD",
    }
    forex = asset == "forex" or normalized in forex_symbols
    if forex:
        return [
            [("Open", _fmt_value(stats["Open"], digits)), ("Previous", _fmt_value(quote.previous_close, digits) if quote else "n/a"), ("Day change", _fmt_percent(change_percent))],
            [("High", _fmt_value(stats["High"], digits)), ("52-wk high", _fmt_value(quote.year_high, digits) if quote else "n/a"), ("52-wk low", _fmt_value(quote.year_low, digits) if quote else "n/a")],
            [("Low", _fmt_value(stats["Low"], digits)), ("Session", _status_text(quote)), ("Updated", quote.timestamp.strftime("%H:%M UTC") if quote else "n/a")],
        ]
    if asset == "crypto":
        return [
            [("Open", stats["Open"]), ("Previous", _fmt_value(quote.previous_close) if quote else "n/a"), ("24h volume", _fmt_value(quote.volume, 0) if quote else stats["Volume"])],
            [("High", stats["High"]), ("52-wk high", _fmt_value(quote.year_high) if quote else "n/a"), ("52-wk low", _fmt_value(quote.year_low) if quote else "n/a")],
            [("Low", stats["Low"]), ("Session", _status_text(quote)), ("Updated", quote.timestamp.strftime("%H:%M UTC") if quote else "n/a")],
        ]
    if asset in {"metal", "commodity"}:
        return [
            [("Open", stats["Open"]), ("Previous", _fmt_value(quote.previous_close) if quote else "n/a"), ("Day change", _fmt_percent(change_percent))],
            [("High", stats["High"]), ("52-wk high", _fmt_value(quote.year_high) if quote else "n/a"), ("52-wk low", _fmt_value(quote.year_low) if quote else "n/a")],
            [("Low", stats["Low"]), ("Session", _status_text(quote)), ("Updated", quote.timestamp.strftime("%H:%M UTC") if quote else "n/a")],
        ]
    return [
        [("Open", stats["Open"]), ("Mkt cap", _fmt_value(quote.market_cap) if quote else "n/a"), ("Dividend", _fmt_meta(quote.dividend_yield, percent=True) if quote else "n/a")],
        [("High", stats["High"]), ("P/E ratio", _fmt_meta(quote.pe_ratio) if quote else "n/a"), ("After hours", _after_hours(quote))],
        [("Low", stats["Low"]), ("52-wk high", _fmt_value(quote.year_high) if quote else "n/a"), ("52-wk low", _fmt_value(quote.year_low) if quote else "n/a")],
    ]


def _regular_session_mask(index: pd.DatetimeIndex) -> pd.Series:
    aware = pd.DatetimeIndex(index)
    if aware.tz is None:
        aware = aware.tz_localize(UTC)
    values = []
    for stamp in aware:
        et_date = stamp.tz_convert("America/New_York").date()
        values.append(classify_timestamp(stamp, et_date) is SessionKind.REGULAR)
    return pd.Series(values, index=index)


def _regular_session_performance(
    index: pd.DatetimeIndex,
    values,
    frame: TradingFrame | None,
) -> float | None:
    """Return the movement across observed regular-session prices only."""
    if frame is None or frame.regular_utc is None:
        return None

    aware = pd.DatetimeIndex(index)
    if aware.tz is None:
        aware = aware.tz_localize(UTC)
    else:
        aware = aware.tz_convert(UTC)

    start, end = frame.regular_utc
    regular = pd.Series(values, index=aware)
    regular = pd.to_numeric(regular, errors="coerce")
    regular = regular[(aware >= start) & (aware < end)].dropna()
    if len(regular) < 2 or float(regular.iloc[0]) == 0:
        return None
    return (float(regular.iloc[-1]) / float(regular.iloc[0]) - 1.0) * 100.0


def _is_full_day_us_intraday(symbol: str, quote: MarketQuote | None, timeframe: str) -> bool:
    return timeframe.upper().startswith("1D") and build_frame(
        symbol, pd.Timestamp.now(tz=UTC), quote.asset_class if quote else None
    ) is not None


async def _correct_yfinance_previous_close(
    symbol: str,
    quote: MarketQuote | None,
    timeframe: str,
    trading_date_iso: str | None,
) -> float | None:
    if quote is None or quote.source != "yfinance" or not timeframe.upper().startswith("1D"):
        return quote.previous_close if quote else None
    if (
        quote.corrected_previous_close is not None
        and quote.corrected_for_trading_date == trading_date_iso
    ):
        return quote.corrected_previous_close
    try:
        from app.market import MarketService
        daily = await MarketService().get_history(symbol, period="5d", interval="1d")
        if "Close" not in daily.columns:
            return quote.previous_close
        daily = daily.copy()
        daily["Close"] = pd.to_numeric(daily["Close"], errors="coerce")
        daily = daily.dropna(subset=["Close"]).sort_index()
        if len(daily) >= 2:
            corrected = float(daily["Close"].iloc[-2])
            quote.corrected_previous_close = corrected
            quote.corrected_for_trading_date = trading_date_iso
            return corrected
    except Exception:
        pass
    return quote.previous_close


def _selector_key(timeframe: str) -> str | None:
    upper = timeframe.upper().replace("MO", "M")
    mapping = [("1D", "1D"), ("5D", "5D"), ("1M", "1M"), ("6M", "6M"), ("YTD", "YTD"), ("1Y", "1Y"), ("5Y", "5Y")]
    return next((label for prefix, label in mapping if upper.startswith(prefix)), None)


def _draw_session_bands(ax, frame: TradingFrame, regular_colour: str) -> None:
    """Show the fixed trading-session frame without inventing any prices."""
    if frame.premarket_utc is not None:
        start, end = frame.premarket_utc
        ax.axvspan(start.to_pydatetime(), end.to_pydatetime(), facecolor=_EXTENDED_GREY, alpha=0.035, zorder=0)
    if frame.regular_utc is not None:
        start, end = frame.regular_utc
        ax.axvspan(start.to_pydatetime(), end.to_pydatetime(), facecolor=regular_colour, alpha=0.014, zorder=0)
    if frame.aftermarket_utc is not None:
        start, end = frame.aftermarket_utc
        ax.axvspan(start.to_pydatetime(), end.to_pydatetime(), facecolor=_EXTENDED_GREY, alpha=0.035, zorder=0)


def _plot_session_coloured_line(ax, index: pd.DatetimeIndex, values, frame: TradingFrame, regular_colour: str, bottom: float) -> None:
    if len(index) == 0 or frame.trading_date is None:
        return
    kinds = [classify_timestamp(ts, frame.trading_date) for ts in index]
    numeric = pd.Series(values, index=index).to_numpy(dtype=float)
    for i in range(len(index) - 1):
        gap = index[i + 1] - index[i]
        if gap > pd.Timedelta(hours=2):
            continue
        regular = kinds[i] is SessionKind.REGULAR and kinds[i + 1] is SessionKind.REGULAR
        colour = regular_colour if regular else _EXTENDED_GREY
        alpha = 0.11 if regular else 0.055
        ax.plot(
            index[i:i + 2],
            numeric[i:i + 2],
            linewidth=2.55,
            color=colour,
            solid_capstyle="round",
            solid_joinstyle="round",
            antialiased=True,
            zorder=4,
        )
        ax.fill_between(index[i:i + 2], numeric[i:i + 2], bottom, color=colour, alpha=alpha, zorder=1, antialiased=True)
    last_colour = regular_colour if kinds[-1] is SessionKind.REGULAR else _EXTENDED_GREY
    ax.scatter([index[-1]], [numeric[-1]], s=50, color=last_colour, edgecolor="#202124", linewidth=1.5, zorder=6, antialiased=True)


def _configure_us_equity_x_axis(ax, frame: TradingFrame) -> None:
    x_min = mdates.date2num(frame.x_min_utc.to_pydatetime())
    x_max = mdates.date2num(frame.x_max_utc.to_pydatetime())
    if x_max <= x_min:
        half_hour = 30.0 / (24.0 * 60.0)
        x_min -= half_hour
        x_max += half_hour
    ax.set_xlim(x_min, x_max)
    locator = mdates.AutoDateLocator(minticks=6, maxticks=8, interval_multiples=True)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=UTC))
    ax.xaxis.get_offset_text().set_visible(False)


def _timeframe_interval(timeframe: str) -> tuple[int, str]:
    parts = [part.strip().lower() for part in timeframe.split("/") if part.strip()]
    for raw_interval in reversed(parts):
        match = _TIMEFRAME_RE.fullmatch(raw_interval)
        if match is not None:
            return int(match.group("count")), match.group("unit")
    return 1, "d"


def _timestamp_tick_step(timeframe: str, span: pd.Timedelta) -> pd.Timedelta:
    count, unit = _timeframe_interval(timeframe)
    base_seconds = count * {
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
        "wk": 7 * 24 * 60 * 60,
        "mo": 30 * 24 * 60 * 60,
    }[unit]
    multiples = {
        "m": (1, 2, 3, 5, 10, 15, 30, 60, 120, 240, 360, 720, 1440),
        "h": (1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 168),
        "d": (1, 2, 3, 5, 7, 14, 30, 60, 90, 180, 365),
        "w": (1, 2, 4, 8, 13, 26, 52),
        "wk": (1, 2, 4, 8, 13, 26, 52),
        "mo": (1, 2, 3, 6, 12),
    }[unit]
    span_seconds = max(span.total_seconds(), 0.0)
    multiple = next((value for value in multiples if span_seconds / (base_seconds * value) <= 8), multiples[-1])
    return pd.Timedelta(seconds=base_seconds * multiple)


def _observed_timestamp_ticks(index: pd.DatetimeIndex, timeframe: str) -> pd.DatetimeIndex:
    observed = _display_index(index, "")
    if not len(observed):
        return observed
    observed = observed.drop_duplicates().sort_values()
    step = _timestamp_tick_step(timeframe, observed[-1] - observed[0])
    ticks = [observed[0]]
    next_target = observed[0] + step
    for timestamp in observed[1:]:
        if timestamp >= next_target:
            ticks.append(timestamp)
            next_target = timestamp + step
    if ticks[-1] != observed[-1]:
        ticks.append(observed[-1])
    return pd.DatetimeIndex(ticks)


def _timestamp_tick_labels(ticks: pd.DatetimeIndex, timeframe: str) -> list[str]:
    if len(ticks) <= 1:
        return [ticks[0].strftime("%H:%M")] if len(ticks) else []
    count, unit = _timeframe_interval(timeframe)
    span = ticks[-1] - ticks[0]
    if unit in {"m", "h"}:
        # 4H charts intentionally show time only, never calendar dates.
        if count == 4 and unit == "h":
            date_format = "%H:%M"
        else:
            date_format = "%d %b\n%H:%M" if span >= pd.Timedelta(days=2) else "%H:%M"
    elif unit == "mo":
        date_format = "%b %Y"
    else:
        date_format = "%b %Y" if span >= pd.Timedelta(days=365) else "%d %b"
    return [timestamp.strftime(date_format) for timestamp in ticks]


def _configure_observed_timestamp_ticks(
    ax,
    index: pd.DatetimeIndex,
    timeframe: str,
    visible_bounds: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> None:
    observed = _display_index(index, "")
    if visible_bounds is not None:
        lower, upper = visible_bounds
        observed = observed[(observed >= lower) & (observed <= upper)]
    ticks = _observed_timestamp_ticks(observed, timeframe)
    if not len(ticks):
        return
    positions = mdates.date2num(ticks.to_pydatetime())
    labels = _timestamp_tick_labels(ticks, timeframe)
    ax.xaxis.set_major_locator(FixedLocator(positions))
    ax.xaxis.set_major_formatter(FixedFormatter(labels))
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
    work = _prepare_price_series(df)
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

    is_1d = timeframe.upper().startswith("1D")
    frame = build_frame(
        symbol,
        work.index[-1],
        quote.asset_class if quote else None,
        observed_index=work.index,
    ) if is_1d else None
    trading_date_iso = frame.trading_date.isoformat() if frame and frame.trading_date else None

    if quote is not None and quote.source == "yfinance" and is_1d:
        corrected_previous = await _correct_yfinance_previous_close(symbol, quote, timeframe, trading_date_iso)
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
        previous = first_close

    period_perf = _period_performance(work["Close"], timeframe, change_percent)
    regular_perf = _regular_session_performance(work.index, work["Close"], frame) if frame is not None else None
    colour_perf = regular_perf if frame is not None else period_perf
    line_color = _REGULAR_GREEN if colour_perf is not None and colour_perf > 1e-12 else _REGULAR_RED if colour_perf is not None and colour_perf < -1e-12 else _EXTENDED_GREY
    stats = _regular_session_stats(work, frame, symbol) if frame is not None else _session_stats(work, symbol)
    digits = _price_digits(symbol, quote)
    currency_text = f" {currency}" if currency else ""

    fig = plt.figure(figsize=_STANDARD_FIGSIZE, dpi=_STANDARD_DPI, facecolor="#202124")
    ax = fig.add_axes([0.035, 0.30, 0.865, 0.56])
    ax.set_facecolor("#202124")
    y = work["Close"].to_numpy(dtype=float)
    baseline = float(min(y.min(), previous if previous is not None else y.min()))
    ceiling = float(max(y.max(), previous if previous is not None else y.max()))
    spread = ceiling - baseline
    padding = max(spread * 0.22, abs(last_price) * 0.0025, 0.01)
    chart_bottom, chart_top = baseline - padding, ceiling + padding

    if frame is not None:
        _draw_session_bands(ax, frame, line_color)
        _plot_session_coloured_line(ax, work.index, y, frame, line_color, chart_bottom)
    else:
        x = work.index.to_pydatetime()
        ax.plot(x, y, linewidth=2.55, color=line_color, solid_capstyle="round", solid_joinstyle="round", antialiased=True, zorder=4)
        ax.fill_between(x, y, chart_bottom, color=line_color, alpha=0.11, zorder=1, antialiased=True)
        ax.scatter([x[-1]], [y[-1]], s=50, color=line_color, edgecolor="#202124", linewidth=1.5, zorder=6, antialiased=True)

    if previous is not None:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (5, 6)), color="#e4e7eb", alpha=0.85, zorder=2)
        ax.text(1.002, previous, f"Prev close\n{_fmt_value(previous, digits)}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8.5, color="#d5d8de", linespacing=1.08)

    ax.set_ylim(chart_bottom, chart_top)
    ax.grid(axis="y", color="#34373b", linestyle="-", linewidth=0.65, alpha=0.75)
    ax.grid(axis="x", color="#34373b", linestyle="--", linewidth=0.55, alpha=0.55)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#d7dbe2", labelsize=8.5, length=0, pad=8)
    ax.yaxis.tick_right()

    if frame is not None:
        _configure_us_equity_x_axis(ax, frame)
        _configure_observed_timestamp_ticks(
            ax,
            work.index,
            timeframe,
            visible_bounds=(frame.x_min_utc, frame.x_max_utc),
        )
    else:
        x = work.index.to_pydatetime()
        if len(x) > 1:
            ax.set_xlim(x[0], x[-1])
        _configure_observed_timestamp_ticks(ax, work.index, timeframe)

    price_line = f"{_fmt_value(last_price, digits)}{currency_text}"
    if period_perf is not None:
        price_line += f"  {period_perf:+.2f}%"
    ax.text(0.0, 1.19, symbol.upper(), transform=ax.transAxes, ha="left", va="bottom", fontsize=20, fontweight="bold", color="#f8fafc")
    ax.text(0.0, 1.065, price_line, transform=ax.transAxes, ha="left", va="bottom", fontsize=18, fontweight="bold", color=line_color if period_perf is not None else "#f8fafc")

    selector = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y"]
    selected = _selector_key(timeframe)
    start_x, step = 0.67, 0.047
    for idx, item in enumerate(selector):
        xpos = start_x + idx * step
        if item == selected:
            pill = FancyBboxPatch((xpos - 0.020, 1.145), 0.040, 0.085, boxstyle="round,pad=0.008,rounding_size=0.018", transform=ax.transAxes, linewidth=0, facecolor="#30343a", edgecolor="none", zorder=8)
            ax.add_patch(pill)
            ax.text(xpos, 1.19, item, transform=ax.transAxes, ha="center", va="center", fontsize=10.5, fontweight="bold", color="#f8fafc", zorder=9)
        else:
            ax.text(xpos, 1.19, item, transform=ax.transAxes, ha="center", va="center", fontsize=10.5, color="#c7ccd4", zorder=8)

    chart_date = work.index[-1].tz_convert(UTC).strftime("%Y-%b-%d")
    ax.text(1.0, -0.105, chart_date, transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#b9bec7")
    ax.text(1.0, -0.145, f"{timeframe.upper()} • UTC", transform=ax.transAxes, ha="right", va="top", color="#b8bdc7", fontsize=8.0, fontweight="bold")
    fig.add_artist(plt.Line2D([0.035, 0.93], [0.262, 0.262], transform=fig.transFigure, color="#34373b", linewidth=0.9))

    rows = _asset_stats_rows(symbol, quote, stats, period_perf)
    y_positions = [0.225, 0.182, 0.139]
    x_positions_text = [0.055, 0.36, 0.66]
    for ypos, row in zip(y_positions, rows):
        for xpos, (label, value) in zip(x_positions_text, row):
            fig.text(xpos, ypos, label, ha="left", va="center", fontsize=9.0, color="#9aa0a6")
            fig.text(xpos + 0.10, ypos, value, ha="left", va="center", fontsize=10.0, fontweight="bold", color="#f8fafc")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_STANDARD_DPI, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
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
        plots.extend([
            _line(enriched["RSI14"], rsi_panel, "#22d3ee", 1.05),
            _line(pd.Series(70.0, index=enriched.index), rsi_panel, "#ef4444", 0.65, "--"),
            _line(pd.Series(30.0, index=enriched.index), rsi_panel, "#22c55e", 0.65, "--"),
            _line(pd.Series(50.0, index=enriched.index), rsi_panel, "#64748b", 0.5, ":"),
        ])
    if {"MACD", "MACD_SIGNAL"}.issubset(enriched.columns):
        histogram = enriched["MACD"] - enriched["MACD_SIGNAL"]
        plots.extend([
            mpf.make_addplot(histogram.clip(lower=0), type="bar", panel=macd_panel, color="#22c55e", alpha=0.55, width=0.7),
            mpf.make_addplot(histogram.clip(upper=0), type="bar", panel=macd_panel, color="#ef4444", alpha=0.55, width=0.7),
            _line(enriched["MACD"], macd_panel, "#60a5fa", 1.0),
            _line(enriched["MACD_SIGNAL"], macd_panel, "#f59e0b", 1.0),
            _line(pd.Series(0.0, index=enriched.index), macd_panel, "#64748b", 0.5, "--"),
        ])
    ratios = [6]
    if has_volume:
        ratios.append(1.8)
    ratios.extend([2, 2])
    fig, _ = mpf.plot(
        enriched,
        type="candle",
        style=_CHART_STYLE,
        addplot=plots or None,
        volume=has_volume,
        volume_panel=volume_panel if has_volume else 0,
        panel_ratios=ratios,
        figsize=(14.0, 9.8),
        title=f"{symbol.upper()}  •  {timeframe}  •  Advanced",
        ylabel="Price",
        ylabel_lower="Volume" if has_volume else "",
        xrotation=0,
        datetime_format="%d %b\n%H:%M",
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=10000,
    )
    fig.set_dpi(_ADVANCED_DPI)
    fig.suptitle(f"{symbol.upper()}  •  {timeframe}  •  Advanced", x=0.055, y=0.985, ha="left", fontsize=15, fontweight="bold", color="#f8fafc")
    fig.subplots_adjust(top=0.94, left=0.05, right=0.96, bottom=0.07, hspace=0.08)
    fig.text(0.055, 0.018, "EMA20 / EMA50  •  Bollinger Bands  •  RSI14  •  MACD", ha="left", va="bottom", fontsize=8.0, color="#94a3b8")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_ADVANCED_DPI, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor(), edgecolor="none", pil_kwargs={"compress_level": 1})
    plt.close(fig)
    buf.seek(0)
    return buf

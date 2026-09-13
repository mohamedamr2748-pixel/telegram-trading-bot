from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from app.indicators import add_advanced_indicators, add_basic_indicators


_CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    facecolor="#111827",
    figcolor="#0b1220",
    gridcolor="#263246",
    gridstyle=":",
    gridaxis="both",
    y_on_right=True,
    rc={
        "axes.labelsize": 9,
        "axes.titlesize": 13,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "font.size": 9,
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

    keep = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in work.columns]
    work = work[keep].apply(pd.to_numeric, errors="coerce")
    work = work[~work.index.duplicated(keep="last")].sort_index()
    work = work.dropna(subset=required)

    if work.empty:
        raise ValueError("No valid OHLC data available for chart")

    if "Volume" in work.columns:
        work["Volume"] = work["Volume"].fillna(0)

    return work


def _line(series: pd.Series, panel: int, color: str, width: float = 1.0, linestyle: str = "-"):
    return mpf.make_addplot(
        series,
        panel=panel,
        color=color,
        width=width,
        linestyle=linestyle,
        secondary_y=False,
    )


def _display_index(index: pd.DatetimeIndex, symbol: str) -> pd.DatetimeIndex:
    """Use exchange-friendly local time for common US securities."""
    upper = symbol.upper()
    if upper.endswith("-USD") or upper in {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD"}:
        return index
    try:
        return index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    except TypeError:
        return index


def _infer_previous_close(series: pd.Series, timeframe: str) -> float | None:
    """Infer the previous session close when the caller did not provide it."""
    if len(series) < 2:
        return None

    upper = timeframe.upper()
    if upper.startswith("1D"):
        # A one-day intraday request usually contains only today's session.
        # Do not incorrectly label the penultimate intraday point as prev close.
        return None

    if upper.startswith("5D"):
        dates = pd.Series(series.index.date, index=series.index)
        unique_dates = list(dict.fromkeys(dates.tolist()))
        if len(unique_dates) >= 2:
            previous_day = unique_dates[-2]
            previous = series[dates == previous_day]
            if not previous.empty:
                return float(previous.iloc[-1])
        return None

    return float(series.iloc[-2])


async def render_google_finance_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
) -> io.BytesIO:
    """Render a compact Google Finance-style price chart from market data."""
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

    display_index = _display_index(work.index, symbol)
    series = pd.Series(work["Close"].to_numpy(dtype=float), index=display_index)
    last_price = price if price is not None else float(series.iloc[-1])
    previous = prev_close if prev_close is not None else _infer_previous_close(series, timeframe)
    if change_percent is None and previous and previous > 0:
        change_percent = (last_price / previous - 1.0) * 100.0

    currency_text = f" {currency}" if currency else ""

    fig, ax = plt.subplots(figsize=(12.8, 7.1), dpi=160, facecolor="#0b1220")
    ax.set_facecolor("#36383f")

    x = series.index.to_pydatetime()
    y = series.to_numpy(dtype=float)
    baseline = float(min(y.min(), previous if previous and previous > 0 else y.min()))
    ceiling = float(max(y.max(), previous if previous and previous > 0 else y.max()))
    spread = ceiling - baseline
    padding = max(spread * 0.22, abs(last_price) * 0.0025, 0.01)
    chart_bottom = baseline - padding
    chart_top = ceiling + padding

    positive = change_percent is None or change_percent >= 0
    line_color = "#81c995" if positive else "#f28b82"
    muted = "#b8bdc7"

    ax.plot(x, y, linewidth=2.4, color=line_color, solid_capstyle="round", zorder=4)
    ax.fill_between(x, y, chart_bottom, color=line_color, alpha=0.10, zorder=1)

    if previous is not None and previous > 0:
        ax.axhline(previous, linewidth=1.0, linestyle=(0, (1.5, 4)), color="#c3c7cf", alpha=0.7, zorder=2)
        ax.text(
            1.005,
            previous,
            f"Prev\nclose\n{previous:.6g}",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=8,
            color="#d4d7dd",
            linespacing=1.05,
        )

    ax.scatter([x[-1]], [y[-1]], s=42, color=line_color, edgecolor="#36383f", linewidth=1.2, zorder=6)
    ax.set_ylim(chart_bottom, chart_top)

    ax.grid(axis="y", color="#5a5e66", linestyle="-", linewidth=0.7, alpha=0.42)
    ax.grid(axis="x", visible=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#d0d3da", labelsize=8, length=0, pad=8)
    ax.yaxis.tick_right()

    locator = mdates.AutoDateLocator(minticks=4, maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    price_line = f"{last_price:.6g}{currency_text}"
    if change_percent is not None:
        price_line += f"  {change_percent:+.2f}%"
    ax.set_title(
        f"{symbol.upper()}\n{price_line}",
        loc="left",
        color="#f8fafc",
        fontsize=18,
        fontweight="bold",
        pad=14,
        linespacing=1.25,
    )
    ax.text(
        1.0,
        1.075,
        timeframe.upper(),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        color="#b8bdc7",
        fontsize=8,
        fontweight="bold",
    )

    fig.subplots_adjust(left=0.035, right=0.90, top=0.79, bottom=0.16)
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=160,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
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
) -> io.BytesIO:
    """Render the standard Google Finance-style chart or the technical chart."""
    if not advanced:
        return await render_google_finance_chart(
            df,
            symbol,
            timeframe,
            prev_close=prev_close,
            price=price,
            currency=currency,
            change_percent=change_percent,
        )

    work = _clean_ohlcv(df)
    enriched = add_advanced_indicators(work)

    has_volume = "Volume" in enriched.columns
    volume_panel = 1 if has_volume else None
    rsi_panel = 2 if has_volume else 1
    macd_panel = rsi_panel + 1

    plots = []
    if "EMA20" in enriched:
        plots.append(_line(enriched["EMA20"], 0, "#38bdf8", 1.15))
    if "EMA50" in enriched:
        plots.append(_line(enriched["EMA50"], 0, "#f59e0b", 1.15))
    if "BB_UPPER" in enriched:
        plots.append(_line(enriched["BB_UPPER"], 0, "#a78bfa", 0.9))
    if "BB_MID" in enriched:
        plots.append(_line(enriched["BB_MID"], 0, "#94a3b8", 0.7, "--"))
    if "BB_LOWER" in enriched:
        plots.append(_line(enriched["BB_LOWER"], 0, "#a78bfa", 0.9))

    if "RSI14" in enriched:
        plots.extend(
            [
                _line(enriched["RSI14"], rsi_panel, "#22d3ee", 1.05),
                _line(pd.Series(70.0, index=enriched.index), rsi_panel, "#ef4444", 0.65, "--"),
                _line(pd.Series(30.0, index=enriched.index), rsi_panel, "#22c55e", 0.65, "--"),
                _line(pd.Series(50.0, index=enriched.index), rsi_panel, "#64748b", 0.5, ":"),
            ]
        )

    if {"MACD", "MACD_SIGNAL"}.issubset(enriched.columns):
        histogram = enriched["MACD"] - enriched["MACD_SIGNAL"]
        plots.extend(
            [
                mpf.make_addplot(histogram.clip(lower=0), type="bar", panel=macd_panel, color="#22c55e", alpha=0.55, width=0.7),
                mpf.make_addplot(histogram.clip(upper=0), type="bar", panel=macd_panel, color="#ef4444", alpha=0.55, width=0.7),
                _line(enriched["MACD"], macd_panel, "#60a5fa", 1.0),
                _line(enriched["MACD_SIGNAL"], macd_panel, "#f59e0b", 1.0),
                _line(pd.Series(0.0, index=enriched.index), macd_panel, "#64748b", 0.5, "--"),
            ]
        )

    ratios = [6]
    if has_volume:
        ratios.append(1.8)
    ratios.extend([2, 2])

    buf = io.BytesIO()
    fig, _ = mpf.plot(
        enriched,
        type="candle",
        style=_CHART_STYLE,
        addplot=plots or None,
        volume=has_volume,
        volume_panel=volume_panel if has_volume else 0,
        panel_ratios=ratios,
        figsize=(12.5, 8.8),
        title=f"{symbol.upper()}  •  {timeframe}  •  Advanced",
        ylabel="Price",
        ylabel_lower="Volume" if has_volume else "",
        xrotation=0,
        datetime_format="%d %b\n%H:%M",
        tight_layout=True,
        returnfig=True,
    )

    fig.suptitle(
        f"{symbol.upper()}  •  {timeframe}  •  Advanced",
        x=0.055,
        y=0.985,
        ha="left",
        fontsize=14,
        fontweight="bold",
        color="#f8fafc",
    )
    fig.subplots_adjust(top=0.94, left=0.05, right=0.96, bottom=0.07, hspace=0.08)
    fig.text(
        0.055,
        0.018,
        "EMA20 / EMA50  •  Bollinger Bands  •  RSI14  •  MACD",
        ha="left",
        va="bottom",
        fontsize=7.5,
        color="#94a3b8",
    )
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

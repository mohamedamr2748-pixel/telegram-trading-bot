from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from app.indicators import add_advanced_indicators, add_basic_indicators
from config import settings


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


async def render_google_finance_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
) -> io.BytesIO:
    """Render a compact Google Finance-style chart from Google Finance price points."""
    if "Close" not in df.columns:
        raise ValueError("Google Finance chart requires a Close/price series")

    work = df.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    work["Close"] = pd.to_numeric(work["Close"], errors="coerce")
    work = work.dropna(subset=["Close"]).sort_index()
    work = work[~work.index.duplicated(keep="last")]
    if work.empty:
        raise ValueError("No valid price points available for chart")

    if len(work) > 2500:
        work = work.iloc[-2500:]

    series = work["Close"]
    last_price = price if price is not None else float(series.iloc[-1])
    currency_text = f" {currency}" if currency else ""
    move_text = f"  {change_percent:+.2f}%" if change_percent is not None else ""

    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=160, facecolor="#0b1220")
    ax.set_facecolor("#111827")

    x = series.index.to_pydatetime()
    y = series.to_numpy(dtype=float)
    line_color = "#60a5fa"
    fill_color = "#60a5fa"
    muted = "#94a3b8"

    ax.plot(x, y, linewidth=2.0, color=line_color, solid_capstyle="round")
    ax.fill_between(x, y, y.min(), color=fill_color, alpha=0.08)

    if prev_close is not None and prev_close > 0:
        ax.axhline(prev_close, linewidth=0.9, linestyle=(0, (2, 3)), color=muted, alpha=0.85)

    ax.scatter([x[-1]], [y[-1]], s=28, color=line_color, zorder=5)
    ax.annotate(
        f"{last_price:.6g}{currency_text}",
        xy=(x[-1], y[-1]),
        xytext=(-8, 12),
        textcoords="offset points",
        ha="right",
        va="bottom",
        fontsize=9,
        color="#f8fafc",
        bbox={"boxstyle": "round,pad=0.28", "fc": "#1f2937", "ec": "#334155", "alpha": 0.95},
    )

    ax.grid(axis="y", color="#263246", linestyle=":", linewidth=0.8)
    ax.grid(axis="x", visible=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=muted, labelsize=8, length=0)
    ax.yaxis.tick_right()

    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_title(
        f"{symbol.upper()}  •  {last_price:.6g}{currency_text}{move_text}",
        loc="left",
        color="#f8fafc",
        fontsize=15,
        fontweight="bold",
        pad=16,
    )
    ax.text(0.0, 1.015, timeframe.upper(), transform=ax.transAxes, ha="left", va="bottom", color=muted, fontsize=8)
    if prev_close is not None and prev_close > 0:
        ax.text(
            0.99,
            0.03,
            f"Prev close  {prev_close:.6g}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            color=muted,
            fontsize=8,
        )

    fig.subplots_adjust(left=0.045, right=0.945, top=0.84, bottom=0.12)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
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
    """Render the configured chart style.

    When Google Finance is enabled, its normalized price series is rendered in
    the Google Finance-style line/area format. Otherwise the existing technical
    candlestick renderer remains available.
    """
    if settings.google_finance_enabled:
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
    enriched = add_advanced_indicators(work) if advanced else add_basic_indicators(work)

    has_volume = "Volume" in enriched.columns
    volume_panel = 1 if has_volume else None
    rsi_panel = 2 if has_volume else 1
    macd_panel = rsi_panel + 1

    plots = []
    if "EMA20" in enriched:
        plots.append(_line(enriched["EMA20"], 0, "#38bdf8", 1.15))
    if "EMA50" in enriched:
        plots.append(_line(enriched["EMA50"], 0, "#f59e0b", 1.15))

    if advanced:
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

    if advanced and {"MACD", "MACD_SIGNAL"}.issubset(enriched.columns):
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
    ratios.append(2)
    if advanced:
        ratios.append(2)

    buf = io.BytesIO()
    fig, _ = mpf.plot(
        enriched,
        type="candle",
        style=_CHART_STYLE,
        addplot=plots or None,
        volume=has_volume,
        volume_panel=volume_panel if has_volume else 0,
        panel_ratios=ratios,
        figsize=(12.5, 8.8 if advanced else 7.4),
        title=f"{symbol.upper()}  •  {timeframe}" + ("  •  Advanced" if advanced else ""),
        ylabel="Price",
        ylabel_lower="Volume" if has_volume else "",
        xrotation=0,
        datetime_format="%d %b\n%H:%M",
        tight_layout=True,
        returnfig=True,
    )

    fig.suptitle(
        f"{symbol.upper()}  •  {timeframe}" + ("  •  Advanced" if advanced else ""),
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
        "EMA20 / EMA50" + ("  •  Bollinger Bands  •  RSI14  •  MACD" if advanced else "  •  RSI14"),
        ha="left",
        va="bottom",
        fontsize=7.5,
        color="#94a3b8",
    )
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

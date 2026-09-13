from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
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


async def render_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    advanced: bool = False,
) -> io.BytesIO:
    work = _clean_ohlcv(df)
    enriched = add_advanced_indicators(work) if advanced else add_basic_indicators(work)

    has_volume = "Volume" in enriched.columns
    volume_panel = 1 if has_volume else None
    rsi_panel = 2 if has_volume else 1
    macd_panel = rsi_panel + 1

    plots = []

    # Price panel: trend overlays.
    if "EMA20" in enriched:
        plots.append(_line(enriched["EMA20"], 0, "#38bdf8", 1.15))
    if "EMA50" in enriched:
        plots.append(_line(enriched["EMA50"], 0, "#f59e0b", 1.15))

    # Advanced price overlay: volatility bands.
    if advanced:
        if "BB_UPPER" in enriched:
            plots.append(_line(enriched["BB_UPPER"], 0, "#a78bfa", 0.9))
        if "BB_MID" in enriched:
            plots.append(_line(enriched["BB_MID"], 0, "#94a3b8", 0.7, "--"))
        if "BB_LOWER" in enriched:
            plots.append(_line(enriched["BB_LOWER"], 0, "#a78bfa", 0.9))

    # Volume is plotted by mplfinance itself. RSI gets its own panel.
    if "RSI14" in enriched:
        plots.extend(
            [
                _line(enriched["RSI14"], rsi_panel, "#22d3ee", 1.05),
                _line(pd.Series(70.0, index=enriched.index), rsi_panel, "#ef4444", 0.65, "--"),
                _line(pd.Series(30.0, index=enriched.index), rsi_panel, "#22c55e", 0.65, "--"),
                _line(pd.Series(50.0, index=enriched.index), rsi_panel, "#64748b", 0.5, ":"),
            ]
        )

    # Advanced tier: MACD line, signal and histogram.
    if advanced and {"MACD", "MACD_SIGNAL"}.issubset(enriched.columns):
        histogram = enriched["MACD"] - enriched["MACD_SIGNAL"]
        plots.extend(
            [
                mpf.make_addplot(
                    histogram.clip(lower=0),
                    type="bar",
                    panel=macd_panel,
                    color="#22c55e",
                    alpha=0.55,
                    width=0.7,
                ),
                mpf.make_addplot(
                    histogram.clip(upper=0),
                    type="bar",
                    panel=macd_panel,
                    color="#ef4444",
                    alpha=0.55,
                    width=0.7,
                ),
                _line(enriched["MACD"], macd_panel, "#60a5fa", 1.0),
                _line(enriched["MACD_SIGNAL"], macd_panel, "#f59e0b", 1.0),
                _line(pd.Series(0.0, index=enriched.index), macd_panel, "#64748b", 0.5, "--"),
            ]
        )

    panel_count = 1 + (1 if has_volume else 0) + 1 + (1 if advanced else 0)
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

    # Small footer keeps the chart self-explanatory in Telegram.
    fig.text(
        0.055,
        0.018,
        "EMA20 / EMA50" + ("  •  Bollinger Bands  •  RSI14  •  MACD" if advanced else "  •  RSI14"),
        ha="left",
        va="bottom",
        fontsize=7.5,
        color="#94a3b8",
    )

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

from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd

from app.indicators import add_advanced_indicators, add_basic_indicators


async def render_chart(df: pd.DataFrame, symbol: str, timeframe: str, advanced: bool = False) -> io.BytesIO:
    work = df.copy()
    work.index = pd.to_datetime(work.index)
    work = work[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in work.columns]].dropna(subset=["Open", "High", "Low", "Close"])
    enriched = add_advanced_indicators(work) if advanced else add_basic_indicators(work)
    plots = []
    for column in (["EMA20", "EMA50"] if not advanced else ["EMA20", "EMA50", "BB_UPPER", "BB_LOWER"]):
        if column in enriched:
            plots.append(mpf.make_addplot(enriched[column], width=0.9))

    buf = io.BytesIO()
    mpf.plot(
        enriched,
        type="candle",
        volume="Volume" in enriched.columns,
        addplot=plots or None,
        title=f"{symbol.upper()} • {timeframe}",
        style="yahoo",
        figsize=(12, 7),
        savefig=dict(fname=buf, dpi=140, bbox_inches="tight", pad_inches=0.2),
    )
    buf.seek(0)
    return buf

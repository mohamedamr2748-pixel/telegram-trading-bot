from __future__ import annotations

import pandas as pd


def _period_change(df: pd.DataFrame, timeframe: str) -> float | None:
    """Return the return across the displayed chart period."""
    upper = str(timeframe).upper()
    if upper.startswith("1D"):
        return None
    if "Close" not in df.columns:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 2:
        return None
    first = float(close.iloc[0])
    last = float(close.iloc[-1])
    if first == 0:
        return None
    return (last / first - 1.0) * 100.0


def install() -> None:
    """Make the chart colour and headline return reflect the selected period."""
    from app import charts

    if getattr(charts, "_period_performance_installed", False):
        return

    original_render = charts.render_google_finance_chart

    async def render_with_period_performance(*args, **kwargs):
        df = args[0] if args else kwargs.get("df")
        timeframe = args[2] if len(args) > 2 else kwargs.get("timeframe", "")
        performance = _period_change(df, str(timeframe)) if isinstance(df, pd.DataFrame) else None
        if performance is not None:
            if len(args) >= 7:
                mutable = list(args)
                mutable[6] = performance
                args = tuple(mutable)
            else:
                kwargs["change_percent"] = performance
        return await original_render(*args, **kwargs)

    charts.render_google_finance_chart = render_with_period_performance
    charts._period_performance_installed = True

from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch

from app.chart_timestamps import configure_price_x_axis, timeframe_key
from app.domain import MarketQuote


# Keep the existing implementation available under a private module name.  The
# new package is intentionally a compatibility layer so callers importing
# ``app.charts`` do not need to change while the price timestamp system is
# rebuilt independently.
_LEGACY_PATH = Path(__file__).resolve().parent.parent / "charts.py"
_LEGACY_SPEC = importlib.util.spec_from_file_location("app._legacy_charts", _LEGACY_PATH)
if _LEGACY_SPEC is None or _LEGACY_SPEC.loader is None:
    raise ImportError(f"Unable to load legacy chart module: {_LEGACY_PATH}")
_LEGACY = importlib.util.module_from_spec(_LEGACY_SPEC)
_LEGACY_SPEC.loader.exec_module(_LEGACY)

_SKIP_LEGACY = {
    "__name__", "__loader__", "__package__", "__spec__", "__file__", "__cached__", "__builtins__"
}
for _name, _value in vars(_LEGACY).items():
    if _name not in _SKIP_LEGACY:
        globals().setdefault(_name, _value)


def _call_legacy(function_name: str, *args, **kwargs):
    """Call a legacy async renderer while honouring package-level monkeypatches."""
    function = getattr(_LEGACY, function_name)
    overridden = []
    for name in ("_plot_session_coloured_line", "_configure_us_equity_x_axis"):
        package_value = globals().get(name)
        legacy_value = getattr(_LEGACY, name, None)
        if package_value is not None and package_value is not legacy_value:
            overridden.append((name, legacy_value))
            setattr(_LEGACY, name, package_value)
    try:
        return function(*args, **kwargs)
    finally:
        for name, legacy_value in overridden:
            setattr(_LEGACY, name, legacy_value)


def _render_price_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
    quote: MarketQuote | None = None,
):
    """Render a basic price chart using the rebuilt timestamp contract."""
    work = _LEGACY._prepare_price_series(df)

    if quote is not None:
        price = quote.price if price is None else price
        currency = currency or (
            "USD"
            if quote.asset_class in {"stock", "index", "commodity", "metal", "forex", "market"}
            else None
        )
        if prev_close is None and quote.previous_close is not None:
            prev_close = quote.previous_close
        if prev_close and prev_close > 0 and price is not None:
            change_percent = (price / prev_close - 1.0) * 100.0
        elif change_percent is None:
            change_percent = quote.change_percent

    key = timeframe_key(timeframe)
    last_price = float(price) if price is not None else float(work["Close"].iloc[-1])
    previous = float(prev_close) if prev_close and prev_close > 0 else None
    first_close = float(work["Close"].iloc[0])

    if key == "1D":
        if change_percent is None and previous is not None:
            change_percent = (last_price / previous - 1.0) * 100.0
        elif change_percent is None and first_close > 0 and len(work) >= 2:
            change_percent = (last_price / first_close - 1.0) * 100.0
    else:
        if first_close > 0:
            change_percent = (last_price / first_close - 1.0) * 100.0
        previous = first_close

    period_perf = _LEGACY._period_performance(work["Close"], key, change_percent)
    line_color = _LEGACY._change_colour(period_perf)
    stats = _LEGACY._session_stats(work, symbol)
    digits = _LEGACY._price_digits(symbol, quote)
    currency_text = "" if _LEGACY._is_index_symbol(symbol) else (f" {currency}" if currency else "")

    fig = plt.figure(
        figsize=_LEGACY._STANDARD_FIGSIZE,
        dpi=_LEGACY._STANDARD_DPI,
        facecolor="#202124",
    )
    ax = fig.add_axes([0.035, 0.30, 0.865, 0.56])
    ax.set_facecolor("#202124")

    y = work["Close"].to_numpy(dtype=float)
    baseline = float(min(y.min(), previous if previous is not None else y.min()))
    ceiling = float(max(y.max(), previous if previous is not None else y.max()))
    spread = ceiling - baseline
    padding = max(spread * 0.22, abs(last_price) * 0.0025, 0.01)
    chart_bottom, chart_top = baseline - padding, ceiling + padding

    x = work.index.to_pydatetime()
    ax.plot(
        x,
        y,
        linewidth=2.55,
        color=line_color,
        solid_capstyle="round",
        solid_joinstyle="round",
        antialiased=True,
        zorder=4,
    )
    ax.fill_between(x, y, chart_bottom, color=line_color, alpha=0.11, zorder=1, antialiased=True)
    ax.scatter(
        [x[-1]],
        [y[-1]],
        s=50,
        color=line_color,
        edgecolor="#202124",
        linewidth=1.5,
        zorder=6,
        antialiased=True,
    )

    if previous is not None:
        ax.axhline(
            previous,
            linewidth=1.0,
            linestyle=(0, (5, 6)),
            color="#e4e7eb",
            alpha=0.85,
            zorder=2,
        )
        ax.text(
            1.002,
            previous,
            f"Prev close\n{_LEGACY._fmt_value(previous, digits)}",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=8.5,
            color="#d5d8de",
            linespacing=1.08,
        )

    ax.set_ylim(chart_bottom, chart_top)
    ax.grid(axis="y", color="#34373b", linestyle="-", linewidth=0.65, alpha=0.75)
    ax.grid(axis="x", color="#34373b", linestyle="--", linewidth=0.55, alpha=0.55)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#d7dbe2", labelsize=8.5, length=0, pad=8)
    ax.yaxis.tick_right()

    configure_price_x_axis(ax, key, work.index)

    price_line = f"{_LEGACY._fmt_value(last_price, digits)}{currency_text}"
    if period_perf is not None:
        price_line += f"  {period_perf:+.2f}%"
    ax.text(
        0.0,
        1.19,
        symbol.upper(),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=20,
        fontweight="bold",
        color="#f8fafc",
    )
    ax.text(
        0.0,
        1.065,
        price_line,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=18,
        fontweight="bold",
        color=_LEGACY._change_colour(period_perf),
    )

    selector = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y"]
    selected = _LEGACY._selector_key(key)
    start_x, step = 0.67, 0.047
    for idx, item in enumerate(selector):
        xpos = start_x + idx * step
        if item == selected:
            pill = FancyBboxPatch(
                (xpos - 0.020, 1.145),
                0.040,
                0.085,
                boxstyle="round,pad=0.008,rounding_size=0.018",
                transform=ax.transAxes,
                linewidth=0,
                facecolor="#30343a",
                edgecolor="none",
                zorder=8,
            )
            ax.add_patch(pill)
            ax.text(
                xpos,
                1.19,
                item,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10.5,
                fontweight="bold",
                color="#f8fafc",
                zorder=9,
            )
        else:
            ax.text(
                xpos,
                1.19,
                item,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10.5,
                color="#c7ccd4",
                zorder=8,
            )

    chart_date = work.index[-1].tz_convert("UTC").strftime("%Y-%b-%d")
    ax.text(
        1.0,
        -0.105,
        chart_date,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        color="#b9bec7",
    )
    ax.text(
        1.0,
        -0.145,
        f"{key} • UTC",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color="#b8bdc7",
        fontsize=8.0,
        fontweight="bold",
    )
    fig.add_artist(
        plt.Line2D(
            [0.035, 0.93],
            [0.262, 0.262],
            transform=fig.transFigure,
            color="#34373b",
            linewidth=0.9,
        )
    )

    rows = _LEGACY._asset_stats_rows(symbol, quote, stats, period_perf)
    y_positions = [0.225, 0.182, 0.139]
    x_positions_text = [0.055, 0.36, 0.66]
    for ypos, row in zip(y_positions, rows):
        for xpos, (label, value) in zip(x_positions_text, row):
            fig.text(xpos, ypos, label, ha="left", va="center", fontsize=9.0, color="#9aa0a6")
            fig.text(
                xpos + 0.10,
                ypos,
                value,
                ha="left",
                va="center",
                fontsize=10.0,
                fontweight="bold",
                color="#f8fafc",
            )

    buf = _LEGACY.io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=_LEGACY._STANDARD_DPI,
        bbox_inches="tight",
        pad_inches=0.08,
        facecolor=fig.get_facecolor(),
        edgecolor="none",
        pil_kwargs={"compress_level": 1},
    )
    plt.close(fig)
    buf.seek(0)
    return buf


async def render_google_finance_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    prev_close: float | None = None,
    price: float | None = None,
    currency: str | None = None,
    change_percent: float | None = None,
    quote: MarketQuote | None = None,
):
    """Compatibility wrapper: /chart keeps the legacy session renderer; price charts use the new timestamp engine."""
    if _LEGACY._is_session_intraday_chart(timeframe):
        return await _call_legacy(
            "render_google_finance_chart",
            df,
            symbol,
            timeframe,
            prev_close=prev_close,
            price=price,
            currency=currency,
            change_percent=change_percent,
            quote=quote,
        )
    return await _render_price_chart(
        df,
        symbol,
        timeframe,
        prev_close=prev_close,
        price=price,
        currency=currency,
        change_percent=change_percent,
        quote=quote,
    )


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
):
    """Public renderer used by the bot.

    /price timeframe buttons use the rebuilt timestamp system. The standalone
    /chart 1d/15m session renderer and advanced charts continue using the
    existing implementation.
    """
    if advanced or _LEGACY._is_session_intraday_chart(timeframe):
        return await _call_legacy(
            "render_chart",
            df,
            symbol,
            timeframe,
            advanced=advanced,
            prev_close=prev_close,
            price=price,
            currency=currency,
            change_percent=change_percent,
            quote=quote,
        )
    return await _render_price_chart(
        df,
        symbol,
        timeframe,
        prev_close=prev_close,
        price=price,
        currency=currency,
        change_percent=change_percent,
        quote=quote,
    )


# Keep the rebuilt helper available to tests and downstream code that imports
# it directly from app.charts.
_configure_price_x_axis = configure_price_x_axis

__all__ = [name for name in globals() if not name.startswith("__")]

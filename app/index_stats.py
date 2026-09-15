"""Index-specific chart statistics without placeholder n/a fields."""
from __future__ import annotations

from typing import Any

from app.domain import MarketQuote


def _index_rows(
    symbol: str,
    quote: MarketQuote | None,
    stats: dict[str, str],
    change_percent: float | None,
    *,
    fmt_value: Any,
    fmt_percent: Any,
    status_text: Any,
) -> list[list[tuple[str, str]]]:
    """Return useful index metrics using values already supplied by the quote/chart."""
    previous = fmt_value(quote.previous_close) if quote and quote.previous_close is not None else "—"
    year_high = fmt_value(quote.year_high) if quote and quote.year_high is not None else "—"
    year_low = fmt_value(quote.year_low) if quote and quote.year_low is not None else "—"
    day_change = fmt_percent(change_percent) if change_percent is not None else "—"
    session = status_text(quote)
    volume = stats.get("Volume") or "0"
    return [
        [("Open", stats["Open"]), ("Volume", volume), ("Previous", previous)],
        [("High", stats["High"]), ("52-wk high", year_high), ("52-wk low", year_low)],
        [("Low", stats["Low"]), ("Day change", day_change), ("Session", session)],
    ]


def install(charts_module: Any) -> None:
    """Install the index-specific statistics formatter into the chart renderer."""
    original = charts_module._asset_stats_rows

    def asset_stats_rows(symbol: str, quote: MarketQuote | None, stats: dict[str, str], change_percent: float | None):
        asset = (quote.asset_class if quote else "stock").lower()
        if asset == "index":
            return _index_rows(
                symbol,
                quote,
                stats,
                change_percent,
                fmt_value=charts_module._fmt_value,
                fmt_percent=charts_module._fmt_percent,
                status_text=charts_module._status_text,
            )
        return original(symbol, quote, stats, change_percent)

    charts_module._asset_stats_rows = asset_stats_rows

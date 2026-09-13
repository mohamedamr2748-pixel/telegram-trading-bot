from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pandas as pd
import yfinance as yf

from app.domain import MarketQuote
from app.market import MarketService, YFinanceProvider


_FOREX_SYMBOLS = {
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "USDEUR", "USDGBP", "JPYUSD", "USDAUD", "AUUSD", "CADUSD", "CHFUSD", "USDNZD",
}


def _inverse(value: float | None) -> float | None:
    return 1.0 / value if value is not None and value > 0 else None


def _invert_high_low(frame: pd.DataFrame) -> tuple[float | None, float | None]:
    if "High" not in frame.columns or "Low" not in frame.columns:
        return None, None
    high = pd.to_numeric(frame["High"], errors="coerce").dropna()
    low = pd.to_numeric(frame["Low"], errors="coerce").dropna()
    if high.empty or low.empty:
        return None, None
    # For an inverse FX pair, the largest inverse value comes from the
    # smallest value of the original pair, and vice versa.
    return _inverse(float(low.min())), _inverse(float(high.max()))


def _history_metadata(symbol: str) -> dict[str, float | None]:
    user_symbol = symbol.strip().upper()
    normalized, inverse = YFinanceProvider._normalize_pair(user_symbol)
    yf_symbol = YFinanceProvider._history_symbol(user_symbol)
    frame = yf.Ticker(yf_symbol).history(period="1y", interval="1d", auto_adjust=False)
    if frame.empty or "Close" not in frame.columns:
        return {}

    frame = frame.copy()
    for column in ("Open", "High", "Low", "Close"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Close"]).sort_index()
    if frame.empty:
        return {}

    if inverse:
        closes = frame["Close"].apply(_inverse).dropna()
        previous = _inverse(float(frame["Close"].iloc[-2])) if len(frame) >= 2 else None
        year_high, year_low = _invert_high_low(frame)
    else:
        closes = frame["Close"].dropna()
        previous = float(frame["Close"].iloc[-2]) if len(frame) >= 2 else None
        year_high = float(frame["High"].dropna().max()) if "High" in frame and not frame["High"].dropna().empty else None
        year_low = float(frame["Low"].dropna().min()) if "Low" in frame and not frame["Low"].dropna().empty else None

    return {
        "previous_close": previous,
        "year_high": year_high,
        "year_low": year_low,
    }


_original_get_quote: Callable[..., Awaitable[MarketQuote]] | None = None


async def _enriched_get_quote(self: MarketService, symbol: str) -> MarketQuote:
    assert _original_get_quote is not None
    quote = await _original_get_quote(self, symbol)
    user_symbol = symbol.strip().upper()
    if quote.asset_class != "forex" and user_symbol not in _FOREX_SYMBOLS:
        return quote

    # BiQuote is intentionally the preferred live FX source. Its response
    # can omit historical metadata, so fill only missing fields from Yahoo's
    # daily history without replacing the live price/source.
    missing_metadata = (
        quote.previous_close is None
        or quote.year_high is None
        or quote.year_low is None
    )
    if not missing_metadata:
        return quote

    try:
        metadata = await asyncio.to_thread(_history_metadata, user_symbol)
    except Exception:
        return quote

    if quote.previous_close is None:
        quote.previous_close = metadata.get("previous_close")
    if quote.year_high is None:
        quote.year_high = metadata.get("year_high")
    if quote.year_low is None:
        quote.year_low = metadata.get("year_low")

    if quote.previous_close and quote.previous_close > 0:
        quote.change = quote.price - quote.previous_close
        quote.change_percent = quote.change / quote.previous_close * 100.0

    return quote


def install_market_enrichment() -> None:
    global _original_get_quote
    if _original_get_quote is not None:
        return
    _original_get_quote = MarketService.get_quote
    MarketService.get_quote = _enriched_get_quote  # type: ignore[method-assign]

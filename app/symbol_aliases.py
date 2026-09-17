from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.domain import MarketQuote
from app.market import MarketService


_SYMBOL_ALIASES = {
    "SP500": "^GSPC",
    "SPX": "^GSPC",
    "S&P500": "^GSPC",
    "S&P500INDEX": "^GSPC",
    "NASDAQ100": "^NDX",
    "NASDAQ": "^IXIC",
    "NASDAQCOMPOSITE": "^IXIC",
    "DOW": "^DJI",
    "DOWJONES": "^DJI",
    "GOLD": "GC=F",
}


def canonical_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    compact = re.sub(r"[\s-]+", "", raw)
    return _SYMBOL_ALIASES.get(compact, raw)


_original_get_quote: Callable[..., Awaitable[MarketQuote]] | None = None
_original_get_history: Callable[..., Awaitable[object]] | None = None


async def _aliased_get_quote(self: MarketService, symbol: str) -> MarketQuote:
    assert _original_get_quote is not None
    user_symbol = symbol.strip().upper()
    quote = await _original_get_quote(self, canonical_symbol(user_symbol))
    quote.symbol = user_symbol
    return quote


async def _aliased_get_history(self: MarketService, symbol: str, period: str = "1mo", interval: str = "1d"):
    assert _original_get_history is not None
    return await _original_get_history(self, canonical_symbol(symbol), period=period, interval=interval)


def install_symbol_aliases() -> None:
    global _original_get_quote, _original_get_history
    if _original_get_quote is not None:
        return
    _original_get_quote = MarketService.get_quote
    _original_get_history = MarketService.get_history
    MarketService.get_quote = _aliased_get_quote  # type: ignore[method-assign]
    MarketService.get_history = _aliased_get_history  # type: ignore[method-assign]

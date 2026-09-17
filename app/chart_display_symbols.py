"""User-facing chart labels for canonical market-data symbols."""
from __future__ import annotations

_DISPLAY_SYMBOLS = {
    "^GSPC": "S&P 500",
    "SP500": "S&P 500",
    "SPX": "S&P 500",
    "S&P500": "S&P 500",
    "S&P500INDEX": "S&P 500",
    "^NDX": "NASDAQ-100",
    "NASDAQ100": "NASDAQ-100",
    "NASDAQ-100": "NASDAQ-100",
    "^IXIC": "NASDAQ Composite",
    "NASDAQ": "NASDAQ Composite",
    "NASDAQCOMPOSITE": "NASDAQ Composite",
    "^DJI": "Dow Jones",
    "DOW": "Dow Jones",
    "DOWJONES": "Dow Jones",
    "GC=F": "Gold",
    "GOLD": "Gold",
}


def chart_display_symbol(symbol: str) -> str:
    """Keep provider symbols internal while using friendly display labels."""
    raw = symbol.strip().upper()
    return _DISPLAY_SYMBOLS.get(raw, raw)

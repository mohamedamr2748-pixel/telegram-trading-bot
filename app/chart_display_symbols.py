"""User-facing chart labels for canonical market-data symbols."""
from __future__ import annotations

_DISPLAY_SYMBOLS = {
    "^GSPC": "SP500",
    "^NDX": "NASDAQ100",
    "^IXIC": "NASDAQ",
    "^DJI": "DOWJONES",
}


def chart_display_symbol(symbol: str) -> str:
    """Keep provider symbols internal while using friendly chart labels."""
    raw = symbol.strip().upper()
    return _DISPLAY_SYMBOLS.get(raw, raw)

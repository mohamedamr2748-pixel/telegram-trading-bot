"""User-facing chart labels and input aliases for market symbols."""
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

# Common user-facing aliases are converted to one canonical provider symbol
# before /price requests quote and history data. This keeps aliases such as
# BTC, BTC/USD and BTC-USD on the exact same market-data path as BTCUSD.
_INPUT_SYMBOL_ALIASES = {
    "BTC": "BTCUSD",
    "BTC/USD": "BTCUSD",
    "BTC-USD": "BTCUSD",
    "ETH": "ETHUSD",
    "ETH/USD": "ETHUSD",
    "ETH-USD": "ETHUSD",
    "SOL": "SOLUSD",
    "SOL/USD": "SOLUSD",
    "SOL-USD": "SOLUSD",
    "XRP": "XRPUSD",
    "XRP/USD": "XRPUSD",
    "XRP-USD": "XRPUSD",
    "BNB": "BNBUSD",
    "BNB/USD": "BNBUSD",
    "BNB-USD": "BNBUSD",
    "XAU": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "XAU-USD": "XAUUSD",
    "XAG": "XAGUSD",
    "XAG/USD": "XAGUSD",
    "XAG-USD": "XAGUSD",
}


def normalise_market_symbol(symbol: str) -> str:
    """Return the canonical provider symbol for common user input aliases."""
    raw = symbol.strip().upper()
    return _INPUT_SYMBOL_ALIASES.get(raw, raw)


def chart_display_symbol(symbol: str) -> str:
    """Keep provider symbols internal while using friendly display labels."""
    raw = symbol.strip().upper()
    return _DISPLAY_SYMBOLS.get(raw, raw)

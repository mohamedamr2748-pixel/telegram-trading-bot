from __future__ import annotations

from app.market import YFinanceProvider


# User-facing crypto pairs remain unchanged. The provider history symbol is
# resolved internally, and inverse pairs are returned in the user's direction.
_CRYPTO_HISTORY_SYMBOLS = {
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "SOLUSD": "SOL-USD",
    "XRPUSD": "XRP-USD",
    "BNBUSD": "BNB-USD",
}
_INVERSE_CRYPTO_PAIRS = {
    "USDBTC": "BTCUSD",
    "USDETH": "ETHUSD",
    "USDSOL": "SOLUSD",
    "USDXRP": "XRPUSD",
    "USDBNB": "BNBUSD",
}

_original_normalize_pair = YFinanceProvider._normalize_pair
_original_history_symbol = YFinanceProvider._history_symbol
_installed = False


def _normalize_pair_with_crypto(cls, symbol: str) -> tuple[str, bool]:
    normalized = symbol.strip().upper().replace("/", "").replace("-", "")
    if normalized in _CRYPTO_HISTORY_SYMBOLS:
        return normalized, False
    inverse_base = _INVERSE_CRYPTO_PAIRS.get(normalized)
    if inverse_base:
        return inverse_base, True
    return _original_normalize_pair(symbol)


def _history_symbol_with_crypto(cls, symbol: str) -> str:
    normalized, _ = cls._normalize_pair(symbol)
    history_symbol = _CRYPTO_HISTORY_SYMBOLS.get(normalized)
    if history_symbol:
        return history_symbol
    return _original_history_symbol(symbol)


def install() -> None:
    global _installed
    if _installed:
        return
    YFinanceProvider._normalize_pair = classmethod(_normalize_pair_with_crypto)
    YFinanceProvider._history_symbol = classmethod(_history_symbol_with_crypto)
    _installed = True

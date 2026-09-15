"""Session classification and display-frame construction for intraday charts.

This module is the single source of truth for chart session boundaries and
asset-aware session handling. US equity sessions are defined in
America/New_York and converted to UTC with zoneinfo so DST is handled without
fixed UTC offsets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time as dtime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

PREMARKET_START = dtime(4, 0)
REGULAR_START = dtime(9, 30)
REGULAR_END = dtime(16, 0)
AFTERMARKET_END = dtime(20, 0)


class SessionKind(str, Enum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTERMARKET = "aftermarket"
    CLOSED = "closed"


class AssetKind(str, Enum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    OTHER = "other"


_CRYPTO_COMPACT = frozenset({
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "DOGEUSD", "ADAUSD",
    "USDBTC", "USDETH", "USDSOL", "USDXRP", "USDBNB", "USDDOGE", "USDADA",
})

_FOREX_COMPACT = frozenset({
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "USDEUR", "USDGBP", "JPYUSD", "USDAUD", "AUUSD", "CADUSD", "CHFUSD", "USDNZD",
})

_US_INDEX_ALIASES = frozenset({
    "SP500", "SPX", "S&P500", "S&P500INDEX", "NASDAQ", "NASDAQCOMPOSITE",
    "DOWJONES", "DOW", "RUSSELL2000", "VIX",
})


def classify_asset(symbol: str, quote_asset_class: str | None = None) -> AssetKind:
    """Classify a symbol for chart-session purposes.

    Explicit symbol families win over provider metadata. When no explicit
    non-US family is recognised and the symbol looks like a normal ticker,
    default to US equity so the full-day frame is still available when quote
    metadata is missing.
    """
    s = (symbol or "").strip().upper()
    compact = s.replace("/", "").replace("-", "").replace("_", "").replace("^", "")

    if s.endswith("-USD") or compact in _CRYPTO_COMPACT:
        return AssetKind.CRYPTO
    if s.endswith("=X") or compact in _FOREX_COMPACT:
        return AssetKind.FOREX
    if s.endswith("=F") or compact in {"XAUUSD", "XAGUSD"}:
        return AssetKind.COMMODITY
    if s.startswith("^") or compact in _US_INDEX_ALIASES:
        return AssetKind.US_EQUITY

    if quote_asset_class:
        qc = quote_asset_class.lower()
        if qc == "crypto":
            return AssetKind.CRYPTO
        if qc == "forex":
            return AssetKind.FOREX
        if qc in {"commodity", "metal", "futures"}:
            return AssetKind.COMMODITY
        if qc in {"stock", "index", "equity"}:
            return AssetKind.US_EQUITY

    if s and s.replace(".", "").isalnum() and "=" not in s and ":" not in s and "/" not in s:
        return AssetKind.US_EQUITY
    return AssetKind.OTHER


def _ensure_utc(value: pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize(UTC)
    return stamp.tz_convert(UTC)


def latest_us_trading_date(when_utc: pd.Timestamp) -> date:
    """Return the latest weekday represented by ``when_utc`` in New York."""
    et = _ensure_utc(when_utc).tz_convert(ET)
    trading_date = et.date()
    while trading_date.weekday() >= 5:
        trading_date -= timedelta(days=1)
    return trading_date


@dataclass(frozen=True, slots=True)
class TradingFrame:
    asset_kind: AssetKind
    trading_date: date | None
    x_min_utc: pd.Timestamp
    x_max_utc: pd.Timestamp
    premarket_utc: tuple[pd.Timestamp, pd.Timestamp] | None
    regular_utc: tuple[pd.Timestamp, pd.Timestamp] | None
    aftermarket_utc: tuple[pd.Timestamp, pd.Timestamp] | None


def _et_to_utc(trading_date: date, clock: dtime) -> pd.Timestamp:
    return pd.Timestamp.combine(trading_date, clock).tz_localize(ET).tz_convert(UTC)


def build_us_equity_frame(when_utc: pd.Timestamp) -> TradingFrame:
    trading_date = latest_us_trading_date(when_utc)
    premarket = (_et_to_utc(trading_date, PREMARKET_START), _et_to_utc(trading_date, REGULAR_START))
    regular = (_et_to_utc(trading_date, REGULAR_START), _et_to_utc(trading_date, REGULAR_END))
    aftermarket = (_et_to_utc(trading_date, REGULAR_END), _et_to_utc(trading_date, AFTERMARKET_END))
    return TradingFrame(
        asset_kind=AssetKind.US_EQUITY,
        trading_date=trading_date,
        x_min_utc=premarket[0],
        x_max_utc=aftermarket[1],
        premarket_utc=premarket,
        regular_utc=regular,
        aftermarket_utc=aftermarket,
    )


def build_frame(symbol: str, when_utc: pd.Timestamp, quote_asset_class: str | None = None) -> TradingFrame | None:
    if classify_asset(symbol, quote_asset_class) is not AssetKind.US_EQUITY:
        return None
    return build_us_equity_frame(when_utc)


def classify_timestamp(timestamp: pd.Timestamp, trading_date: date) -> SessionKind:
    stamp = _ensure_utc(timestamp).tz_convert(ET)
    if stamp.date() != trading_date:
        return SessionKind.CLOSED
    clock = stamp.time()
    if PREMARKET_START <= clock < REGULAR_START:
        return SessionKind.PREMARKET
    if REGULAR_START <= clock < REGULAR_END:
        return SessionKind.REGULAR
    if REGULAR_END <= clock < AFTERMARKET_END:
        return SessionKind.AFTERMARKET
    return SessionKind.CLOSED

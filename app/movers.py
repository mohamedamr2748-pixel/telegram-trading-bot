from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import yfinance as yf


@dataclass(frozen=True)
class Mover:
    symbol: str
    name: str
    percent_change: float


_CACHE_TTL = 20.0
_cache: dict[str, tuple[float, tuple[Mover, ...]]] = {}
_lock = asyncio.Lock()


def _extract_quotes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        quotes = payload.get("quotes")
        if isinstance(quotes, list):
            return [item for item in quotes if isinstance(item, dict)]
        for value in payload.values():
            found = _extract_quotes(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_quotes(value)
            if found:
                return found
    return []


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _parse(payload: Any, *, descending: bool) -> tuple[Mover, ...]:
    rows: list[Mover] = []
    for item in _extract_quotes(payload):
        symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        change = _to_float(
            item.get("percentchange")
            if item.get("percentchange") is not None
            else item.get("regularMarketChangePercent")
        )
        if change is None:
            continue
        # yfinance's screener returns US equity results for the predefined
        # day_gainers/day_losers queries. Keep only sensible equity-like rows.
        if change == 0:
            continue
        name = str(item.get("shortName") or item.get("longName") or symbol).strip()
        rows.append(Mover(symbol=symbol, name=name, percent_change=change))
    rows.sort(key=lambda row: row.percent_change, reverse=descending)
    return tuple(rows[:3])


def _screen(query: str) -> tuple[Mover, ...]:
    payload = yf.screen(query, count=10)
    return _parse(payload, descending=query == "day_gainers")


async def get_top_movers() -> tuple[tuple[Mover, ...], tuple[Mover, ...]]:
    """Return top 3 US equity gainers and losers, never raising to callers."""
    global _cache
    async with _lock:
        now = time.monotonic()
        cached = _cache.get("top")
        if cached and cached[0] > now:
            gainers, losers = cached[1]
            return gainers, losers
        try:
            gainers, losers = await asyncio.gather(
                asyncio.to_thread(_screen, "day_gainers"),
                asyncio.to_thread(_screen, "day_losers"),
            )
        except Exception:
            return (), ()
        _cache["top"] = (now + _CACHE_TTL, (gainers, losers))
        return gainers, losers

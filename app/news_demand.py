from __future__ import annotations

import time
from datetime import datetime, timezone

from redis.asyncio import Redis

from config import settings

DEMAND_KEY = "news:demand:last_requested"
FETCH_KEY = "news:demand:last_fetched"


class NewsDemandTracker:
    """Tracks ticker demand only; it deliberately stores no user identifiers."""

    def __init__(self) -> None:
        self._redis: Redis | None = None

    async def _client(self) -> Redis | None:
        if not settings.redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def mark_requested(self, symbol: str) -> None:
        redis = await self._client()
        if redis is None:
            return
        await redis.hset(DEMAND_KEY, symbol.strip().upper(), str(int(time.time())))

    async def mark_fetched(self, symbol: str) -> None:
        redis = await self._client()
        if redis is None:
            return
        await redis.hset(FETCH_KEY, symbol.strip().upper(), str(int(time.time())))

    async def get_last_requested(self, symbol: str) -> datetime | None:
        redis = await self._client()
        if redis is None:
            return None
        raw = await redis.hget(DEMAND_KEY, symbol.strip().upper())
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc) if raw else None
        except (TypeError, ValueError, OverflowError):
            return None

    async def get_last_fetched(self, symbol: str) -> datetime | None:
        redis = await self._client()
        if redis is None:
            return None
        raw = await redis.hget(FETCH_KEY, symbol.strip().upper())
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc) if raw else None
        except (TypeError, ValueError, OverflowError):
            return None

    async def symbols(self) -> list[str]:
        redis = await self._client()
        if redis is None:
            return []
        values = await redis.hkeys(DEMAND_KEY)
        return [str(symbol).upper() for symbol in values]

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

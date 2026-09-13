from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone
from typing import Awaitable, Callable

from redis.asyncio import Redis

from app.domain import NewsItemDTO
from app.news import NewsService
from config import settings


FRESH_SECONDS = 6 * 60 * 60
STALE_FALLBACK_SECONDS = 12 * 60 * 60
LOCK_SECONDS = 120
POLL_SECONDS = 0.5
WAIT_TIMEOUT_SECONDS = 130


class NewsCacheService:
    """Per-ticker six-hour news cache with Redis single-flight refreshes.

    One request becomes the refresh owner. Concurrent requests for the same
    ticker wait for that refresh and then receive the same newly-built cache.
    """

    def __init__(self, news_service: NewsService | None = None) -> None:
        self.news_service = news_service or NewsService()
        self._redis: Redis | None = None

    async def _client(self) -> Redis | None:
        if not settings.redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _cache_key(symbol: str) -> str:
        return f"news:{symbol.strip().upper()}"

    @staticmethod
    def _lock_key(symbol: str) -> str:
        return f"news:lock:{symbol.strip().upper()}"

    @staticmethod
    def _serialise(items: list[NewsItemDTO], symbol: str, created_at: datetime) -> str:
        payload = {
            "symbol": symbol,
            "created_at": created_at.isoformat(),
            "refresh_at": (created_at.timestamp() + FRESH_SECONDS),
            "articles": [
                {
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "symbol": symbol,
                }
                for item in items
            ],
        }
        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _deserialise(raw: str | None) -> tuple[datetime | None, list[NewsItemDTO]]:
        if not raw:
            return None, []
        try:
            payload = json.loads(raw)
            created_at = datetime.fromisoformat(payload["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            items = [
                NewsItemDTO(
                    title=str(article["title"]),
                    url=str(article["url"]),
                    source=str(article["source"]),
                    published_at=(
                        datetime.fromisoformat(article["published_at"])
                        if article.get("published_at")
                        else None
                    ),
                    symbol=str(article.get("symbol") or payload.get("symbol") or ""),
                )
                for article in payload.get("articles", [])
            ]
            return created_at.astimezone(timezone.utc), items
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, []

    @staticmethod
    def _is_fresh(created_at: datetime | None, now: datetime | None = None) -> bool:
        if created_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - created_at).total_seconds() < FRESH_SECONDS

    async def get(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        redis = await self._client()

        # Redis is the production path. Keep a safe direct-search fallback for
        # local development when REDIS_URL has not been configured yet.
        if redis is None:
            return await self.news_service.search(symbol, limit)

        key = self._cache_key(symbol)
        lock_key = self._lock_key(symbol)
        raw = await redis.get(key)
        created_at, items = self._deserialise(raw)
        now = datetime.now(timezone.utc)

        if self._is_fresh(created_at, now):
            return items[:limit]

        previous_created_at = created_at
        token = secrets.token_urlsafe(24)
        acquired = await redis.set(lock_key, token, nx=True, ex=LOCK_SECONDS)

        if acquired:
            try:
                # Another request may have filled the cache between our first
                # GET and acquiring the lock. Always re-check before searching.
                raw = await redis.get(key)
                created_at, items = self._deserialise(raw)
                if self._is_fresh(created_at):
                    return items[:limit]

                new_items = await self.news_service.search(symbol, limit=max(limit, 8))
                if not new_items:
                    # Preserve the stale cache on refresh failure.
                    return items[:limit]

                created = datetime.now(timezone.utc)
                # A successful SET replaces the old cache in one operation.
                # Use a longer hard TTL so stale data remains available if the
                # next refresh fails after the six-hour freshness window.
                await redis.set(
                    key,
                    self._serialise(new_items, symbol, created),
                    ex=STALE_FALLBACK_SECONDS,
                )
                return new_items[:limit]
            finally:
                # Release only our lock; never delete another request's lock.
                lua = (
                    "if redis.call('get', KEYS[1]) == ARGV[1] "
                    "then return redis.call('del', KEYS[1]) else return 0 end"
                )
                try:
                    await redis.eval(lua, 1, lock_key, token)
                except Exception:
                    pass

        # Another request owns the refresh. Hold this request until the new
        # cache is visible, then return that exact cache to the user.
        deadline = asyncio.get_running_loop().time() + WAIT_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            raw = await redis.get(key)
            latest_created_at, latest_items = self._deserialise(raw)
            if latest_created_at is not None:
                if previous_created_at is None or latest_created_at > previous_created_at:
                    if latest_items:
                        return latest_items[:limit]

            lock_exists = await redis.exists(lock_key)
            if not lock_exists:
                # The owner finished (successfully or not). Re-enter the
                # normal path so one waiter can take ownership when needed.
                return await self.get(symbol, limit)
            await asyncio.sleep(POLL_SECONDS)

        # Never leave a Telegram request hanging indefinitely. At timeout,
        # serve the best stale cache available, or perform a final search.
        raw = await redis.get(key)
        _, stale_items = self._deserialise(raw)
        if stale_items:
            return stale_items[:limit]
        return await self.news_service.search(symbol, limit)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover
    Redis = Any  # type: ignore

from config import settings


class Cache:
    def __init__(self) -> None:
        self.redis: Redis | None = Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
        self.memory: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        if self.redis:
            return await self.redis.get(key)
        item = self.memory.get(key)
        if not item or item[0] < time.time():
            self.memory.pop(key, None)
            return None
        return item[1]

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        if self.redis:
            await self.redis.set(key, value, ex=ttl)
            return
        self.memory[key] = (time.time() + ttl, value)

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import NewsItemDTO
from app.news_cache import FRESH_SECONDS, LOCK_SECONDS, STALE_FALLBACK_SECONDS, NewsCacheService


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.locks = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx:
            if key in self.locks:
                return False
            self.locks[key] = value
            return True
        self.data[key] = value
        return True

    async def exists(self, key):
        return int(key in self.locks)

    async def eval(self, _lua, _numkeys, key, token):
        if self.locks.get(key) == token:
            del self.locks[key]
            return 1
        return 0


class FakeNewsService:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def search(self, symbol, limit=8):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return [
            NewsItemDTO(
                title=f"Fresh {symbol} story",
                url=f"https://reuters.com/{symbol.lower()}",
                source="Reuters",
                published_at=datetime.now(timezone.utc),
                symbol=symbol,
            )
        ]


class TestableNewsCacheService(NewsCacheService):
    def __init__(self, fake_redis, fake_news):
        super().__init__(fake_news)
        self.fake_redis = fake_redis

    async def _client(self):
        return self.fake_redis


@pytest.mark.asyncio
async def test_single_flight_returns_same_new_cache_to_all_waiters():
    redis = FakeRedis()
    news = FakeNewsService()
    service = TestableNewsCacheService(redis, news)

    tasks = [asyncio.create_task(service.get("AAPL", 8)) for _ in range(5)]
    await asyncio.wait_for(news.started.wait(), timeout=1)
    await asyncio.sleep(0.05)

    assert news.calls == 1
    assert all(not task.done() for task in tasks)

    news.release.set()
    results = await asyncio.gather(*tasks)

    assert news.calls == 1
    assert all(result == results[0] for result in results)
    assert results[0][0].title == "Fresh AAPL story"


@pytest.mark.asyncio
async def test_fresh_cache_does_not_search_again():
    redis = FakeRedis()
    news = FakeNewsService()
    service = TestableNewsCacheService(redis, news)

    news.release.set()
    first = await service.get("NVDA", 8)
    second = await service.get("NVDA", 8)

    assert first == second
    assert news.calls == 1


@pytest.mark.asyncio
async def test_existing_stale_cache_is_kept_when_refresh_returns_no_items():
    redis = FakeRedis()
    symbol = "TSLA"
    old_created = datetime.now(timezone.utc) - timedelta(seconds=FRESH_SECONDS + 60)
    redis.data[service_key := f"news:{symbol}"] = NewsCacheService._serialise(
        [
            NewsItemDTO(
                title="Old TSLA story",
                url="https://reuters.com/old-tsla",
                source="Reuters",
                published_at=old_created,
                symbol=symbol,
            )
        ],
        symbol,
        old_created,
    )

    class EmptyNewsService:
        async def search(self, _symbol, limit=8):
            return []

    service = TestableNewsCacheService(redis, EmptyNewsService())
    result = await service.get(symbol, 8)

    assert result[0].title == "Old TSLA story"
    assert redis.data[service_key] == NewsCacheService._serialise(
        result, symbol, old_created
    )


def test_news_cache_constants():
    assert FRESH_SECONDS == 21600
    assert STALE_FALLBACK_SECONDS == 43200
    assert LOCK_SECONDS == 120

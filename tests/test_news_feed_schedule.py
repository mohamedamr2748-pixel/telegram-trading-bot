from datetime import datetime, timedelta, timezone

import asyncio

from app.news_feed import NewsFeedWorker


class FakeDemand:
    def __init__(self, requested, fetched):
        self.requested = requested
        self.fetched = fetched

    async def get_last_requested(self, symbol):
        return self.requested

    async def get_last_fetched(self, symbol):
        return self.fetched


def test_due_without_previous_fetch():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(minutes=1), None)
    assert asyncio.run(worker._is_due("AAPL", now)) is True


def test_not_due_before_interval():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(minutes=1), now - timedelta(minutes=5))
    assert asyncio.run(worker._is_due("AAPL", now)) is False

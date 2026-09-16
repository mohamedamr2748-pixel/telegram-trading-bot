import asyncio
from datetime import datetime, timedelta, timezone

from app.news_feed import ACTIVE_POLL_MINUTES, ACTIVE_POLL_OFF_HOURS_MINUTES, NORMAL_POLL_HOURS, NewsFeedWorker, _is_regular_market_hours


class FakeDemand:
    def __init__(self, requested=None, fetched=None):
        self.requested = requested
        self.fetched = fetched

    async def get_last_requested(self, symbol):
        return self.requested

    async def get_last_fetched(self, symbol):
        return self.fetched


def test_regular_us_market_hours():
    assert _is_regular_market_hours(datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)) is True
    assert _is_regular_market_hours(datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)) is False
    assert _is_regular_market_hours(datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)) is False


def test_interval_requires_demand():
    worker = NewsFeedWorker()
    worker.demand = FakeDemand()
    assert asyncio.run(worker._interval_seconds("AAPL", datetime.now(timezone.utc))) is None


def test_active_equity_uses_15_minutes_during_regular_hours():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(hours=1))
    assert asyncio.run(worker._interval_seconds("AAPL", now)) == ACTIVE_POLL_MINUTES * 60


def test_active_non_equity_uses_30_minutes():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(hours=1))
    assert asyncio.run(worker._interval_seconds("BTC-USD", now)) == ACTIVE_POLL_OFF_HOURS_MINUTES * 60


def test_recent_demand_uses_2_hours():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(hours=12))
    assert asyncio.run(worker._interval_seconds("AAPL", now)) == NORMAL_POLL_HOURS * 3600


def test_dormant_demand_stops_refreshing():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    worker = NewsFeedWorker()
    worker.demand = FakeDemand(now - timedelta(hours=25))
    assert asyncio.run(worker._interval_seconds("AAPL", now)) is None

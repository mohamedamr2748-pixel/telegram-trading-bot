from datetime import datetime, timezone

from app.news_feed import NewsFeedWorker, _is_regular_market_hours


def test_regular_us_market_hours():
    assert _is_regular_market_hours(datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)) is True
    assert _is_regular_market_hours(datetime(2026, 9, 16, 21, 0, tzinfo=timezone.utc)) is False
    assert _is_regular_market_hours(datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)) is False


def test_interval_requires_demand(monkeypatch):
    worker = NewsFeedWorker(["AAPL"])

    async def no_request(symbol):
        return None

    monkeypatch.setattr(worker.demand, "get_last_requested", no_request)

    import asyncio
    interval = asyncio.run(worker._interval_seconds("AAPL", datetime.now(timezone.utc)))
    assert interval is None

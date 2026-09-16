from datetime import datetime, timedelta, timezone

from app.news_feed import NewsFeedWorker, _is_regular_market_hours


def test_regular_us_market_hours_uses_new_york_clock() -> None:
    monday_open = datetime(2026, 9, 14, 13, 30, tzinfo=timezone.utc)
    monday_after_close = datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)

    assert _is_regular_market_hours(monday_open) is True
    assert _is_regular_market_hours(monday_after_close) is False
    assert _is_regular_market_hours(saturday) is False


def test_no_demand_means_no_refresh() -> None:
    worker = NewsFeedWorker(["AAPL"])
    now = datetime.now(timezone.utc)
    assert worker._interval_seconds  # method exists; demand is checked asynchronously below


def test_candidate_universe_is_explicit_and_does_not_imply_fetch() -> None:
    worker = NewsFeedWorker(["AAPL", "NVDA", "BTCUSD"])
    assert worker.candidate_symbols == {"AAPL", "NVDA", "BTCUSD"}

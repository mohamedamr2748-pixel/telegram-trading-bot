from app.news_cache import FRESH_SECONDS, STALE_FALLBACK_SECONDS, LOCK_SECONDS


def test_news_cache_constants():
    assert FRESH_SECONDS == 21600
    assert STALE_FALLBACK_SECONDS == 43200
    assert LOCK_SECONDS == 120

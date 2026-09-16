from app.cache_cleanup import CACHE_TABLES


def test_cache_cleanup_targets_only_non_user_tables():
    assert CACHE_TABLES == ("news_assets", "news", "market_snapshots")
    assert "users" not in CACHE_TABLES
    assert "watchlists" not in CACHE_TABLES
    assert "alerts" not in CACHE_TABLES
    assert "usage" not in CACHE_TABLES

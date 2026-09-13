"""Telegram Trading Intelligence Bot application package."""

# Install the cache-aware NewsService before app.bot imports NewsService.
# This keeps the existing news filtering/search implementation intact while
# adding the per-ticker Redis single-flight cache at the application boundary.
from app import news as _news_module
from app.news_cache import NewsCacheService


class CachedNewsService(NewsCacheService):
    pass


_news_module.NewsService = CachedNewsService

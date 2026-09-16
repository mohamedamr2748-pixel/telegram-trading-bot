from __future__ import annotations

import logging
from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

# These tables contain market/news cache data only in the current trading bot.
# User-owned data is deliberately NOT included here.
CACHE_TABLES = ("news_assets", "news", "market_snapshots")


async def purge_market_cache() -> None:
    """Delete only persisted market/news cache data.

    Never touches users, watchlists, watchlist_items, alerts, usage, or any
    other user-owned table.
    """
    async with engine.begin() as conn:
        # Order matters because news_assets references news.
        await conn.execute(text("TRUNCATE TABLE news_assets RESTART IDENTITY CASCADE"))
        await conn.execute(text("TRUNCATE TABLE news RESTART IDENTITY CASCADE"))
        await conn.execute(text("TRUNCATE TABLE market_snapshots RESTART IDENTITY CASCADE"))
    logger.info("Purged non-user market/news cache tables: %s", ", ".join(CACHE_TABLES))

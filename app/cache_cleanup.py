from __future__ import annotations

import logging
from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)

# These tables contain application market/news cache data only.
# User-owned data is deliberately NOT included here.
CACHE_TABLES = ("news_assets", "news", "market_snapshots")


async def purge_market_cache() -> None:
    """Delete only persisted market/news cache data.

    This function intentionally never touches users, watchlists, alerts,
    usage, study/user records, or any other user-owned tables.
    """
    async with engine.begin() as conn:
        for table in CACHE_TABLES:
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    logger.info("Purged non-user market/news cache tables: %s", ", ".join(CACHE_TABLES))

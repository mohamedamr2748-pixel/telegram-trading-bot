from __future__ import annotations

import logging

from sqlalchemy import delete

from app.db import MarketSnapshot, NewsAsset, NewsItem, engine, session_factory

logger = logging.getLogger(__name__)

CACHE_TABLES = ("news_assets", "news", "market_snapshots")


async def purge_market_cache() -> None:
    """Delete only market/news cache rows; no user-owned table is targeted."""
    async with session_factory() as session:
        await session.execute(delete(NewsAsset))
        await session.execute(delete(NewsItem))
        await session.execute(delete(MarketSnapshot))
        await session.commit()
    logger.info("Purged non-user market/news cache tables: %s", ", ".join(CACHE_TABLES))

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import NewsAsset, NewsItem, session_factory
from app.domain import NewsItemDTO
from app.news_demand import NewsDemandTracker

RETENTION_HOURS = 48


class NewsCacheService:
    """Compatibility reader for the persisted news feed; never performs network I/O."""

    def __init__(self) -> None:
        self.demand = NewsDemandTracker()

    async def _read(self, symbol: str, limit: int) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
        async with session_factory() as session:
            result = await session.execute(
                select(NewsItem, NewsAsset.symbol)
                .join(NewsAsset, NewsAsset.news_id == NewsItem.id)
                .where(NewsAsset.symbol == symbol, NewsItem.published_at.is_not(None), NewsItem.published_at >= cutoff)
                .order_by(NewsItem.published_at.desc())
                .limit(limit)
            )
            rows = result.all()
        return [
            NewsItemDTO(title=item.title, url=item.canonical_url, source=item.source, published_at=item.published_at, relevance=item.relevance, urgency=item.urgency, symbol=asset_symbol)
            for item, asset_symbol in rows
        ]

    async def get_fresh(self, symbol: str, limit: int = 8) -> list[NewsItemDTO] | None:
        await self.demand.mark_requested(symbol)
        items = await self._read(symbol, limit)
        return items if items else None

    async def get(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        await self.demand.mark_requested(symbol)
        return await self._read(symbol, limit)

    async def close(self) -> None:
        await self.demand.close()

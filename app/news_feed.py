from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
from sqlalchemy import select

from app.db import NewsAsset, NewsItem, engine, session_factory
from app.domain import NewsItemDTO

logger = logging.getLogger(__name__)

# Baseline collector cadence. Per-symbol demand can be added later without
# coupling /news requests to external providers.
DEFAULT_POLL_SECONDS = 2 * 60 * 60
RETENTION_HOURS = 48
FETCH_LIMIT = 40


def _normalise_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" or url.rstrip("/").lower()


def _published_at(entry: object) -> datetime | None:
    raw = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if raw is None:
        return None
    try:
        import calendar
        return datetime.fromtimestamp(calendar.timegm(raw), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _google_news_url(symbol: str) -> str:
    query = quote_plus(f'"{symbol}" stock OR shares')
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


class GoogleNewsFeed:
    """Fetch a symbol's Google News RSS feed and persist only news rows."""

    async def fetch(self, symbol: str, limit: int = FETCH_LIMIT) -> list[NewsItemDTO]:
        symbol = _normalise_symbol(symbol)
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "TickaroNewsFeed/1.0"}) as client:
            response = await client.get(_google_news_url(symbol))
            response.raise_for_status()
        parsed = feedparser.parse(response.content)
        items: list[NewsItemDTO] = []
        for entry in parsed.entries[:limit]:
            title = str(getattr(entry, "title", "")).strip()
            url = str(getattr(entry, "link", "")).strip()
            published_at = _published_at(entry)
            if not title or not url or published_at is None:
                continue
            source = str(getattr(getattr(entry, "source", None), "title", "Google News")).strip() or "Google News"
            items.append(NewsItemDTO(title=title, url=url, source=source, published_at=published_at, symbol=symbol))
        return sorted(items, key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


async def store_news(items: list[NewsItemDTO]) -> int:
    if not items:
        return 0
    inserted = 0
    async with session_factory() as session:
        for item in items:
            canonical = _canonical_url(item.url)
            existing = await session.scalar(select(NewsItem).where(NewsItem.canonical_url == canonical))
            if existing is None:
                row = NewsItem(canonical_url=canonical, title=item.title, source=item.source, published_at=item.published_at)
                session.add(row)
                await session.flush()
                session.add(NewsAsset(news_id=row.id, symbol=item.symbol))
                inserted += 1
            else:
                asset = await session.scalar(select(NewsAsset).where(NewsAsset.news_id == existing.id, NewsAsset.symbol == item.symbol))
                if asset is None:
                    session.add(NewsAsset(news_id=existing.id, symbol=item.symbol))
        await session.commit()
    return inserted


async def cleanup_old_news(hours: int = RETENTION_HOURS) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM news_assets WHERE news_id IN (SELECT id FROM news WHERE published_at IS NOT NULL AND published_at < :cutoff)"
            ),
            {"cutoff": cutoff},
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM news WHERE published_at IS NOT NULL AND published_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )


class NewsFeedWorker:
    def __init__(self, symbols: list[str], poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        self.symbols = [_normalise_symbol(s) for s in symbols if s.strip()]
        self.poll_seconds = max(300, poll_seconds)
        self.provider = GoogleNewsFeed()

    async def run(self) -> None:
        while True:
            try:
                for symbol in self.symbols:
                    try:
                        items = await self.provider.fetch(symbol)
                        inserted = await store_news(items)
                        logger.info("News feed %s: fetched=%s inserted=%s", symbol, len(items), inserted)
                    except Exception:
                        logger.exception("News feed fetch failed for %s", symbol)
                await cleanup_old_news()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("News feed worker failed")
            await asyncio.sleep(self.poll_seconds)

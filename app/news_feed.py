from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

import feedparser
import httpx
from sqlalchemy import select

from app.db import NewsAsset, NewsItem, engine, session_factory
from app.domain import NewsItemDTO
from app.news_demand import NewsDemandTracker

logger = logging.getLogger(__name__)

SCHEDULER_SECONDS = 5 * 60
ACTIVE_HOURS = 6
NORMAL_HOURS = 24
RETENTION_HOURS = 48
FETCH_LIMIT = 40
ACTIVE_POLL_MINUTES = 15
ACTIVE_POLL_OFF_HOURS_MINUTES = 30
NORMAL_POLL_HOURS = 2
MARKET_TZ = ZoneInfo("America/New_York")

SPECIAL_QUERIES = {
    "BTC-USD": "Bitcoin crypto cryptocurrency",
    "ETH-USD": "Ethereum crypto cryptocurrency",
    "GC=F": "gold futures gold prices",
    "EURUSD=X": "EUR USD euro dollar forex",
    "GBPUSD=X": "GBP USD pound dollar forex",
    "JPY=X": "JPY USD yen dollar forex",
}
NON_US_EQUITIES = {"BTC-USD", "ETH-USD", "GC=F", "EURUSD=X", "GBPUSD=X", "JPY=X", "BTCUSD", "ETHUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"}

# User-facing News is restricted to established financial publishers.
TRUSTED_NEWS_DOMAINS = {
    "reuters.com", "bloomberg.com", "cnbc.com", "ft.com",
    "wsj.com", "barrons.com", "marketwatch.com", "apnews.com",
}
TRUSTED_NEWS_NAMES = {
    "reuters", "bloomberg", "cnbc", "financial times",
    "the wall street journal", "wall street journal",
    "barron's", "marketwatch", "associated press", "ap news",
}

def _is_trusted_news_source(source: str, url: str) -> bool:
    source_norm = source.strip().lower()
    if source_norm in TRUSTED_NEWS_NAMES:
        return True
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in TRUSTED_NEWS_DOMAINS)


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
    base = SPECIAL_QUERIES.get(symbol, f'"{symbol}" stock OR shares')
    trusted_sites = " OR ".join(f"site:{domain}" for domain in TRUSTED_NEWS_DOMAINS)
    query = f"({base}) ({trusted_sites})"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def _is_us_equity(symbol: str) -> bool:
    return symbol not in NON_US_EQUITIES


def _is_regular_market_hours(now: datetime | None = None) -> bool:
    local = (now or datetime.now(timezone.utc)).astimezone(MARKET_TZ)
    if local.weekday() >= 5:
        return False
    minute = local.hour * 60 + local.minute
    return 9 * 60 + 30 <= minute < 16 * 60


class GoogleNewsFeed:
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
            source = str(getattr(getattr(entry, "source", None), "title", "")).strip()
            if not source or not _is_trusted_news_source(source, url):
                continue
            items.append(NewsItemDTO(title=title, url=url, source=source, published_at=published_at, symbol=symbol))
        return sorted(items, key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


async def store_news(items: list[NewsItemDTO]) -> int:
    inserted = 0
    if not items:
        return inserted
    async with session_factory() as session:
        for item in items:
            canonical = _canonical_url(item.url)
            existing = await session.scalar(select(NewsItem).where(NewsItem.canonical_url == canonical))
            if existing is None:
                existing = NewsItem(canonical_url=canonical, title=item.title, source=item.source, published_at=item.published_at, relevance=item.relevance, urgency=item.urgency)
                session.add(existing)
                await session.flush()
                inserted += 1
            asset = await session.scalar(select(NewsAsset).where(NewsAsset.news_id == existing.id, NewsAsset.symbol == item.symbol))
            if asset is None:
                session.add(NewsAsset(news_id=existing.id, symbol=item.symbol))
        await session.commit()
    return inserted


async def cleanup_old_news(hours: int = RETENTION_HOURS) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with session_factory() as session:
        old_ids = select(NewsItem.id).where(NewsItem.published_at.is_not(None), NewsItem.published_at < cutoff)
        await session.execute(NewsAsset.__table__.delete().where(NewsAsset.news_id.in_(old_ids)))
        await session.execute(NewsItem.__table__.delete().where(NewsItem.published_at.is_not(None), NewsItem.published_at < cutoff))
        await session.commit()


class NewsFeedWorker:
    """Background-only news collector with adaptive ticker polling."""

    def __init__(self) -> None:
        self.provider = GoogleNewsFeed()
        self.demand = NewsDemandTracker()

    async def _interval_seconds(self, symbol: str, now: datetime) -> int | None:
        last_requested = await self.demand.get_last_requested(symbol)
        if last_requested is None:
            return None
        age_hours = max(0.0, (now - last_requested).total_seconds() / 3600)
        if age_hours <= ACTIVE_HOURS:
            return ACTIVE_POLL_MINUTES * 60 if _is_us_equity(symbol) and _is_regular_market_hours(now) else ACTIVE_POLL_OFF_HOURS_MINUTES * 60
        if age_hours <= NORMAL_HOURS:
            return NORMAL_POLL_HOURS * 3600
        return None

    async def _is_due(self, symbol: str, now: datetime) -> bool:
        interval = await self._interval_seconds(symbol, now)
        if interval is None:
            return False
        last_fetched = await self.demand.get_last_fetched(symbol)
        return last_fetched is None or (now - last_fetched).total_seconds() >= interval

    async def _refresh_symbol(self, symbol: str) -> None:
        if not await self._is_due(symbol, datetime.now(timezone.utc)):
            return
        try:
            items = await self.provider.fetch(symbol)
            inserted = await store_news(items)
            await self.demand.mark_fetched(symbol)
            logger.info("News feed %s: fetched=%s inserted=%s", symbol, len(items), inserted)
        except Exception:
            logger.exception("News feed fetch failed for %s", symbol)

    async def run(self) -> None:
        while True:
            try:
                await self.demand.prune_inactive()
                for symbol in await self.demand.symbols():
                    await self._refresh_symbol(symbol)
                await cleanup_old_news()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("News feed worker failed")
            await asyncio.sleep(SCHEDULER_SECONDS)

    async def close(self) -> None:
        await self.demand.close()

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

import feedparser
import httpx
from sqlalchemy import select, text

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


def _is_us_equity(symbol: str) -> bool:
    return symbol not in {"BTCUSD", "ETHUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"}


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
            text("DELETE FROM news_assets WHERE news_id IN (SELECT id FROM news WHERE published_at IS NOT NULL AND published_at < :cutoff)"),
            {"cutoff": cutoff},
        )
        await conn.execute(
            text("DELETE FROM news WHERE published_at IS NOT NULL AND published_at < :cutoff"),
            {"cutoff": cutoff},
        )


class NewsFeedWorker:
    """Adaptive ticker collector: active -> 15/30m, normal -> 2h, dormant -> off."""

    def __init__(self, candidate_symbols: list[str]) -> None:
        self.candidate_symbols = {_normalise_symbol(s) for s in candidate_symbols if s.strip()}
        self.provider = GoogleNewsFeed()
        self.demand = NewsDemandTracker()

    async def _tracked_symbols(self) -> list[str]:
        # Candidate tickers are known up front, but are fetched only after
        # aggregate demand exists. /news can dynamically add any valid ticker.
        return sorted(self.candidate_symbols | set(await self.demand.symbols()))

    async def _interval_seconds(self, symbol: str, now: datetime) -> int | None:
        last_requested = await self.demand.get_last_requested(symbol)
        if last_requested is None:
            return None
        age_hours = max(0.0, (now - last_requested).total_seconds() / 3600)
        if age_hours <= ACTIVE_HOURS:
            if _is_us_equity(symbol) and _is_regular_market_hours(now):
                return ACTIVE_POLL_MINUTES * 60
            return ACTIVE_POLL_OFF_HOURS_MINUTES * 60
        if age_hours <= NORMAL_HOURS:
            return NORMAL_POLL_HOURS * 3600
        return None

    async def _is_due(self, symbol: str, now: datetime) -> bool:
        interval = await self._interval_seconds(symbol, now)
        if interval is None:
            return False
        last_fetched = await self.demand.get_last_fetched(symbol)
        if last_fetched is None:
            return True
        return (now - last_fetched).total_seconds() >= interval

    async def _refresh_symbol(self, symbol: str) -> None:
        now = datetime.now(timezone.utc)
        if not await self._is_due(symbol, now):
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
                symbols = await self._tracked_symbols()
                for symbol in symbols:
                    await self._refresh_symbol(symbol)
                await cleanup_old_news()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("News feed worker failed")
            await asyncio.sleep(SCHEDULER_SECONDS)

    async def close(self) -> None:
        await self.demand.close()

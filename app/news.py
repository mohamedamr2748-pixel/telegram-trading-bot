from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from app.domain import NewsItemDTO
from config import settings


class GDELTNewsProvider:
    async def search(self, query: str, limit: int = 10) -> list[NewsItemDTO]:
        params = {
            "query": f'"{query.upper()}"',
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(limit, 75),
            "timespan": "1d",
            "sort": "datedesc",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(settings.gdelt_base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        items: list[NewsItemDTO] = []
        for article in payload.get("articles", []):
            url = article.get("url") or article.get("documentidentifier")
            title = article.get("title") or "Untitled"
            if not url:
                continue
            published = None
            raw_date = article.get("seendate") or article.get("date")
            if raw_date:
                try:
                    published = datetime.strptime(str(raw_date)[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            source = article.get("domain") or article.get("sourcecountry") or "GDELT"
            items.append(NewsItemDTO(title=title, url=url, source=str(source), published_at=published, symbol=query.upper()))
        return items


class RSSNewsProvider:
    async def fetch(self, urls: list[str], limit: int = 10) -> list[NewsItemDTO]:
        def parse(url: str) -> list[NewsItemDTO]:
            feed = feedparser.parse(url)
            result: list[NewsItemDTO] = []
            for entry in feed.entries[:limit]:
                link = entry.get("link")
                title = entry.get("title")
                if not link or not title:
                    continue
                result.append(NewsItemDTO(title=title, url=link, source=feed.feed.get("title", url)))
            return result
        batches = await asyncio.gather(*(asyncio.to_thread(parse, url) for url in urls), return_exceptions=True)
        output: list[NewsItemDTO] = []
        for batch in batches:
            if isinstance(batch, Exception):
                continue
            output.extend(batch)
        return output


class NewsService:
    def __init__(self) -> None:
        self.gdelt = GDELTNewsProvider()
        self.rss = RSSNewsProvider()

    async def search(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        gdelt_items = []
        try:
            gdelt_items = await self.gdelt.search(symbol, limit)
        except Exception:
            pass
        rss_items = await self.rss.fetch(settings.rss_urls, limit=max(3, limit // 2)) if settings.rss_urls else []
        combined = gdelt_items + [item for item in rss_items if symbol.lower() in item.title.lower()]
        seen: set[str] = set()
        unique: list[NewsItemDTO] = []
        for item in combined:
            key = item.url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return unique[:limit]

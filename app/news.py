from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import httpx

from app.domain import NewsItemDTO
from config import settings


_COMPANY_ALIASES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "AVGO": "Broadcom",
    "AMD": "AMD",
    "PLTR": "Palantir",
    "COIN": "Coinbase",
    "INTC": "Intel",
    "JPM": "JPMorgan",
    "NFLX": "Netflix",
    "ORCL": "Oracle",
    "CRM": "Salesforce",
    "MU": "Micron",
    "QCOM": "Qualcomm",
    "BA": "Boeing",
    "WMT": "Walmart",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
}


def _search_terms(symbol: str) -> list[str]:
    symbol = symbol.strip().upper()
    alias = _COMPANY_ALIASES.get(symbol)
    if alias:
        return [symbol, alias]
    return [symbol, f"{symbol} stock"]


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class GDELTNewsProvider:
    async def search(self, query: str, limit: int = 10) -> list[NewsItemDTO]:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(limit, 75),
            "timespan": "3d",
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
            published = _parse_datetime(article.get("seendate") or article.get("date"))
            source = article.get("domain") or article.get("sourcecountry") or "GDELT"
            items.append(
                NewsItemDTO(
                    title=title,
                    url=url,
                    source=str(source),
                    published_at=published,
                    symbol=query,
                )
            )
        return items


class GoogleNewsRSSProvider:
    base_url = "https://news.google.com/rss/search"

    async def search(self, query: str, limit: int = 10) -> list[NewsItemDTO]:
        url = f"{self.base_url}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"

        def parse() -> list[NewsItemDTO]:
            feed = feedparser.parse(url)
            output: list[NewsItemDTO] = []
            for entry in feed.entries[:limit]:
                link = entry.get("link")
                title = entry.get("title")
                if not link or not title:
                    continue
                source_obj = entry.get("source")
                source = source_obj.get("title") if hasattr(source_obj, "get") else None
                published = _parse_datetime(entry.get("published") or entry.get("updated"))
                output.append(
                    NewsItemDTO(
                        title=title,
                        url=link,
                        source=source or "Google News",
                        published_at=published,
                        symbol=query,
                    )
                )
            return output

        return await asyncio.to_thread(parse)


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
                published = _parse_datetime(entry.get("published") or entry.get("updated"))
                result.append(
                    NewsItemDTO(
                        title=title,
                        url=link,
                        source=feed.feed.get("title", url),
                        published_at=published,
                    )
                )
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
        self.google = GoogleNewsRSSProvider()
        self.rss = RSSNewsProvider()

    async def search(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        terms = _search_terms(symbol)
        query = f'"{terms[0]}" OR "{terms[1]}"'

        gdelt_items: list[NewsItemDTO] = []
        google_items: list[NewsItemDTO] = []

        # GDELT is the first free source. Broaden the query beyond an exact ticker
        # match so a company name such as NVIDIA still returns relevant stories.
        try:
            gdelt_items = await self.gdelt.search(query, max(limit, 10))
        except Exception:
            gdelt_items = []

        # Google News RSS is a second free fallback and is especially useful when
        # GDELT has not indexed the latest stories for a ticker yet.
        try:
            google_query = f"{terms[0]} {terms[1]}"
            google_items = await self.google.search(google_query, max(limit, 10))
        except Exception:
            google_items = []

        rss_items = await self.rss.fetch(settings.rss_urls, limit=max(3, limit // 2)) if settings.rss_urls else []
        combined = gdelt_items + google_items + rss_items

        seen: set[str] = set()
        unique: list[NewsItemDTO] = []
        for item in combined:
            key = item.url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            item.symbol = symbol
            unique.append(item)

        unique.sort(
            key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Keep the bot formatter simple: every result carries its publication date
        # directly in the linked title. Unknown dates are explicitly marked.
        for item in unique:
            date_label = item.published_at.strftime("%d %b %Y") if item.published_at else "Date n/a"
            item.title = f"[{date_label}] {item.title}"

        return unique[:limit]

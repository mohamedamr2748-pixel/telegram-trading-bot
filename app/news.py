from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

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
    "BTCUSD": "Bitcoin",
    "ETHUSD": "Ethereum",
    "XAUUSD": "Gold",
    "EURUSD": "EUR USD",
    "GBPUSD": "GBP USD",
    "USDJPY": "USD JPY",
}


@dataclass(frozen=True, slots=True)
class NewsSource:
    priority: int
    name: str
    domain: str
    reliability: float
    specialties: tuple[str, ...]


# Editorial source order requested for the trading bot. Google News is used as
# the discovery layer so the bot can query each domain without requiring an API
# key from every publisher.
NEWS_SOURCES: tuple[NewsSource, ...] = (
    NewsSource(1, "Reuters", "reuters.com", 1.00, ("markets", "macro", "stocks", "fx", "commodities")),
    NewsSource(2, "Bloomberg", "bloomberg.com", 1.00, ("markets", "macro", "stocks", "rates", "fx", "commodities")),
    NewsSource(3, "The Wall Street Journal", "wsj.com", 0.98, ("stocks", "companies", "macro", "markets")),
    NewsSource(4, "Financial Times", "ft.com", 0.98, ("global markets", "macro", "rates", "fx")),
    NewsSource(5, "CNBC", "cnbc.com", 0.96, ("markets", "stocks", "earnings", "fed")),
    NewsSource(6, "MarketWatch", "marketwatch.com", 0.93, ("stocks", "indices", "macro")),
    NewsSource(7, "Yahoo Finance", "finance.yahoo.com", 0.92, ("stocks", "earnings", "markets")),
    NewsSource(8, "Barron's", "barrons.com", 0.92, ("stocks", "investing", "markets")),
    NewsSource(9, "Investing.com", "investing.com", 0.90, ("stocks", "fx", "commodities", "indices", "crypto")),
    NewsSource(10, "TradingView", "tradingview.com", 0.90, ("markets", "technical", "stocks", "fx", "crypto")),
    NewsSource(11, "Seeking Alpha", "seekingalpha.com", 0.88, ("stocks", "earnings", "analysis")),
    NewsSource(12, "Benzinga", "benzinga.com", 0.86, ("stocks", "earnings", "breaking")),
    NewsSource(13, "Investor's Business Daily", "investors.com", 0.85, ("stocks", "technical", "fundamental")),
    NewsSource(14, "TheStreet", "thestreet.com", 0.83, ("stocks", "markets")),
    NewsSource(15, "Forbes", "forbes.com", 0.82, ("companies", "markets", "macro")),
    NewsSource(16, "Fortune", "fortune.com", 0.81, ("companies", "economy", "markets")),
    NewsSource(17, "Nasdaq", "nasdaq.com", 0.84, ("equities", "earnings", "markets")),
    NewsSource(18, "Barchart", "barchart.com", 0.84, ("stocks", "futures", "commodities", "options")),
    NewsSource(19, "Stocktwits", "stocktwits.com", 0.72, ("trader sentiment", "stocks")),
    NewsSource(20, "FXStreet", "fxstreet.com", 0.87, ("fx", "macro", "central banks")),
    NewsSource(21, "Forex Factory", "forexfactory.com", 0.78, ("fx", "economic events")),
    NewsSource(22, "Kitco", "kitco.com", 0.84, ("gold", "silver", "metals")),
    NewsSource(23, "OilPrice.com", "oilprice.com", 0.79, ("oil", "energy", "commodities")),
    NewsSource(24, "CoinDesk", "coindesk.com", 0.88, ("crypto", "bitcoin", "regulation")),
    NewsSource(25, "Cointelegraph", "cointelegraph.com", 0.80, ("crypto", "regulation")),
    NewsSource(26, "The Block", "theblock.co", 0.86, ("crypto", "institutional", "markets")),
    NewsSource(27, "Blockworks", "blockworks.co", 0.83, ("crypto", "institutional", "markets")),
    NewsSource(28, "Decrypt", "decrypt.co", 0.77, ("crypto", "web3")),
    NewsSource(29, "Morningstar", "morningstar.com", 0.86, ("equities", "funds", "valuation")),
    NewsSource(30, "Investopedia", "investopedia.com", 0.75, ("markets", "investing", "finance")),
)

_SOURCE_BY_DOMAIN = {source.domain: source for source in NEWS_SOURCES}


def _search_terms(symbol: str) -> list[str]:
    symbol = symbol.strip().upper()
    alias = _COMPANY_ALIASES.get(symbol)
    if alias:
        return [symbol, alias]
    return [symbol, f"{symbol} stock"]


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
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


def _normalise_title(title: str) -> str:
    text = re.sub(r"\s+", " ", title).strip().lower()
    text = re.sub(r"\[[^\]]+\]$", "", text).strip()
    return re.sub(r"[^a-z0-9 ]+", "", text)


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" or url.rstrip("/").lower()


def _source_for_item(item: NewsItemDTO) -> NewsSource | None:
    host = urlparse(item.url).netloc.lower().replace("www.", "")
    for source in NEWS_SOURCES:
        if host == source.domain or host.endswith("." + source.domain):
            return source
    name = (item.source or "").strip().lower()
    for source in NEWS_SOURCES:
        if name == source.name.lower():
            return source
    return None


def _is_recent(published_at: datetime | None, hours: int) -> bool:
    if published_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return published_at >= cutoff


class GDELTNewsProvider:
    async def search(self, query: str, limit: int = 20, timespan: str = "48h") -> list[NewsItemDTO]:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(limit, 75),
            "timespan": timespan,
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
            items.append(NewsItemDTO(title=title, url=url, source=str(source), published_at=published, symbol=query))
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
                output.append(NewsItemDTO(title=title, url=link, source=source or "Google News", published_at=published, symbol=query))
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
                result.append(NewsItemDTO(title=title, url=link, source=feed.feed.get("title", url), published_at=published))
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
        self._semaphore = asyncio.Semaphore(8)

    async def _search_source(self, source: NewsSource, terms: list[str], limit: int) -> list[NewsItemDTO]:
        query_terms = " OR ".join(f'"{term}"' for term in terms)
        # site: is the key Google News discovery filter. This keeps the 30-source
        # universe explicit while still using one public feed endpoint per source.
        query = f"({query_terms}) site:{source.domain}"
        async with self._semaphore:
            try:
                return await self.google.search(query, limit)
            except Exception:
                return []

    def _score(self, item: NewsItemDTO, symbol: str, terms: list[str]) -> float:
        source = _source_for_item(item)
        priority_score = (31 - source.priority) * 10 if source else 0
        reliability = (source.reliability * 100) if source else 0
        age_score = 0.0
        if item.published_at:
            age_minutes = max(0.0, (datetime.now(timezone.utc) - item.published_at).total_seconds() / 60.0)
            age_score = max(0.0, 720.0 - age_minutes) / 12.0
        title_lower = item.title.lower()
        relevance = 0.0
        for term in terms:
            if term.lower() in title_lower:
                relevance += 25.0
        if symbol.lower() in title_lower:
            relevance += 10.0
        return priority_score + reliability + age_score + relevance

    async def search(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        terms = _search_terms(symbol)
        now = datetime.now(timezone.utc)

        # Search all ranked publishers concurrently through Google News RSS.
        # We deliberately request more candidates than the user sees so scoring
        # and duplicate removal can choose the strongest stories.
        per_source_limit = max(3, min(6, limit))
        source_batches = await asyncio.gather(
            *(self._search_source(source, terms, per_source_limit) for source in NEWS_SOURCES)
        )
        google_items = [item for batch in source_batches for item in batch]

        # GDELT is the broad safety-net for stories Google News has not surfaced.
        gdelt_items: list[NewsItemDTO] = []
        try:
            gdelt_query = f'({" OR ".join(f"{term}" for term in terms)})'
            gdelt_items = await self.gdelt.search(gdelt_query, max(20, limit * 3), timespan="48h")
        except Exception:
            gdelt_items = []

        custom_items = await self.rss.fetch(settings.rss_urls, limit=max(3, limit // 2)) if settings.rss_urls else []

        candidates: list[NewsItemDTO] = []
        candidates.extend(google_items)
        candidates.extend(gdelt_items)
        candidates.extend(custom_items)

        # Keep only current daily stories when a publication date is available.
        candidates = [item for item in candidates if _is_recent(item.published_at, 24)]
        for item in candidates:
            item.symbol = symbol

        # Deduplicate by canonical URL first, then by normalised title so the
        # same wire story repeated across outlets only appears once.
        seen_urls: set[str] = set()
        title_buckets: dict[str, NewsItemDTO] = {}
        unique: list[NewsItemDTO] = []
        for item in candidates:
            url_key = _canonical_url(item.url)
            title_key = _normalise_title(item.title)
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            existing = title_buckets.get(title_key)
            if existing is not None:
                existing_score = self._score(existing, symbol, terms)
                item_score = self._score(item, symbol, terms)
                if item_score <= existing_score:
                    continue
                try:
                    unique.remove(existing)
                except ValueError:
                    pass
            title_buckets[title_key] = item
            unique.append(item)

        unique.sort(key=lambda item: self._score(item, symbol, terms), reverse=True)

        output: list[NewsItemDTO] = []
        for item in unique:
            source = _source_for_item(item)
            if source:
                source_label = source.name
            else:
                source_label = item.source or "Unknown source"
            date_label = item.published_at.strftime("%d %b %Y") if item.published_at else "Date n/a"
            item.title = f"[{date_label}] {item.title}"
            item.source = source_label
            output.append(item)
            if len(output) >= limit:
                break

        # Deterministic fallback: the old broad GDELT/Google search still has a
        # chance to return useful results when every publisher filter is empty.
        if not output:
            fallback_query = f'"{terms[0]}" OR "{terms[1]}"'
            try:
                fallback = await self.google.search(fallback_query, limit)
            except Exception:
                fallback = []
            for item in fallback:
                item.symbol = symbol
                if item.published_at and item.published_at > now - timedelta(hours=48):
                    item.title = f"[{item.published_at.strftime('%d %b %Y')}] {item.title}"
                    output.append(item)
                if len(output) >= limit:
                    break

        return output[:limit]

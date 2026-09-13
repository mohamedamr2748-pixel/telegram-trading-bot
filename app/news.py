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
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon", "META": "Meta Platforms",
    "TSLA": "Tesla", "GOOGL": "Alphabet", "GOOG": "Alphabet", "AVGO": "Broadcom", "AMD": "AMD",
    "PLTR": "Palantir", "COIN": "Coinbase", "INTC": "Intel", "JPM": "JPMorgan", "NFLX": "Netflix",
    "ORCL": "Oracle", "CRM": "Salesforce", "MU": "Micron", "QCOM": "Qualcomm", "BA": "Boeing",
    "WMT": "Walmart", "XOM": "Exxon Mobil", "CVX": "Chevron", "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF", "IWM": "Russell 2000 ETF", "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum",
    "XAUUSD": "Gold", "EURUSD": "EUR USD", "GBPUSD": "GBP USD", "USDJPY": "USD JPY",
}

_COMPANY_KEYWORDS = {
    "AAPL": ("apple", "iphone", "ipad", "mac", "tim cook", "app store"),
    "MSFT": ("microsoft", "windows", "azure", "copilot", "office"),
    "NVDA": ("nvidia", "gpu", "gpu chips", "jensen huang"),
    "AMZN": ("amazon", "aws", "prime", "jeff bezos"),
    "META": ("meta", "facebook", "instagram", "whatsapp", "zuckerberg"),
    "TSLA": ("tesla", "elon musk", "model 3", "model y", "cybertruck"),
    "GOOGL": ("alphabet", "google", "youtube", "waymo", "gemini"),
    "GOOG": ("alphabet", "google", "youtube", "waymo", "gemini"),
    "AVGO": ("broadcom", "avgo", "vmware"), "AMD": ("amd", "advanced micro devices", "radeon"),
    "PLTR": ("palantir", "foundry", "aip"), "COIN": ("coinbase", "coin"),
    "INTC": ("intel", "intel foundry"), "JPM": ("jpmorgan", "jp morgan", "jamie dimon"),
    "NFLX": ("netflix"), "ORCL": ("oracle", "oci"), "CRM": ("salesforce", "slack"),
    "MU": ("micron", "dram", "nand"), "QCOM": ("qualcomm", "snapdragon"), "BA": ("boeing", "737", "787"),
    "WMT": ("walmart"), "XOM": ("exxon", "exxonmobil", "exxon mobil"), "CVX": ("chevron"),
    "SPY": ("s&p 500", "sp500", "sp 500"), "QQQ": ("nasdaq 100", "nasdaq-100", "qqq"),
    "IWM": ("russell 2000", "russell 2000", "iwm"), "BTCUSD": ("bitcoin", "btc"),
    "ETHUSD": ("ethereum", "ether", "eth"), "XAUUSD": ("gold", "xau", "bullion"),
    "EURUSD": ("eur/usd", "euro", "eurusd"), "GBPUSD": ("gbp/usd", "pound", "sterling", "gbpusd"),
    "USDJPY": ("usd/jpy", "yen", "usdjpy"),
}

_MARKET_TERMS = (
    "stock", "shares", "share price", "earnings", "revenue", "profit", "sales", "forecast", "guidance",
    "analyst", "price target", "target", "valuation", "investor", "market", "trading", "price", "dividend",
    "buyback", "upgrade", "downgrade", "estimate", "outlook", "demand", "supply", "tariff", "regulation",
    "lawsuit", "acquisition", "merger", "partnership", "semiconductor", "chip", "gpu", "ai", "cloud",
    "margin", "capex", "cash flow", "credit", "bond", "yield", "rate", "fed", "inflation", "jobs",
    "oil", "crude", "gold", "silver", "forex", "currency", "bitcoin", "crypto", "ethereum", "etf",
)

_IRRELEVANT_TERMS = (
    "mcp server", "streaming", "tv shows", "movies", "movie", "recipe", "fashion", "celebrity", "wedding",
    "travel guide", "best restaurants", "game review", "gaming guide", "gift guide", "what to watch",
)


@dataclass(frozen=True, slots=True)
class NewsSource:
    priority: int
    name: str
    domain: str
    reliability: float
    specialties: tuple[str, ...]


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
    terms = [symbol]
    if alias and alias.lower() != symbol.lower():
        terms.append(alias)
    return terms


def _asset_route(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol in {"BTCUSD", "ETHUSD"}:
        return "crypto"
    if symbol in {"XAUUSD"}:
        return "gold"
    if symbol in {"EURUSD", "GBPUSD", "USDJPY"}:
        return "fx"
    return "equity"


def _active_sources(symbol: str) -> tuple[NewsSource, ...]:
    route = _asset_route(symbol)
    specialist_domains = {
        "crypto": {"coindesk.com", "cointelegraph.com", "theblock.co", "blockworks.co", "decrypt.co"},
        "gold": {"kitco.com", "oilprice.com"},
        "fx": {"fxstreet.com", "forexfactory.com"},
        "equity": set(),
    }[route]
    return tuple(source for source in NEWS_SOURCES if source.priority <= 19 or source.domain in specialist_domains or source.priority in {29, 30})


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
    text = re.sub(r"\[[^\]]+\]", "", title.lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_tokens(title: str) -> set[str]:
    return {token for token in _normalise_title(title).split() if len(token) > 2}


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
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return published_at >= cutoff


def _title_relevance(item: NewsItemDTO, symbol: str, terms: list[str]) -> tuple[bool, float]:
    title = item.title.lower()
    for bad in _IRRELEVANT_TERMS:
        if bad in title:
            return False, -100.0

    target_terms = list(terms) + list(_COMPANY_KEYWORDS.get(symbol, ()))
    target_terms = [term.lower() for term in target_terms]
    target_hits = sum(1 for term in target_terms if term in title)
    if target_hits == 0:
        return False, -100.0

    market_hits = sum(1 for term in _MARKET_TERMS if term in title)
    if market_hits == 0 and symbol not in {"SPY", "QQQ", "IWM", "BTCUSD", "ETHUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"}:
        return False, -80.0

    score = target_hits * 45.0 + min(market_hits, 4) * 9.0
    if symbol.lower() in title:
        score += 18.0
    alias = _COMPANY_ALIASES.get(symbol)
    if alias and alias.lower() in title:
        score += 12.0
    return True, score


class GDELTNewsProvider:
    async def search(self, query: str, limit: int = 20, timespan: str = "48h") -> list[NewsItemDTO]:
        params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": min(limit, 75), "timespan": timespan, "sort": "datedesc"}
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
        self._semaphore = asyncio.Semaphore(10)

    async def _search_source(self, source: NewsSource, terms: list[str], limit: int) -> list[NewsItemDTO]:
        query_terms = " OR ".join(f'"{term}"' for term in terms)
        query = f"({query_terms}) site:{source.domain}"
        async with self._semaphore:
            try:
                return await self.google.search(query, limit)
            except Exception:
                return []

    def _score(self, item: NewsItemDTO, symbol: str, terms: list[str]) -> float:
        source = _source_for_item(item)
        ok, relevance = _title_relevance(item, symbol, terms)
        if not ok:
            return -1000.0

        source_score = 0.0
        if source:
            source_score = max(0.0, 55.0 - (source.priority - 1) * 1.65) * source.reliability

        freshness = 0.0
        if item.published_at:
            age_minutes = max(0.0, (datetime.now(timezone.utc) - item.published_at).total_seconds() / 60.0)
            freshness = max(0.0, 35.0 - age_minutes / 30.0)

        return relevance + source_score + freshness

    @staticmethod
    def _near_duplicate(a: NewsItemDTO, b: NewsItemDTO) -> bool:
        a_tokens = _title_tokens(a.title)
        b_tokens = _title_tokens(b.title)
        if not a_tokens or not b_tokens:
            return False
        overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
        return overlap >= 0.82

    async def search(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        terms = _search_terms(symbol)
        now = datetime.now(timezone.utc)
        sources = _active_sources(symbol)
        per_source_limit = max(4, min(7, limit + 1))

        source_batches = await asyncio.gather(
            *(self._search_source(source, terms, per_source_limit) for source in sources)
        )
        google_items = [item for batch in source_batches for item in batch]

        # GDELT remains a broad backstop, but it is filtered by the same strict title relevance rules.
        gdelt_items: list[NewsItemDTO] = []
        try:
            gdelt_query = f'({" OR ".join(terms)})'
            gdelt_items = await self.gdelt.search(gdelt_query, max(20, limit * 4), timespan="48h")
        except Exception:
            gdelt_items = []

        custom_items = await self.rss.fetch(settings.rss_urls, limit=max(3, limit // 2)) if settings.rss_urls else []
        candidates = google_items + gdelt_items + custom_items

        # Strict daily window. Unknown timestamps are rejected rather than treated as fresh.
        candidates = [item for item in candidates if _is_recent(item.published_at, 24)]
        for item in candidates:
            item.symbol = symbol

        ranked: list[NewsItemDTO] = []
        seen_urls: set[str] = set()
        for item in sorted(candidates, key=lambda candidate: self._score(candidate, symbol, terms), reverse=True):
            if self._score(item, symbol, terms) <= -500:
                continue
            url_key = _canonical_url(item.url)
            if url_key in seen_urls:
                continue
            if any(self._near_duplicate(item, existing) for existing in ranked):
                continue
            seen_urls.add(url_key)
            ranked.append(item)

        # Keep publisher diversity so one noisy feed cannot fill the entire news block.
        output: list[NewsItemDTO] = []
        per_source_count: dict[str, int] = {}
        for item in ranked:
            source = _source_for_item(item)
            source_label = source.name if source else (item.source or "Unknown source")
            count = per_source_count.get(source_label, 0)
            if count >= 2:
                continue
            per_source_count[source_label] = count + 1
            date_label = item.published_at.strftime("%d %b %Y") if item.published_at else "Date n/a"
            item.title = f"[{date_label}] {item.title}"
            item.source = source_label
            output.append(item)
            if len(output) >= limit:
                break

        # If strict filtering leaves too few items, use a second, still market-focused pass.
        if len(output) < min(3, limit):
            fallback_query = f'"{terms[0]}" OR "{terms[1]}" stock market'
            try:
                fallback = await self.google.search(fallback_query, max(limit * 2, 8))
            except Exception:
                fallback = []
            for item in fallback:
                if not item.published_at or item.published_at < now - timedelta(hours=48):
                    continue
                item.symbol = symbol
                ok, _ = _title_relevance(item, symbol, terms)
                if not ok:
                    continue
                source = _source_for_item(item)
                item.source = source.name if source else (item.source or "Unknown source")
                item.title = f"[{item.published_at.strftime('%d %b %Y')}] {item.title}"
                if not any(self._near_duplicate(item, existing) for existing in output):
                    output.append(item)
                if len(output) >= limit:
                    break

        return output[:limit]

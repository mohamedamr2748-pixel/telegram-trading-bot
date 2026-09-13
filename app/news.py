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

_COMPANY_KEYWORDS = {
    "AAPL": ("apple", "apple inc", "iphone", "ipad", "mac", "tim cook", "app store", "apple shares"),
    "MSFT": ("microsoft", "azure", "copilot", "windows", "office"),
    "NVDA": ("nvidia", "nvda", "jensen huang", "gpu", "cuda", "blackwell"),
    "AMZN": ("amazon", "aws", "prime", "bezos"),
    "META": ("meta", "facebook", "instagram", "whatsapp", "zuckerberg"),
    "TSLA": ("tesla", "elon musk", "model 3", "model y", "cybertruck"),
    "GOOGL": ("alphabet", "google", "youtube", "waymo", "gemini"),
    "GOOG": ("alphabet", "google", "youtube", "waymo", "gemini"),
    "AVGO": ("broadcom", "avgo", "vmware"),
    "AMD": ("amd", "advanced micro devices", "radeon", "ryzen"),
    "PLTR": ("palantir", "foundry", "aip"),
    "COIN": ("coinbase", "coinbase stock"),
    "INTC": ("intel", "intel foundry"),
    "JPM": ("jpmorgan", "jp morgan", "jamie dimon"),
    "NFLX": ("netflix"),
    "ORCL": ("oracle", "oci"),
    "CRM": ("salesforce", "slack"),
    "MU": ("micron", "dram", "nand"),
    "QCOM": ("qualcomm", "snapdragon"),
    "BA": ("boeing", "737", "787"),
    "WMT": ("walmart"),
    "XOM": ("exxon", "exxonmobil", "exxon mobil"),
    "CVX": ("chevron"),
    "SPY": ("s&p 500", "sp500", "sp 500", "spy"),
    "QQQ": ("nasdaq 100", "nasdaq-100", "qqq"),
    "IWM": ("russell 2000", "iwm"),
    "BTCUSD": ("bitcoin", "btc"),
    "ETHUSD": ("ethereum", "ether", "eth"),
    "XAUUSD": ("gold", "xau", "bullion"),
    "EURUSD": ("eur/usd", "euro", "eurusd"),
    "GBPUSD": ("gbp/usd", "pound", "sterling", "gbpusd"),
    "USDJPY": ("usd/jpy", "yen", "usdjpy"),
}

_MARKET_TERMS = (
    "stock", "stocks", "share", "shares", "share price", "earnings", "revenue", "profit", "profits",
    "sales", "guidance", "forecast", "analyst", "price target", "target price", "valuation", "investor",
    "market", "markets", "trading", "price", "dividend", "buyback", "upgrade", "downgrade", "estimate",
    "outlook", "demand", "supply", "tariff", "regulation", "lawsuit", "acquisition", "merger", "partnership",
    "semiconductor", "chip", "gpu", "ai", "cloud", "margin", "capex", "cash flow", "credit", "bond", "yield",
    "rate", "fed", "inflation", "jobs", "oil", "crude", "gold", "silver", "forex", "currency", "bitcoin",
    "crypto", "ethereum", "etf", "options", "futures",
)

_STRONG_TRADING_TERMS = (
    "stock", "stocks", "share", "shares", "earnings", "revenue", "profit", "sales", "guidance", "forecast",
    "analyst", "price target", "valuation", "investor", "market", "markets", "trading", "dividend", "buyback",
    "upgrade", "downgrade", "estimate", "outlook", "acquisition", "merger", "partnership", "tariff", "regulation",
    "lawsuit", "demand", "supply", "fed", "inflation", "interest rate", "yield", "futures", "options", "etf",
)

_IRRELEVANT_TITLE_PATTERNS = (
    "mcp server", "recipe", "fashion", "celebrity", "wedding", "travel guide", "best restaurants", "game review",
    "gaming guide", "gift guide", "what to watch", "movies to stream", "tv shows", "streaming service",
)

_CONSUMER_ONLY_TERMS = (
    "iphone price", "iphone deal", "iphone deals", "ipad deal", "macbook deal", "apple tv", "apple music",
    "streaming", "movies", "tv shows", "watch this weekend", "price slashed", "discount", "coupon",
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


def _search_terms(symbol: str) -> list[str]:
    symbol = symbol.strip().upper()
    alias = _COMPANY_ALIASES.get(symbol)
    terms = [symbol]
    if alias and alias.lower() != symbol.lower():
        terms.append(alias)
    terms.extend(_COMPANY_KEYWORDS.get(symbol, ())[:3])
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(term for term in terms if term))


def _asset_route(symbol: str) -> str:
    if symbol in {"BTCUSD", "ETHUSD"}:
        return "crypto"
    if symbol == "XAUUSD":
        return "gold"
    if symbol in {"EURUSD", "GBPUSD", "USDJPY"}:
        return "fx"
    return "equity"


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


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def _title_tokens(title: str) -> set[str]:
    return {token for token in _normalise_text(title).split() if len(token) > 2}


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
    source_name = (item.source or "").strip().lower()
    for source in NEWS_SOURCES:
        if source_name == source.name.lower():
            return source
    return None


def _is_recent(published_at: datetime | None, hours: int = 48) -> bool:
    return bool(published_at and published_at >= datetime.now(timezone.utc) - timedelta(hours=hours))


def _query_for_source(symbol: str, source: NewsSource) -> str:
    terms = _search_terms(symbol)
    quoted = " OR ".join(f'"{term}"' for term in terms)
    asset = _asset_route(symbol)
    if asset == "equity":
        context = "stock OR shares OR earnings OR revenue OR market OR investor"
    elif asset == "crypto":
        context = "price OR market OR ETF OR regulation OR trading OR crypto"
    elif asset == "gold":
        context = "gold OR bullion OR metals OR futures OR price OR market"
    else:
        context = "forex OR currency OR central bank OR interest rate OR trading"
    return f"({quoted}) ({context}) site:{source.domain} when:2d"


def _title_relevance(item: NewsItemDTO, symbol: str) -> tuple[bool, float]:
    title = _normalise_text(item.title)
    terms = [term.lower() for term in (_COMPANY_KEYWORDS.get(symbol, ()) + (symbol,))]
    target_hits = sum(1 for term in terms if term and term in title)
    if target_hits == 0:
        return False, -1000.0

    if any(pattern in title for pattern in _IRRELEVANT_TITLE_PATTERNS):
        return False, -1000.0

    strong_hits = sum(1 for term in _STRONG_TRADING_TERMS if term in title)
    market_hits = sum(1 for term in _MARKET_TERMS if term in title)

    # Consumer/product stories need a stronger market signal. This eliminates
    # things such as "iPhone price slashed" and "Apple TV" from an equity feed
    # while keeping genuine company-market stories involving products.
    consumer_hits = sum(1 for term in _CONSUMER_ONLY_TERMS if term in title)
    if consumer_hits and strong_hits == 0:
        return False, -900.0

    # Generic company-name matches are not enough; there must be a meaningful
    # financial/market/operational signal in the headline.
    route = _asset_route(symbol)
    minimum_market_signal = 1 if route in {"crypto", "gold", "fx"} else 1
    if market_hits < minimum_market_signal:
        return False, -800.0

    score = target_hits * 30.0 + min(strong_hits, 4) * 18.0 + min(market_hits, 5) * 5.0
    if symbol.lower() in title:
        score += 22.0
    alias = _COMPANY_ALIASES.get(symbol)
    if alias and alias.lower() in title:
        score += 12.0
    return True, score


def _specialty_bonus(symbol: str, source: NewsSource) -> float:
    route = _asset_route(symbol)
    if route == "crypto" and "crypto" in source.specialties:
        return 15.0
    if route == "gold" and any(term in source.specialties for term in ("gold", "metals", "commodities")):
        return 12.0
    if route == "fx" and any(term in source.specialties for term in ("fx", "central banks")):
        return 12.0
    return 0.0


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

        results: list[NewsItemDTO] = []
        for article in payload.get("articles", []):
            url = article.get("url") or article.get("documentidentifier")
            title = article.get("title") or "Untitled"
            if not url:
                continue
            results.append(
                NewsItemDTO(
                    title=title,
                    url=url,
                    source=str(article.get("domain") or "GDELT"),
                    published_at=_parse_datetime(article.get("seendate") or article.get("date")),
                )
            )
        return results


class GoogleNewsRSSProvider:
    base_url = "https://news.google.com/rss/search"

    async def search(self, query: str, limit: int = 8) -> list[NewsItemDTO]:
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
                output.append(
                    NewsItemDTO(
                        title=title,
                        url=link,
                        source=source or "Google News",
                        published_at=_parse_datetime(entry.get("published") or entry.get("updated")),
                    )
                )
            return output

        return await asyncio.to_thread(parse)


class RSSNewsProvider:
    async def fetch(self, urls: list[str], limit: int = 8) -> list[NewsItemDTO]:
        def parse(url: str) -> list[NewsItemDTO]:
            feed = feedparser.parse(url)
            results: list[NewsItemDTO] = []
            for entry in feed.entries[:limit]:
                link = entry.get("link")
                title = entry.get("title")
                if not link or not title:
                    continue
                results.append(
                    NewsItemDTO(
                        title=title,
                        url=link,
                        source=feed.feed.get("title", url),
                        published_at=_parse_datetime(entry.get("published") or entry.get("updated")),
                    )
                )
            return results

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

    async def _search_source(self, source: NewsSource, symbol: str, limit: int) -> list[NewsItemDTO]:
        query = _query_for_source(symbol, source)
        async with self._semaphore:
            try:
                return await self.google.search(query, limit)
            except Exception:
                return []

    def _score(self, item: NewsItemDTO, symbol: str) -> float:
        ok, relevance = _title_relevance(item, symbol)
        if not ok:
            return -1000.0
        source = _source_for_item(item)
        source_score = 0.0
        specialty_bonus = 0.0
        if source:
            source_score = max(0.0, 58.0 - (source.priority - 1) * 1.75) * source.reliability
            specialty_bonus = _specialty_bonus(symbol, source)
        freshness = 0.0
        if item.published_at:
            age_hours = max(0.0, (datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600.0)
            freshness = max(0.0, 34.0 - age_hours * 1.15)
        return relevance + source_score + specialty_bonus + freshness

    @staticmethod
    def _near_duplicate(a: NewsItemDTO, b: NewsItemDTO) -> bool:
        a_tokens = _title_tokens(a.title)
        b_tokens = _title_tokens(b.title)
        if not a_tokens or not b_tokens:
            return False
        overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
        return overlap >= 0.78

    async def search(self, symbol: str, limit: int = 8) -> list[NewsItemDTO]:
        symbol = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        sources = NEWS_SOURCES  # Keep the full 30-source universe available for every asset.

        source_batches = await asyncio.gather(
            *(self._search_source(source, symbol, max(5, min(8, limit + 2))) for source in sources)
        )
        google_items = [item for batch in source_batches for item in batch]

        # Broad fallback: useful for outlets not surfaced by a source-specific Google feed.
        gdelt_items: list[NewsItemDTO] = []
        try:
            terms = _search_terms(symbol)
            gdelt_query = " OR ".join(f'\"{term}\"' for term in terms[:4])
            gdelt_items = await self.gdelt.search(gdelt_query, max(24, limit * 4), timespan="48h")
        except Exception:
            pass

        custom_items = await self.rss.fetch(settings.rss_urls, limit=max(4, limit // 2)) if settings.rss_urls else []
        candidates = google_items + gdelt_items + custom_items
        candidates = [item for item in candidates if _is_recent(item.published_at, 48)]
        for item in candidates:
            item.symbol = symbol

        # Rank first, then de-duplicate. A higher-priority source wins when several
        # publishers carry the same story.
        ranked_candidates = sorted(candidates, key=lambda item: self._score(item, symbol), reverse=True)
        ranked: list[NewsItemDTO] = []
        seen_urls: set[str] = set()
        for item in ranked_candidates:
            score = self._score(item, symbol)
            if score <= -500:
                continue
            url_key = _canonical_url(item.url)
            if url_key in seen_urls:
                continue
            if any(self._near_duplicate(item, existing) for existing in ranked):
                continue
            seen_urls.add(url_key)
            ranked.append(item)

        # Preserve publisher diversity while still allowing a top publisher to
        # contribute up to two strong stories.
        output: list[NewsItemDTO] = []
        source_counts: dict[str, int] = {}
        for item in ranked:
            source = _source_for_item(item)
            source_label = source.name if source else (item.source or "Unknown source")
            if source_counts.get(source_label, 0) >= 2:
                continue
            source_counts[source_label] = source_counts.get(source_label, 0) + 1
            item.source = source_label
            date_label = item.published_at.strftime("%d %b %Y") if item.published_at else "Date n/a"
            item.title = f"[{date_label}] {item.title}"
            item.relevance = int(round(self._score(item, symbol)))
            output.append(item)
            if len(output) >= limit:
                break

        # Do not replace strict results with low-quality generic search results.
        # If there are fewer than 3 valid stories, run one broader market query as
        # a last resort, but keep the same title relevance filter and 48h window.
        if len(output) < min(3, limit):
            terms = _search_terms(symbol)
            fallback_query = f'({" OR ".join(f"\"{term}\"" for term in terms[:4])}) (stock OR shares OR earnings OR market OR investor) when:2d'
            try:
                fallback_items = await self.google.search(fallback_query, max(12, limit * 2))
            except Exception:
                fallback_items = []
            for item in fallback_items:
                if not _is_recent(item.published_at, 48):
                    continue
                ok, _ = _title_relevance(item, symbol)
                if not ok:
                    continue
                item.symbol = symbol
                if any(self._near_duplicate(item, existing) for existing in output):
                    continue
                source = _source_for_item(item)
                item.source = source.name if source else (item.source or "Unknown source")
                item.title = f"[{item.published_at.strftime('%d %b %Y')}] {item.title}"
                output.append(item)
                if len(output) >= limit:
                    break

        return output[:limit]

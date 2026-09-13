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
    "AAPL": ("apple", "aapl", "apple shares", "apple stock", "iphone", "ipad", "mac", "tim cook", "app store"),
    "MSFT": ("microsoft", "msft", "microsoft stock", "microsoft shares", "azure", "copilot"),
    "NVDA": ("nvidia", "nvda", "nvidia stock", "nvidia shares", "gpu", "jensen huang"),
    "AMZN": ("amazon", "amzn", "amazon stock", "amazon shares", "aws", "prime"),
    "META": ("meta", "meta stock", "meta shares", "facebook", "instagram", "whatsapp", "zuckerberg"),
    "TSLA": ("tesla", "tsla", "tesla stock", "tesla shares", "elon musk", "model 3", "model y", "cybertruck"),
    "GOOGL": ("alphabet", "google", "googl", "goog", "alphabet stock", "google stock", "youtube", "waymo", "gemini"),
    "GOOG": ("alphabet", "google", "googl", "goog", "alphabet stock", "google stock", "youtube", "waymo", "gemini"),
    "AVGO": ("broadcom", "avgo", "broadcom stock", "broadcom shares", "vmware"),
    "AMD": ("amd", "advanced micro devices", "amd stock", "amd shares", "radeon"),
    "PLTR": ("palantir", "pltr", "palantir stock", "palantir shares", "foundry", "aip"),
    "COIN": ("coinbase", "coin", "coinbase stock", "coinbase shares"),
    "INTC": ("intel", "intc", "intel stock", "intel shares", "intel foundry"),
    "JPM": ("jpmorgan", "jp morgan", "jpm", "jpmorgan stock", "jamie dimon"),
    "NFLX": ("netflix", "nflx", "netflix stock", "netflix shares"),
    "ORCL": ("oracle", "orcl", "oracle stock", "oracle shares", "oci"),
    "CRM": ("salesforce", "crm", "salesforce stock", "salesforce shares", "slack"),
    "MU": ("micron", "mu", "micron stock", "micron shares", "dram", "nand"),
    "QCOM": ("qualcomm", "qcom", "qualcomm stock", "qualcomm shares", "snapdragon"),
    "BA": ("boeing", "ba", "boeing stock", "boeing shares", "737", "787"),
    "WMT": ("walmart", "wmt", "walmart stock", "walmart shares"),
    "XOM": ("exxon", "exxonmobil", "exxon mobil", "xom", "exxon stock"),
    "CVX": ("chevron", "cvx", "chevron stock", "chevron shares"),
    "SPY": ("s&p 500", "sp500", "sp 500", "spy", "s&p 500 etf"),
    "QQQ": ("nasdaq 100", "nasdaq-100", "qqq", "nasdaq 100 etf"),
    "IWM": ("russell 2000", "iwm", "russell 2000 etf"),
    "BTCUSD": ("bitcoin", "btc", "bitcoin price", "bitcoin market"),
    "ETHUSD": ("ethereum", "eth", "ethereum price", "ethereum market"),
    "XAUUSD": ("gold", "xau", "gold price", "bullion"),
    "EURUSD": ("eur/usd", "eurusd", "euro", "euro dollar"),
    "GBPUSD": ("gbp/usd", "gbpusd", "pound", "sterling"),
    "USDJPY": ("usd/jpy", "usdjpy", "yen"),
}

_MARKET_TERMS = (
    "stock", "stocks", "shares", "share price", "earnings", "revenue", "profit", "sales", "forecast", "guidance",
    "analyst", "price target", "target", "valuation", "investor", "investors", "market", "trading", "price", "dividend",
    "buyback", "upgrade", "downgrade", "estimate", "outlook", "demand", "supply", "tariff", "regulation",
    "lawsuit", "acquisition", "merger", "partnership", "semiconductor", "chip", "gpu", "ai", "cloud",
    "margin", "capex", "cash flow", "credit", "bond", "yield", "rate", "fed", "inflation", "jobs",
    "oil", "crude", "gold", "silver", "forex", "currency", "bitcoin", "crypto", "ethereum", "etf",
)

_DIRECT_MARKET_PHRASES = (
    "shares", "stock", "share price", "earnings", "revenue", "profit", "sales", "guidance", "forecast",
    "analyst", "price target", "valuation", "market cap", "buyback", "dividend", "upgrade", "downgrade",
    "estimate", "outlook", "investor", "investors", "acquisition", "merger", "lawsuit", "regulation", "tariff",
)

_BUSINESS_IMPACT_PHRASES = (
    "demand", "sales", "revenue", "margin", "manufacturing", "factory", "production", "supply chain", "contract",
    "deal", "partnership", "launch", "launches", "new product", "product", "chip", "cloud", "capacity", "orders",
)

_LISTICLE_TERMS = (
    "and more", "five stocks", "six stocks", "seven stocks", "eight stocks", "10 stocks", "top stocks",
    "stocks investors", "stocks to watch", "best stocks", "stocks worth", "couldn't stop buzzing", "cannot stop buzzing",
)

_BROAD_ROUNDUP_TERMS = (
    "dow jones futures", "stock market today", "stock market", "market today", "stocks rise", "stocks fall",
    "stocks gain", "stocks slide", "market roundup", "market wrap", "morning briefing",
)

_LOW_SIGNAL_INVESTING_TERMS = (
    "10 years ago", "20 years ago", "years ago", "better buy for the next decade", "next decade", "would have",
    "if you invested", "investing $", "investing $10", "investing $20", "retirement", "millionaire", "passive income",
    "personal finance", "how to buy", "should you buy", "best stock to buy", "buy for the long term",
)

_IRRELEVANT_TERMS = (
    "mcp server", "mcp servers", "streaming", "tv shows", "movies", "movie", "recipe", "fashion", "celebrity", "wedding",
    "travel guide", "best restaurants", "game review", "gaming guide", "gift guide", "what to watch", "netflix shows",
    "tokenized", "tokenised", "tokenized stock", "tokenised stock", "synthetic stock", "wrapped token", "tokenized aapl",
    "tokenized stocks", "tokenised stocks", "stock token", "stock tokens", "bstocks",
)

_CRYPTO_ONLY_DOMAINS = {"coindesk.com", "cointelegraph.com", "theblock.co", "blockworks.co", "decrypt.co"}
_FX_ONLY_DOMAINS = {"fxstreet.com", "forexfactory.com"}
_METALS_DOMAINS = {"kitco.com"}
_ENERGY_DOMAINS = {"oilprice.com"}


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
    return [symbol, _COMPANY_ALIASES.get(symbol, symbol)]


def _asset_route(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol in {"BTCUSD", "ETHUSD"}:
        return "crypto"
    if symbol == "XAUUSD":
        return "gold"
    if symbol in {"EURUSD", "GBPUSD", "USDJPY"}:
        return "fx"
    return "equity"


def _active_sources(symbol: str) -> tuple[NewsSource, ...]:
    route = _asset_route(symbol)
    specialist_domains = {
        "crypto": _CRYPTO_ONLY_DOMAINS,
        "gold": _METALS_DOMAINS | _ENERGY_DOMAINS,
        "fx": _FX_ONLY_DOMAINS,
        "equity": set(),
    }[route]
    return tuple(source for source in NEWS_SOURCES if source.priority <= 19 or source.domain in specialist_domains or source.priority in {29, 30})


def _source_allowed_for_route(item: NewsItemDTO, symbol: str) -> bool:
    source = _source_for_item(item)
    # Hard allow-list: /news may only surface publishers from NEWS_SOURCES.
    # Google News and GDELT remain discovery layers, not editorial sources.
    if source is None:
        return False
    route = _asset_route(symbol)
    domain = source.domain
    if route != "crypto" and domain in _CRYPTO_ONLY_DOMAINS:
        return False
    if route != "fx" and domain in _FX_ONLY_DOMAINS:
        return False
    if route not in {"gold", "crypto"} and domain in _METALS_DOMAINS:
        return False
    if route not in {"gold", "crypto"} and domain in _ENERGY_DOMAINS:
        return False
    return True


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


def _search_query(symbol: str, source: NewsSource) -> str:
    symbol = symbol.upper()
    alias = _COMPANY_ALIASES.get(symbol, symbol)
    route = _asset_route(symbol)
    if route == "equity":
        phrases = [
            f'"{symbol}"', f'"{alias} shares"', f'"{alias} stock"', f'"{alias} earnings"',
            f'"{alias} revenue"', f'"{alias} guidance"', f'"{alias} analyst"', f'"{alias} investors"',
            f'"{alias} price target"',
        ]
        if symbol in {"AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA"}:
            phrases.append(f'"{alias} demand"')
        query = " OR ".join(phrases)
    elif route == "crypto":
        query = f'"{alias}" OR "{symbol}" market OR price OR crypto'
    elif route == "gold":
        query = '"gold" OR "XAUUSD" price OR market OR bullion'
    else:
        query = f'"{alias}" OR "{symbol}" forex OR currency OR rate'
    return f"({query}) site:{source.domain} when:1d"


def _entity_hits(title: str, symbol: str) -> tuple[int, bool, bool]:
    normalized = _normalise_title(title)
    lower = normalized.lower()
    alias = _COMPANY_ALIASES.get(symbol, symbol).lower()
    ticker_hit = bool(re.search(rf"\b{re.escape(symbol.lower())}\b", normalized))
    alias_hit = bool(alias and re.search(rf"\b{re.escape(alias)}\b", normalized))
    keywords = _COMPANY_KEYWORDS.get(symbol, (symbol.lower(),))
    keyword_hits = sum(1 for term in keywords if term.lower() in lower)
    return keyword_hits, ticker_hit, alias_hit


def _other_company_mentions(title: str, symbol: str) -> int:
    normalized = _normalise_title(title)
    count = 0
    for other_symbol, alias in _COMPANY_ALIASES.items():
        if other_symbol == symbol:
            continue
        patterns = [other_symbol.lower()]
        if alias:
            patterns.append(alias.lower())
        if any(re.search(rf"\b{re.escape(pattern)}\b", normalized) for pattern in patterns):
            count += 1
    return count


def _title_relevance(item: NewsItemDTO, symbol: str, terms: list[str]) -> tuple[bool, float]:
    title = _normalise_title(item.title)
    if any(bad in title for bad in _IRRELEVANT_TERMS):
        return False, -1000.0
    if any(low in title for low in _LOW_SIGNAL_INVESTING_TERMS):
        return False, -1000.0
    if not _source_allowed_for_route(item, symbol):
        return False, -1000.0

    route = _asset_route(symbol)
    keyword_hits, ticker_hit, alias_hit = _entity_hits(item.title, symbol)
    if not ticker_hit and not alias_hit and keyword_hits == 0:
        return False, -1000.0

    direct_hits = sum(1 for term in _DIRECT_MARKET_PHRASES if term in title)
    business_hits = sum(1 for term in _BUSINESS_IMPACT_PHRASES if term in title)
    listicle_hits = sum(1 for term in _LISTICLE_TERMS if term in title)
    broad_hits = sum(1 for term in _BROAD_ROUNDUP_TERMS if term in title)
    other_companies = _other_company_mentions(item.title, symbol)

    if route == "equity":
        alias = _COMPANY_ALIASES.get(symbol, symbol).lower()
        company_context = any(
            phrase in title
            for phrase in (
                f"{alias} shares", f"{alias} stock", f"{alias} earnings", f"{alias} revenue",
                f"{alias} guidance", f"{alias} analyst", f"{alias} investors", f"{alias} price",
                f"{alias} valuation", f"{alias} demand", f"{alias} sales", f"{alias} profit",
                f"{alias} launches", f"{alias} launch", f"{alias} product",
            )
        )
        if other_companies >= 2 and not ticker_hit:
            return False, -1000.0
        if listicle_hits and not ticker_hit:
            return False, -1000.0
        if broad_hits and not ticker_hit and not company_context:
            return False, -1000.0
        if not ticker_hit and not company_context and direct_hits == 0 and business_hits == 0:
            return False, -1000.0

        score = 55.0
        if ticker_hit:
            score += 60.0
        if company_context:
            score += 40.0
        if alias_hit:
            score += 10.0
        score += min(keyword_hits, 4) * 7.0
        score += min(direct_hits, 5) * 17.0
        score += min(business_hits, 3) * 5.0
        if other_companies:
            score -= min(other_companies, 3) * 25.0
        if listicle_hits:
            score -= 80.0 * listicle_hits
        if broad_hits:
            score -= 35.0 * broad_hits

        consumer_terms = ("iphone", "ipad", "mac", "app store", "watch", "airpods")
        consumer_hits = sum(1 for term in consumer_terms if term in title)
        strong_market_hits = sum(1 for term in _DIRECT_MARKET_PHRASES if term in title)
        if consumer_hits and strong_market_hits == 0 and not ticker_hit:
            return False, -1000.0
        if consumer_hits:
            score -= max(0.0, consumer_hits - 1.0) * 10.0
        if title.startswith("latest ") and "stock news" in title:
            score -= 12.0
        return True, score

    market_hits = sum(1 for term in _MARKET_TERMS if term in title)
    score = 65.0 + (40.0 if ticker_hit else 0.0) + (20.0 if alias_hit else 0.0)
    score += min(market_hits, 5) * 8.0
    if listicle_hits:
        score -= 30.0 * listicle_hits
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

    async def _search_source(self, source: NewsSource, symbol: str, limit: int) -> list[NewsItemDTO]:
        query = _search_query(symbol, source)
        async with self._semaphore:
            try:
                return await self.google.search(query, limit)
            except Exception:
                return []

    def _score(self, item: NewsItemDTO, symbol: str, terms: list[str]) -> float:
        ok, relevance = _title_relevance(item, symbol, terms)
        if not ok:
            return -1000.0
        source = _source_for_item(item)
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
        source_batches = await asyncio.gather(*(self._search_source(source, symbol, per_source_limit) for source in sources))
        google_items = [item for batch in source_batches for item in batch]

        gdelt_items: list[NewsItemDTO] = []
        try:
            alias = _COMPANY_ALIASES.get(symbol, symbol)
            gdelt_query = f'("{symbol}" OR "{alias} shares" OR "{alias} stock" OR "{alias} earnings" OR "{alias} revenue")'
            gdelt_items = await self.gdelt.search(gdelt_query, max(20, limit * 4), timespan="48h")
        except Exception:
            gdelt_items = []

        custom_items = await self.rss.fetch(settings.rss_urls, limit=max(3, limit // 2)) if settings.rss_urls else []
        candidates = google_items + gdelt_items + custom_items
        candidates = [item for item in candidates if _is_recent(item.published_at, 24) and _source_allowed_for_route(item, symbol)]
        for item in candidates:
            item.symbol = symbol

        ranked: list[NewsItemDTO] = []
        seen_urls: set[str] = set()
        for item in sorted(candidates, key=lambda candidate: self._score(candidate, symbol, terms), reverse=True):
            score = self._score(item, symbol, terms)
            if score <= -500:
                continue
            url_key = _canonical_url(item.url)
            if url_key in seen_urls:
                continue
            if any(self._near_duplicate(item, existing) for existing in ranked):
                continue
            seen_urls.add(url_key)
            ranked.append(item)

        output: list[NewsItemDTO] = []
        per_source_count: dict[str, int] = {}
        for item in ranked:
            source = _source_for_item(item)
            if source is None:
                continue
            source_label = source.name
            count = per_source_count.get(source_label, 0)
            if count >= 2:
                continue
            per_source_count[source_label] = count + 1
            date_label = item.published_at.strftime("%d %b %Y")
            item.title = f"[{date_label}] {item.title}"
            item.source = source_label
            output.append(item)
            if len(output) >= limit:
                break

        if len(output) < min(3, limit):
            fallback_query = _search_query(terms[0] if terms else symbol, NEWS_SOURCES[0]).replace("site:reuters.com", "")
            try:
                fallback = await self.google.search(fallback_query, max(limit * 2, 8))
            except Exception:
                fallback = []
            for item in fallback:
                if not item.published_at or item.published_at < now - timedelta(hours=48):
                    continue
                item.symbol = symbol
                if not _source_allowed_for_route(item, symbol):
                    continue
                ok, _ = _title_relevance(item, symbol, terms)
                if not ok:
                    continue
                source = _source_for_item(item)
                if source is None:
                    continue
                item.source = source.name
                item.title = f"[{item.published_at.strftime('%d %b %Y')}] {item.title}"
                if not any(self._near_duplicate(item, existing) for existing in output):
                    output.append(item)
                if len(output) >= limit:
                    break

        return output[:limit]

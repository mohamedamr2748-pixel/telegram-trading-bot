from app.domain import NewsItemDTO
from app.news import _title_relevance


def terms_for(symbol: str) -> list[str]:
    return [symbol, "Apple"] if symbol == "AAPL" else [symbol]


def test_rejects_unrelated_tradingview_story_for_aapl() -> None:
    item = NewsItemDTO(title="[13 Sep 2026] TradingView MCP Server — Connect Claude, other MCP clients", url="https://www.tradingview.com/example", source="TradingView")
    assert _title_relevance(item, "AAPL", terms_for("AAPL"))[0] is False


def test_rejects_consumer_only_apple_story() -> None:
    item = NewsItemDTO(title="iPhone 17 Price Slashed Further After New Price Hike", url="https://www.forbes.com/example", source="Forbes")
    assert _title_relevance(item, "AAPL", terms_for("AAPL"))[0] is False


def test_rejects_multi_stock_listicle() -> None:
    item = NewsItemDTO(title="GameStop, Oracle, Apple and More: Five Stocks Investors Couldn't Stop Buzzing About This Week", url="https://www.tradingview.com/example", source="TradingView")
    assert _title_relevance(item, "AAPL", terms_for("AAPL"))[0] is False


def test_rejects_broad_market_roundup_when_aapl_is_only_a_mention() -> None:
    item = NewsItemDTO(title="Dow Jones Futures: Fed Rate Hike Seen As Oil, Yields Pressure Stocks; Apple, Moderna Are New Buys", url="https://www.investors.com/example", source="Investor's Business Daily")
    assert _title_relevance(item, "AAPL", terms_for("AAPL"))[0] is False


def test_accepts_direct_aapl_market_story() -> None:
    item = NewsItemDTO(title="Apple shares rise as analysts lift price target after strong earnings", url="https://www.reuters.com/example", source="Reuters")
    ok, score = _title_relevance(item, "AAPL", terms_for("AAPL"))
    assert ok is True
    assert score > 100


def test_accepts_aapl_business_impact_story() -> None:
    item = NewsItemDTO(title="Apple launches new chip as analysts raise revenue outlook", url="https://www.cnbc.com/example", source="CNBC")
    assert _title_relevance(item, "AAPL", terms_for("AAPL"))[0] is True

from app.domain import NewsItemDTO
from app.news import _title_relevance


def test_rejects_unrelated_tradingview_story_for_aapl() -> None:
    item = NewsItemDTO(
        title="[13 Sep 2026] TradingView MCP Server — Connect Claude, ChatGPT and other MCP clients - TradingView",
        url="https://www.tradingview.com/example",
        source="TradingView",
    )
    assert _title_relevance(item, "AAPL")[0] is False


def test_rejects_consumer_only_apple_story() -> None:
    item = NewsItemDTO(
        title="iPhone 17 Price Slashed Further After New Price Hike",
        url="https://www.forbes.com/example",
        source="Forbes",
    )
    assert _title_relevance(item, "AAPL")[0] is False


def test_keeps_market_relevant_apple_story() -> None:
    item = NewsItemDTO(
        title="Apple shares rise as analysts lift price target after strong earnings",
        url="https://www.reuters.com/example",
        source="Reuters",
    )
    ok, score = _title_relevance(item, "AAPL")
    assert ok is True
    assert score > 0

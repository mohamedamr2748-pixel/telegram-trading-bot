from app.chart_display_symbols import chart_display_symbol
from app.symbol_aliases import canonical_symbol


def test_canonical_market_symbols_use_friendly_chart_labels():
    assert chart_display_symbol("^GSPC") == "S&P 500"
    assert chart_display_symbol("^NDX") == "NASDAQ-100"
    assert chart_display_symbol("^IXIC") == "NASDAQ Composite"
    assert chart_display_symbol("^DJI") == "Dow Jones"
    assert chart_display_symbol("GC=F") == "Gold"


def test_existing_user_friendly_symbols_remain_friendly():
    assert chart_display_symbol("SP500") == "S&P 500"
    assert chart_display_symbol("NASDAQ-100") == "NASDAQ-100"
    assert chart_display_symbol("Gold") == "Gold"
    assert chart_display_symbol("AAPL") == "AAPL"


def test_friendly_names_resolve_back_to_provider_symbols():
    assert canonical_symbol("S&P 500") == "^GSPC"
    assert canonical_symbol("NASDAQ-100") == "^NDX"
    assert canonical_symbol("NASDAQ Composite") == "^IXIC"
    assert canonical_symbol("Gold") == "GC=F"

from app.chart_display_symbols import chart_display_symbol


def test_canonical_s_and_p_symbols_use_friendly_chart_labels():
    assert chart_display_symbol("^GSPC") == "SP500"
    assert chart_display_symbol("^NDX") == "NASDAQ100"
    assert chart_display_symbol("^IXIC") == "NASDAQ"


def test_existing_user_friendly_symbols_are_unchanged():
    assert chart_display_symbol("SP500") == "SP500"
    assert chart_display_symbol("NASDAQ-100") == "NASDAQ-100"
    assert chart_display_symbol("AAPL") == "AAPL"

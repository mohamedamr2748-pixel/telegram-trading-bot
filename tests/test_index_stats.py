from app import charts
from app.domain import MarketQuote
from app.index_stats import _index_rows, install


def test_index_rows_use_data_instead_of_stock_only_n_a_fields():
    quote = MarketQuote(
        symbol="SP500",
        asset_class="index",
        price=7581,
        previous_close=7620,
        year_high=7817,
        year_low=6317,
        market_status="open",
    )
    rows = _index_rows(
        "SP500",
        quote,
        {"Open": "7,612", "High": "7,617", "Low": "7,573", "Volume": "1.23B"},
        -0.51,
        fmt_value=charts._fmt_value,
        fmt_percent=charts._fmt_percent,
        status_text=charts._status_text,
    )

    flattened = [value for row in rows for _, value in row]
    assert all(value != "n/a" for value in flattened)
    assert rows[0] == [
        ("Open", "7,612"),
        ("Volume", "1.23B"),
        ("Previous", "7,620"),
    ]
    assert rows[1][1] == ("52-wk high", "7,817")
    assert rows[2] == [
        ("Low", "7,573"),
        ("Day change", "-0.51%"),
        ("Session", "OPEN"),
    ]


def test_install_preserves_non_index_stats():
    original = charts._asset_stats_rows
    install(charts)
    try:
        stock_quote = MarketQuote(symbol="AAPL", asset_class="stock", price=100)
        rows = charts._asset_stats_rows(
            "AAPL",
            stock_quote,
            {"Open": "99", "High": "101", "Low": "98", "Volume": "10M"},
            1.0,
        )
        assert rows[0][0] == ("Open", "99")
        assert rows[0][1][0] == "Mkt cap"
    finally:
        charts._asset_stats_rows = original

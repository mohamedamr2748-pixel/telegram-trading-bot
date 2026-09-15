from app.symbol_aliases import canonical_symbol


def test_nasdaq100_aliases_resolve_to_ndx():
    assert canonical_symbol("NASDAQ100") == "^NDX"
    assert canonical_symbol("NASDAQ-100") == "^NDX"
    assert canonical_symbol("nasdaq 100") == "^NDX"


def test_existing_sp500_alias_is_preserved():
    assert canonical_symbol("SP500") == "^GSPC"
    assert canonical_symbol("SP-500") == "^GSPC"

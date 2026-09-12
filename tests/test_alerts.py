import math

import pytest

from app.alerts import validate_price_alert, validate_symbol


@pytest.mark.parametrize("condition", ["above", "below", "pct_up", "pct_down"])
def test_validate_price_alert_accepts_supported_conditions(condition: str) -> None:
    assert validate_price_alert(condition, 10.0) == condition


def test_validate_price_alert_normalises_condition() -> None:
    assert validate_price_alert(" ABOVE ", 10.0) == "above"


def test_validate_price_alert_rejects_unknown_condition() -> None:
    with pytest.raises(ValueError, match="Condition must be"):
        validate_price_alert("crosses", 10.0)


def test_validate_price_alert_rejects_non_finite_thresholds() -> None:
    for value in [math.inf, -math.inf, math.nan]:
        with pytest.raises(ValueError, match="finite"):
            validate_price_alert("above", value)


def test_validate_price_alert_rejects_negative_percentage() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        validate_price_alert("pct_down", -1.0)


def test_validate_symbol_normalises_case_and_spacing() -> None:
    assert validate_symbol("  aapl  ") == "AAPL"


def test_validate_symbol_rejects_empty_or_whitespace_symbols() -> None:
    with pytest.raises(ValueError, match="valid symbol"):
        validate_symbol("   ")


def test_validate_symbol_rejects_symbols_with_spaces() -> None:
    with pytest.raises(ValueError, match="valid symbol"):
        validate_symbol("BRK B")

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class DecimalPrice(float):
    """Float value that renders as tidy decimal market-price text."""

    def __str__(self) -> str:
        return _format_decimal_price(self)

    def __format__(self, format_spec: str) -> str:
        if not format_spec or "e" in format_spec.lower() or "g" in format_spec.lower():
            return _format_decimal_price(self)
        return super().__format__(format_spec)


def _format_decimal_price(value: float) -> str:
    number = float(value)
    text = f"{number:,.8f}"
    return text.rstrip("0").rstrip(".") or "0"


def _decimal_price(value: float | None) -> DecimalPrice | None:
    return None if value is None else DecimalPrice(value)


@dataclass(slots=True)
class MarketQuote:
    symbol: str
    asset_class: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float = 0.0
    change: float | None = None
    change_percent: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "unknown"
    market_status: str = "unknown"
    previous_close: float | None = None
    year_high: float | None = None
    year_low: float | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    eps: float | None = None
    pre_market_price: float | None = None
    post_market_price: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "price",
            "open",
            "high",
            "low",
            "previous_close",
            "year_high",
            "year_low",
            "pre_market_price",
            "post_market_price",
        ):
            setattr(self, field_name, _decimal_price(getattr(self, field_name)))

    @property
    def is_stale(self) -> bool:
        return (datetime.now(timezone.utc) - self.timestamp.astimezone(timezone.utc)).total_seconds() > 300


@dataclass(slots=True)
class NewsItemDTO:
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    relevance: int = 0
    urgency: int = 0
    symbol: str | None = None


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

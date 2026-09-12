from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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

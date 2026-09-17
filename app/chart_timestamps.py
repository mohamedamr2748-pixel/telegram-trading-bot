from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import matplotlib.dates as mdates
import pandas as pd

UTC = "UTC"
TimestampMode = Literal["intraday", "daily", "weekly", "monthly"]


@dataclass(frozen=True, slots=True)
class TimestampRule:
    key: str
    mode: TimestampMode
    tick_count: int = 6


TIMESTAMP_RULES: dict[str, TimestampRule] = {
    "1M": TimestampRule("1M", "intraday"),
    "5M": TimestampRule("5M", "intraday"),
    "15M": TimestampRule("15M", "intraday"),
    "30M": TimestampRule("30M", "intraday"),
    "1H": TimestampRule("1H", "intraday"),
    "4H": TimestampRule("4H", "intraday"),
    "1D": TimestampRule("1D", "daily"),
    "1W": TimestampRule("1W", "weekly"),
    "1MO": TimestampRule("1MO", "monthly"),
}


def timeframe_key(timeframe: str) -> str:
    """Normalise a renderer label such as ``4H/chart`` to ``4H``."""
    return (timeframe or "").split("/", 1)[0].strip().upper()


def _normalise_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    values = pd.DatetimeIndex(index)
    if values.tz is None:
        values = values.tz_localize(UTC)
    else:
        values = values.tz_convert(UTC)
    return values.sort_values().drop_duplicates()


def _tick_positions(index: pd.DatetimeIndex, count: int) -> pd.DatetimeIndex:
    if len(index) <= count:
        return index
    positions = [round(i * (len(index) - 1) / (count - 1)) for i in range(count)]
    return pd.DatetimeIndex([index[position] for position in positions])


def _intraday_format(timestamps: pd.DatetimeIndex) -> str:
    same_day = timestamps[0].date() == timestamps[-1].date()
    return "%H:%M" if same_day else "%d %b\n%H:%M"


def _format_for(rule: TimestampRule, timestamps: pd.DatetimeIndex) -> str:
    if rule.mode == "intraday":
        return _intraday_format(timestamps)
    if rule.mode == "daily":
        return "%d %b"
    if rule.mode == "weekly":
        return "%d %b\n%Y"
    return "%b %Y"


def configure_price_x_axis(ax, timeframe: str, index: pd.DatetimeIndex) -> None:
    """Configure a price-chart X-axis from actual observed candle timestamps.

    The button label is treated as the candle interval. We never fabricate a
    timestamp grid from a different timeframe and we never use an automatic
    locator that can produce labels unrelated to the observed candles.
    """
    timestamps = _normalise_index(index)
    if len(timestamps) == 0:
        return

    key = timeframe_key(timeframe)
    rule = TIMESTAMP_RULES.get(key, TimestampRule(key or "unknown", "intraday"))
    x_min = timestamps[0]
    x_max = timestamps[-1]
    if x_max <= x_min:
        delta = {
            "1M": pd.Timedelta(minutes=1),
            "5M": pd.Timedelta(minutes=5),
            "15M": pd.Timedelta(minutes=15),
            "30M": pd.Timedelta(minutes=30),
            "1H": pd.Timedelta(hours=1),
            "4H": pd.Timedelta(hours=4),
            "1D": pd.Timedelta(days=1),
            "1W": pd.Timedelta(weeks=1),
            "1MO": pd.Timedelta(days=31),
        }.get(key, pd.Timedelta(hours=1))
        x_max = x_min + delta

    ax.set_xlim(x_min.to_pydatetime(), x_max.to_pydatetime())
    ticks = _tick_positions(timestamps, rule.tick_count)
    ax.xaxis.set_major_locator(mdates.FixedLocator(mdates.date2num(ticks.to_pydatetime())))
    ax.xaxis.set_major_formatter(mdates.DateFormatter(_format_for(rule, timestamps), tz=UTC))
    ax.xaxis.get_offset_text().set_visible(False)
    ax.tick_params(axis="x", pad=8, length=0)


__all__ = ["TIMESTAMP_RULES", "TimestampRule", "configure_price_x_axis", "timeframe_key"]

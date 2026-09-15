from __future__ import annotations

import io
from typing import Any

import matplotlib.font_manager as fm
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    weight = "bold" if bold else "normal"
    try:
        path = fm.findfont(
            fm.FontProperties(family="DejaVu Sans", weight=weight),
            fallback_to_default=True,
        )
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return ImageFont.load_default()


def _asset_label(symbol: str, quote: Any = None) -> str:
    asset = str(getattr(quote, "asset_class", "") or "").lower()
    if asset == "index" or symbol.startswith("^"):
        return "INDEX"
    if asset == "crypto" or symbol.endswith("-USD"):
        return "CRYPTO"
    if asset in {"commodity", "metal"} or symbol.endswith("=F"):
        return "COMMODITY"
    if asset == "forex":
        return "FOREX"
    return "EQUITY"


def _fmt_price(value: object, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:,.{digits}f}"


def _session_label(quote: Any = None) -> str:
    status = str(getattr(quote, "market_status", "") or "").upper().replace("_", " ")
    if "PRE" in status:
        return "PRE-MARKET"
    if "POST" in status or "AFTER" in status:
        return "AFTER-HOURS"
    if "REGULAR" in status or status == "OPEN":
        return "REGULAR SESSION"
    if "CLOSED" in status:
        return "CLOSED"
    return "UNKNOWN"


def _metadata_values(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    quote: Any = None,
) -> dict[str, str]:
    work = frame.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    work = work.sort_index()

    opening = work["Open"].iloc[0] if "Open" in work.columns and not work.empty else None
    high = work["High"].max() if "High" in work.columns and not work.empty else None
    low = work["Low"].min() if "Low" in work.columns and not work.empty else None

    previous = getattr(quote, "previous_close", None)
    year_high = getattr(quote, "year_high", None)
    year_low = getattr(quote, "year_low", None)
    interval = timeframe.split("/", 1)[1] if "/" in timeframe else timeframe

    return {
        "asset": _asset_label(symbol, quote),
        "interval": interval.upper(),
        "open": _fmt_price(opening),
        "high": _fmt_price(high),
        "low": _fmt_price(low),
        "previous": _fmt_price(previous),
        "day_range": f"{_fmt_price(low)} — {_fmt_price(high)}",
        "session": _session_label(quote),
        "year_range": f"{_fmt_price(year_low)} — {_fmt_price(year_high)}" if year_low is not None and year_high is not None else "n/a",
    }


async def _render_with_header(original_render, *args, **kwargs) -> io.BytesIO:
    df = args[0] if args else kwargs.get("df")
    symbol = str(args[1] if len(args) > 1 else kwargs.get("symbol", "")).upper()
    timeframe = str(args[2] if len(args) > 2 else kwargs.get("timeframe", ""))
    quote = kwargs.get("quote")

    rendered = await original_render(*args, **kwargs)
    rendered.seek(0)
    base = Image.open(rendered).convert("RGB")

    if not isinstance(df, pd.DataFrame) or df.empty:
        return rendered

    values = _metadata_values(df, symbol, timeframe, quote)

    width, height = base.size
    # Reserve a dedicated header band so the metadata never collides with the
    # chart title or selector below it.
    pad_top = max(225, int(height * 0.22))
    canvas = Image.new("RGB", (width, height + pad_top), "#202124")
    canvas.paste(base, (0, pad_top))
    draw = ImageDraw.Draw(canvas)

    muted = "#b2b8c0"
    bright = "#f0f2f5"
    divider = "#34373b"

    x0 = int(width * 0.035)
    x1 = int(width * 0.385)
    x2 = int(width * 0.690)

    y1 = int(pad_top * 0.07)
    y2 = int(pad_top * 0.30)
    y3 = int(pad_top * 0.51)
    y4 = int(pad_top * 0.72)

    heading = _font(max(38, int(width / 38)), bold=False)
    label = _font(max(31, int(width / 47)), bold=True)
    value = _font(max(35, int(width / 42)), bold=True)

    # 1. Context row.
    draw.text(
        (x0, y1),
        f"{values['asset']}  •  {values['interval']} INTERVALS  •  UTC TIMEZONE",
        font=heading,
        fill=muted,
    )

    # 2. OHLC row. Keep each field independent so long prices cannot collide.
    draw.text((x0, y2), "OPEN", font=label, fill=bright)
    draw.text((x0 + int(width * 0.125), y2), values["open"], font=value, fill=bright)

    draw.text((x1, y2), "HIGH", font=label, fill=bright)
    draw.text((x1 + int(width * 0.125), y2), values["high"], font=value, fill=bright)

    draw.text((x2, y2), "LOW", font=label, fill=bright)
    draw.text((x2 + int(width * 0.075), y2), values["low"], font=value, fill=bright)

    # 3. Previous close / day range row.
    draw.text((x0, y3), "PREV CLOSE", font=label, fill=bright)
    draw.text((x0 + int(width * 0.175), y3), values["previous"], font=value, fill=bright)

    draw.text((x1, y3), "DAY RANGE", font=label, fill=bright)
    draw.text((x1 + int(width * 0.155), y3), values["day_range"], font=value, fill=bright)

    # 4. Session / 52-week range row.
    draw.text((x0, y4), "SESSION", font=label, fill=bright)
    draw.text((x0 + int(width * 0.125), y4), values["session"], font=value, fill=bright)

    draw.text((x1, y4), "52W", font=label, fill=bright)
    draw.text((x1 + int(width * 0.060), y4), values["year_range"], font=value, fill=bright)

    divider_y = int(pad_top * 0.93)
    draw.line(
        (x0, divider_y, int(width * 0.93), divider_y),
        fill=divider,
        width=max(1, int(width / 1800)),
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=False, compress_level=1)
    output.seek(0)
    return output


def install() -> None:
    from app import charts

    if getattr(charts, "_chart_header_details_installed", False):
        return
    original_render = charts.render_google_finance_chart

    async def render_with_header(*args, **kwargs):
        return await _render_with_header(original_render, *args, **kwargs)

    charts.render_google_finance_chart = render_with_header
    charts._chart_header_details_installed = True

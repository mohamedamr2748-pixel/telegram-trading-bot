from __future__ import annotations

import io
from typing import Any

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except OSError:
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


def _fmt_volume(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    absolute = abs(number)
    if absolute >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{number / 1_000:.0f}K"
    return f"{number:.0f}"


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


def _metadata_lines(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    quote: Any = None,
) -> tuple[str, str, str, str]:
    work = frame.copy()
    work.index = pd.to_datetime(work.index, utc=True)
    work = work.sort_index()

    opening = work["Open"].iloc[0] if "Open" in work.columns and not work.empty else None
    high = work["High"].max() if "High" in work.columns and not work.empty else None
    low = work["Low"].min() if "Low" in work.columns and not work.empty else None
    volume = work["Volume"].sum() if "Volume" in work.columns and not work.empty else None

    previous = getattr(quote, "previous_close", None)
    year_high = getattr(quote, "year_high", None)
    year_low = getattr(quote, "year_low", None)
    interval = timeframe.split("/", 1)[1] if "/" in timeframe else timeframe
    asset = _asset_label(symbol.upper(), quote)
    session = _session_label(quote)

    line_one = f"{asset}  •  {interval.upper()} INTERVALS  •  UTC TIMEZONE"
    line_two = (
        f"OPEN  {_fmt_price(opening)}     "
        f"HIGH  {_fmt_price(high)}     "
        f"LOW  {_fmt_price(low)}     "
        f"VOLUME  {_fmt_volume(volume)}"
    )
    line_three = (
        f"PREV CLOSE  {_fmt_price(previous)}     "
        f"DAY RANGE  {_fmt_price(low)} — {_fmt_price(high)}"
    )
    line_four = f"SESSION  {session}"
    if year_high is not None and year_low is not None:
        line_four += f"     52W  {_fmt_price(year_low)} — {_fmt_price(year_high)}"
    return line_one, line_two, line_three, line_four


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

    line_one, line_two, line_three, line_four = _metadata_lines(df, symbol, timeframe, quote)

    width, height = base.size
    # More vertical room plus a much larger fixed font keeps the metadata
    # readable after Telegram scales the image on a phone.
    pad_top = max(230, int(height * 0.225))
    canvas = Image.new("RGB", (width, height + pad_top), "#202124")
    canvas.paste(base, (0, pad_top))
    draw = ImageDraw.Draw(canvas)

    muted = "#b2b8c0"
    bright = "#f0f2f5"
    divider = "#34373b"

    x = int(width * 0.035)
    meta_size = max(48, int(width / 32))
    small = _font(meta_size, bold=False)
    values = _font(meta_size, bold=True)
    value_size = max(50, int(width / 30))
    values_large = _font(value_size, bold=True)

    y_one = int(pad_top * 0.07)
    y_two = int(pad_top * 0.34)
    y_three = int(pad_top * 0.57)
    y_four = int(pad_top * 0.78)

    draw.text((x, y_one), line_one, font=small, fill=muted)
    draw.text((x, y_two), line_two, font=values_large, fill=bright)
    draw.text((x, y_three), line_three, font=values, fill=bright)
    draw.text((x, y_four), line_four, font=values, fill=bright)

    divider_y = int(pad_top * 0.97)
    draw.line(
        (x, divider_y, int(width * 0.93), divider_y),
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

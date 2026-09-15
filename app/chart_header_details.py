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


def _fmt_price(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:,.2f}"


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


def _metadata_line(frame: pd.DataFrame, symbol: str, timeframe: str, quote: Any = None) -> tuple[str, str]:
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    opening = frame["Open"].iloc[0] if "Open" in frame.columns and not frame.empty else None
    high = frame["High"].max() if "High" in frame.columns and not frame.empty else None
    low = frame["Low"].min() if "Low" in frame.columns and not frame.empty else None
    volume = frame["Volume"].sum() if "Volume" in frame.columns and not frame.empty else None

    interval = timeframe.split("/", 1)[1] if "/" in timeframe else timeframe
    asset = _asset_label(symbol.upper(), quote)
    line_one = f"{asset}   •   {interval.upper()} INTERVALS   •   UTC TIMEZONE"
    line_two = (
        f"OPEN {_fmt_price(opening)}    "
        f"HIGH {_fmt_price(high)}    "
        f"LOW {_fmt_price(low)}    "
        f"VOLUME {_fmt_volume(volume)}"
    )
    return line_one, line_two


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

    line_one, line_two = _metadata_line(df, symbol, timeframe, quote)

    width, height = base.size
    pad_top = max(46, int(height * 0.055))
    canvas = Image.new("RGB", (width, height + pad_top), "#202124")
    canvas.paste(base, (0, pad_top))
    draw = ImageDraw.Draw(canvas)

    muted = "#9aa0a6"
    bright = "#d7dbe2"
    divider = "#34373b"
    small = _font(max(15, int(width / 150)), bold=False)
    values = _font(max(15, int(width / 155)), bold=True)

    x = int(width * 0.035)
    y_one = int(pad_top * 0.18)
    y_two = int(pad_top * 0.53)
    draw.text((x, y_one), line_one, font=small, fill=muted)
    draw.text((x, y_two), line_two, font=values, fill=bright)
    divider_y = int(pad_top * 0.96)
    draw.line((x, divider_y, int(width * 0.93), divider_y), fill=divider, width=max(1, int(width / 1800)))

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

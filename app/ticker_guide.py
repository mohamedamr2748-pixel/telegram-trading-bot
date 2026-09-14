from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from app.crypto_pair_enrichment import install as install_crypto_pair_enrichment

# Install pair support when this module is imported by main.py. The bot's
# MarketService instances already exist by then, but the provider methods are
# class methods, so the behaviour is updated for those instances too.
install_crypto_pair_enrichment()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a portable Pillow font without assuming OS font paths."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def ticker_format_image() -> BytesIO:
    image = Image.new("RGB", (1200, 780), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(42)
    heading_font = _font(30)
    body_font = _font(27)
    code_font = _font(30)

    draw.text((70, 55), "Ticker Format Guide", font=title_font, fill="black")
    draw.text(
        (70, 130),
        "Enter the ticker in the correct format.",
        font=body_font,
        fill="black",
    )
    draw.text((70, 210), "Examples", font=heading_font, fill="black")

    examples = [
        ("AAPL", "Apple"),
        ("NVDA", "NVIDIA"),
        ("BTC-USD", "Bitcoin"),
        ("USD-BTC", "Bitcoin (inverse)"),
        ("ETH-USD", "Ethereum"),
        ("GC=F", "Gold Futures"),
        ("EURUSD=X", "EUR / USD"),
    ]
    y = 270
    for ticker, label in examples:
        draw.rounded_rectangle((70, y - 8, 1130, y + 48), radius=10, outline="black", width=2)
        draw.text((95, y), ticker, font=code_font, fill="black")
        draw.text((430, y + 3), label, font=body_font, fill="black")
        y += 65

    draw.text(
        (70, 735),
        "If your ticker is not recognised, check the format and try again.",
        font=body_font,
        fill="black",
    )
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output

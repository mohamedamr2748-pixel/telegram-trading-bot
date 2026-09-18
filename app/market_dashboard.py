from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape

import pandas as pd
from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message

from app.chart_display_symbols import chart_display_symbol, normalise_market_symbol
from app.charts import render_chart
from app.market import MarketService
from app.movers import Mover, get_top_movers

SYMBOLS = ["^GSPC", "^NDX", "^DJI", "BTC-USD", "GC=F"]
LABELS = {"^GSPC": "S&P 500", "^NDX": "NASDAQ-100", "^DJI": "Dow Jones", "BTC-USD": "Bitcoin", "GC=F": "Gold"}
PRICE_DIGITS = {symbol: 2 for symbol in SYMBOLS}

# Price controls are candle intervals. The visible data window is chosen so each
# interval has enough observations for a useful 120-candle chart.
logger = logging.getLogger(__name__)

PRICE_TIMEFRAMES: dict[str, tuple[str, str, str | None]] = {
    "1M": ("1d", "1m", None),
    "5M": ("5d", "5m", None),
    "15M": ("1mo", "15m", None),
    "30M": ("1mo", "30m", None),
    "1H": ("6mo", "1h", None),
    "4H": ("6mo", "4h", None),
    "1D": ("1y", "1d", None),
    "1W": ("5y", "1wk", None),
    "1MO": ("max", "1mo", None),
}

def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"

def _badge(value: float | None) -> str:
    if value is None: return "n/a"
    if value > 0: return f"🟢 {_pct(value)}"
    if value < 0: return f"🔴 {_pct(value)}"
    return "0.00%"

def _price(symbol: str, value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.{PRICE_DIGITS.get(symbol, 2)}f}"

def _session_label(status: str | None) -> str:
    value = (status or "").upper().replace("_", " ")
    if "PRE" in value: return "🟡 Pre-market"
    if "POST" in value or "AFTER" in value: return "🟠 After-hours"
    if "REGULAR" in value or value == "OPEN": return "🟢 Open"
    if "CLOSED" in value: return "🔴 Closed"
    return "Unknown"

def _market_tone(quotes: list[object]) -> str:
    moves = [float(q.change_percent) for q in quotes if hasattr(q, "change_percent") and q.change_percent is not None]
    if not moves: return "🟡 Mixed"
    positives, negatives = sum(v > 0 for v in moves), sum(v < 0 for v in moves)
    if positives > negatives: return "🟢 Positive"
    if negatives > positives: return "🔴 Negative"
    return "🟡 Mixed"

def _mover_line(mover: Mover, positive: bool) -> str:
    return f"<code>{escape(mover.symbol)}</code>  <b>{_pct(mover.percent_change)}</b>"

def _market_keyboard(gainers: tuple[Mover, ...], losers: tuple[Mover, ...]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📈 S&P 500", callback_data="marketv2:chart:^GSPC"), InlineKeyboardButton(text="📈 NASDAQ-100", callback_data="marketv2:chart:^NDX")],
        [InlineKeyboardButton(text="📉 Dow Jones", callback_data="marketv2:chart:^DJI"), InlineKeyboardButton(text="₿ Bitcoin", callback_data="marketv2:chart:BTC-USD")],
        [InlineKeyboardButton(text="🥇 Gold", callback_data="marketv2:chart:GC=F"), InlineKeyboardButton(text="🔥 Top Movers", callback_data="marketv2:movers")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="marketv2:refresh")],
    ]
    movers = [*gainers, *losers][:6]
    for start in range(0, len(movers), 2): rows.append([InlineKeyboardButton(text=row.symbol[:10], callback_data=f"marketv2:chart:{row.symbol}") for row in movers[start:start + 2]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _snapshot(market: MarketService) -> tuple[str, InlineKeyboardMarkup]:
    quotes = await asyncio.gather(*(market.get_quote(symbol) for symbol in SYMBOLS), return_exceptions=True)
    gainers, losers = await get_top_movers()
    valid_quotes = [q for q in quotes if not isinstance(q, Exception)]
    us_status = _session_label(getattr(quotes[0], "market_status", None) if not isinstance(quotes[0], Exception) else None)
    lines = ["🌍 <b>MARKET OVERVIEW</b>", "━━━━━━━━━━━━━━━━", "", "🇺🇸 <b>US MARKETS</b>", ""]
    for symbol, quote in zip(SYMBOLS[:3], quotes[:3]):
        if isinstance(quote, Exception): lines.append(f"<b>{LABELS[symbol]}</b>  <code>n/a</code>  unavailable")
        else: lines.append(f"<b>{LABELS[symbol]}</b>  <code>{_price(symbol, quote.price)}</code>  {_badge(quote.change_percent)}")
    lines.extend(["", f"US Market: {us_status}", "", "🪙 <b>CRYPTO</b>", ""])
    btc = quotes[3]
    if isinstance(btc, Exception): lines.append("<b>Bitcoin</b>  <code>n/a</code>  unavailable")
    else: lines.append(f"<b>Bitcoin</b>  <code>{_price('BTC-USD', btc.price)}</code>  {_badge(btc.change_percent)}")
    lines.extend(["", "🥇 <b>COMMODITIES</b>", ""])
    gold = quotes[4]
    if isinstance(gold, Exception): lines.append("<b>Gold</b>  <code>n/a</code>  unavailable")
    else: lines.append(f"<b>Gold</b>  <code>{_price('GC=F', gold.price)}</code>  {_badge(gold.change_percent)}")
    lines.extend(["", "━━━━━━━━━━━━━━━━", "", "🔥 <b>TOP MOVERS</b>", ""])
    if gainers: lines.extend(["<b>GAINERS</b>", *[_mover_line(row, True) for row in gainers]])
    else: lines.append("Gainers unavailable right now.")
    lines.append("")
    if losers: lines.extend(["<b>LOSERS</b>", *[_mover_line(row, False) for row in losers]])
    else: lines.append("Losers unavailable right now.")
    updated = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines.extend(["", "━━━━━━━━━━━━━━━━", f"📊 Market tone: <b>{_market_tone(valid_quotes)}</b>", f"🕐 Updated: <code>{updated}</code>"])
    return "\n".join(lines), _market_keyboard(gainers, losers)

async def market_cmd(message: Message) -> None:
    text, keyboard = await _snapshot(MarketService()); await message.answer(text, reply_markup=keyboard)

async def _market_chart(callback: CallbackQuery, symbol: str) -> None:
    # Market tickers open the same full /price card used elsewhere in the bot,
    # with the default 4H timeframe and the same chart, caption, and controls.
    await _send_price_card(callback, symbol, "4H", edit=False, limit_key="chart")

def _normalise_price_symbol(symbol: str) -> str:
    raw = chart_display_symbol(symbol)
    if raw.endswith("-USD"): return f"{raw[:-4]}/USD"
    if len(raw) == 6 and raw.isalpha(): return f"{raw[:3]}/{raw[3:]}"
    return raw

def _format_price_value(value: float | None, quote: object | None) -> str:
    if value is None: return "n/a"
    asset = str(getattr(quote, "asset_class", "")).lower() if quote is not None else ""
    if asset == "forex": decimals = 3 if "JPY" in _normalise_price_symbol(str(getattr(quote, "symbol", ""))) else 5
    elif abs(float(value)) < 1: decimals = 6
    else: decimals = 2
    return f"{float(value):,.{decimals}f}"

def _format_volume(value: float | None) -> str:
    if value is None: return "n/a"
    number, magnitude = float(value), abs(float(value))
    if magnitude >= 1_000_000_000_000: return f"{number / 1_000_000_000_000:.2f}T"
    if magnitude >= 1_000_000_000: return f"{number / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000: return f"{number / 1_000_000:.2f}M"
    if magnitude >= 1_000: return f"{number / 1_000:.2f}K"
    return f"{number:,.0f}"

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty: return df
    work = df.copy(); work.index = pd.to_datetime(work.index, utc=True, errors="coerce"); work = work[work.index.notna()].sort_index()
    agg = {}
    for col, fn in (("Open", "first"), ("High", "max"), ("Low", "min"), ("Close", "last"), ("Volume", "sum")):
        if col in work.columns: agg[col] = fn
    if "Close" not in agg: raise ValueError("No Close column available for price chart")
    return work.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["Close"])

async def _get_price_history(symbol: str, timeframe: str) -> pd.DataFrame:
    preset = PRICE_TIMEFRAMES.get(timeframe)
    if preset is None: raise ValueError(f"Unsupported timeframe: {timeframe}")
    period, interval, resample_rule = preset
    df = await MarketService().get_history(symbol, period=period, interval=interval)
    if resample_rule: df = _resample_ohlcv(df, resample_rule)
    return df.tail(120).copy()

async def _caption_volume_4h(symbol: str, df: pd.DataFrame) -> float | None:
    """Recover 4H volume for the caption only, without changing chart data.

    Some stock 4H history responses can contain zero volume even though the
    underlying 1H bars have real traded volume. We keep the existing 4H OHLCV
    frame untouched for rendering and use an isolated 1H request only when the
    displayed 4H volume is entirely zero.
    """
    if "Volume" in df.columns:
        existing = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
        if float(existing.sum()) > 0:
            return float(existing.sum())
    try:
        hourly = await MarketService().get_history(symbol, period="1mo", interval="1h")
    except Exception:
        return float(pd.to_numeric(df["Volume"], errors="coerce").fillna(0).sum()) if "Volume" in df.columns else None
    if "Volume" not in hourly.columns:
        return None
    hourly = hourly.copy()
    hourly.index = pd.to_datetime(hourly.index, utc=True, errors="coerce")
    hourly = hourly[hourly.index.notna()].sort_index()
    hourly_volume = pd.to_numeric(hourly["Volume"], errors="coerce").fillna(0)
    grouped = hourly_volume.groupby(hourly.index.floor("4h")).sum()
    candle_times = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True, errors="coerce"))
    candle_times = candle_times[candle_times.notna()]
    if len(candle_times) == 0:
        return None
    matched = grouped.reindex(candle_times).fillna(0)
    total = float(matched.sum())
    return total if total > 0 else float(hourly_volume.sum()) if float(hourly_volume.sum()) > 0 else None

def _price_caption(symbol: str, timeframe: str, df: pd.DataFrame, quote: object, volume_override: float | None = None) -> tuple[str, str]:
    display_symbol = _normalise_price_symbol(symbol); work = df.copy(); close = pd.to_numeric(work["Close"], errors="coerce").dropna()
    last = float(close.iloc[-1]) if not close.empty else float(getattr(quote, "price")); first = float(close.iloc[0]) if not close.empty else last
    change = ((last / first) - 1.0) * 100.0 if first else None
    high = float(pd.to_numeric(work["High"], errors="coerce").max()) if "High" in work else last; low = float(pd.to_numeric(work["Low"], errors="coerce").min()) if "Low" in work else last
    volume = volume_override if volume_override is not None else (float(pd.to_numeric(work["Volume"], errors="coerce").sum()) if "Volume" in work else None); candle_count = len(work)
    info = f"{display_symbol:<12} | {timeframe:<3} | {candle_count} candles\nLast: ${_format_price_value(last, quote)} ({_pct(change)})\nHigh: ${_format_price_value(high, quote)}\nLow: ${_format_price_value(low, quote)}\nVol: {_format_volume(volume)}\nSource: {getattr(quote, 'source', 'unknown')}"
    return f"<pre>{escape(info)}</pre>", _format_price_value(float(getattr(quote, "price")), quote)

def _price_keyboard(symbol: str, timeframe: str, copy_price: str) -> InlineKeyboardMarkup:
    tf_rows = []
    for group in (("1M", "5M", "15M", "30M", "1H"), ("4H", "1D", "1W", "1MO")):
        row = []
        for item in group:
            kwargs = {"callback_data": f"priceui:t:{item}:{symbol}"}
            if item == timeframe: kwargs["style"] = "primary"
            row.append(InlineKeyboardButton(text=item if item != timeframe else f"• {item} •", **kwargs))
        tf_rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=[*tf_rows, [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"priceui:r:{timeframe}:{symbol}", style="success"), InlineKeyboardButton(text="📋 Copy price", copy_text=CopyTextButton(text=copy_price))]])

async def _send_price_card(
    target: Message | CallbackQuery,
    symbol: str,
    timeframe: str,
    *,
    edit: bool = False,
    limit_key: str = "price",
) -> bool:
    from app.bot import limit_for_user, ticker_format_image
    symbol = normalise_market_symbol(symbol)
    user = target.from_user
    if not await limit_for_user(user.id, user.username, limit_key):
        message = target.message if isinstance(target, CallbackQuery) else target
        limit_text = "10/day" if limit_key == "chart" else "50/day"
        await message.answer(f"⚠️ Free plan limit reached: <b>{limit_text}</b>."); return False
    try:
        market = MarketService(); quote = await market.get_quote(symbol); df = await _get_price_history(symbol, timeframe)
        if df.empty: raise ValueError("No chart data returned")
        display_symbol = chart_display_symbol(symbol)
        image = await render_chart(df, display_symbol, f"{timeframe}/chart", prev_close=getattr(quote, "previous_close", None), price=getattr(quote, "price", None), quote=quote)
        volume_override = await _caption_volume_4h(symbol, df) if timeframe.upper() == "4H" else None
        caption, copy_price = _price_caption(symbol, timeframe, df, quote, volume_override=volume_override); keyboard = _price_keyboard(symbol, timeframe, copy_price); media = BufferedInputFile(image.getvalue(), filename=f"{symbol.replace('/', '_')}.png")
        if edit and isinstance(target, CallbackQuery):
            try:
                await target.message.edit_media(media=InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"), reply_markup=keyboard)
            except TelegramBadRequest as exc:
                # Refreshing an unchanged chart can legitimately return Telegram's
                # "message is not modified". Treat that as a successful no-op so
                # users do not get a false error.
                if "message is not modified" in str(exc).lower():
                    return True
                logger.exception("Telegram failed to update %s %s chart", symbol, timeframe)
                raise
        else:
            message = target.message if isinstance(target, CallbackQuery) else target
            await message.answer_photo(media, caption=caption, reply_markup=keyboard)
        return True
    except ValueError:
        message = target.message if isinstance(target, CallbackQuery) else target; guide = ticker_format_image(); await message.answer_photo(BufferedInputFile(guide.getvalue(), filename="ticker-format-guide.png"), caption=f"❌ <b>Invalid ticker</b>\n\nWe couldn't find price/chart data for <code>{symbol}</code>.\n\nPlease check the ticker format and try again."); return False
    except Exception:
        message = target.message if isinstance(target, CallbackQuery) else target; await message.answer(f"⚠️ We couldn't generate the <b>{timeframe}</b> price chart for <b>{symbol}</b> right now. Please try again later."); return False

async def price_cmd(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2: await message.answer("Usage: <code>/price AAPL</code>"); return
    await _send_price_card(message, parts[1].strip().upper(), "4H")

async def _price_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""; parts = data.split(":", 3)
    if len(parts) != 4: await callback.answer(); return
    _, action, timeframe, symbol = parts; timeframe = timeframe.upper()
    if timeframe not in PRICE_TIMEFRAMES: await callback.answer("Unsupported timeframe", show_alert=True); return
    if action not in {"t", "r"}: await callback.answer(); return
    ok = await _send_price_card(callback, symbol, timeframe, edit=True); await callback.answer("Updated" if ok else "Could not update this chart", show_alert=not ok)

async def _market_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""; action = data.split(":", 2)
    if len(action) < 2: await callback.answer(); return
    kind = action[1]
    if kind == "refresh":
        text, keyboard = await _snapshot(MarketService())
        try: await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception: pass
        await callback.answer("Market refreshed"); return
    if kind == "movers":
        gainers, losers = await get_top_movers(); lines = ["🔥 <b>TOP MOVERS</b>", ""]
        if gainers: lines.extend(["<b>GAINERS</b>", *[_mover_line(row, True) for row in gainers]])
        else: lines.append("Gainers unavailable right now.")
        lines.append("")
        if losers: lines.extend(["<b>LOSERS</b>", *[_mover_line(row, False) for row in losers]])
        else: lines.append("Losers unavailable right now.")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Market Overview", callback_data="marketv2:refresh")]])
        try: await callback.message.edit_text("\n".join(lines), reply_markup=keyboard)
        except Exception: pass
        await callback.answer(); return
    if kind == "chart" and len(action) == 3:
        await _market_chart(callback, action[2]); await callback.answer(); return
    await callback.answer()

def install(bot_module) -> None:
    if getattr(bot_module.router, "_market_dashboard_installed", False): return
    for handler in bot_module.router.message.handlers:
        name = getattr(handler.callback, "__name__", "")
        if name == "market_cmd": handler.callback = market_cmd
        elif name == "price": handler.callback = price_cmd
    bot_module.router.callback_query.register(_price_callback, F.data.startswith("priceui:")); bot_module.router.callback_query.register(_market_callback, F.data.startswith("marketv2:")); bot_module.router._market_dashboard_installed = True

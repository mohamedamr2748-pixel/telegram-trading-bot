from __future__ import annotations

import asyncio
from html import escape
from datetime import datetime, timezone

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.market import MarketService
from app.movers import Mover, get_top_movers


SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "BTC-USD", "GC=F"]
LABELS = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "BTC-USD": "Bitcoin",
    "GC=F": "Gold",
}
PRICE_DIGITS = {
    "^GSPC": 2,
    "^IXIC": 2,
    "^DJI": 2,
    "BTC-USD": 2,
    "GC=F": 2,
}


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _badge(value: float | None) -> str:
    if value is None:
        return "⚪ n/a"
    if value > 0:
        return f"🟢 {_pct(value)}"
    if value < 0:
        return f"🔴 {_pct(value)}"
    return "⚪ 0.00%"


def _price(symbol: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{PRICE_DIGITS.get(symbol, 2)}f}"


def _session_label(status: str | None) -> str:
    value = (status or "").upper().replace("_", " ")
    if "PRE" in value:
        return "🟡 Pre-market"
    if "POST" in value or "AFTER" in value:
        return "🟠 After-hours"
    if "REGULAR" in value or value == "OPEN":
        return "🟢 Open"
    if "CLOSED" in value:
        return "🔴 Closed"
    return "⚪ Unknown"


def _market_tone(quotes: list[object]) -> tuple[str, str]:
    moves = [float(q.change_percent) for q in quotes if hasattr(q, "change_percent") and q.change_percent is not None]
    if not moves:
        return "🟡 Mixed", "Mixed"
    positives = sum(value > 0 for value in moves)
    negatives = sum(value < 0 for value in moves)
    if positives > negatives:
        return "🟢 Positive", "Positive"
    if negatives > positives:
        return "🔴 Negative", "Negative"
    return "🟡 Mixed", "Mixed"


def _mover_line(mover: Mover, positive: bool) -> str:
    icon = "🚀" if positive else "🔻"
    return f"{icon} <code>{escape(mover.symbol)}</code>  <b>{_pct(mover.percent_change)}</b>"


def _market_keyboard(gainers: tuple[Mover, ...], losers: tuple[Mover, ...]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📈 S&P 500", callback_data="marketv2:chart:^GSPC"), InlineKeyboardButton(text="📈 NASDAQ", callback_data="marketv2:chart:^IXIC")],
        [InlineKeyboardButton(text="📉 Dow Jones", callback_data="marketv2:chart:^DJI"), InlineKeyboardButton(text="₿ Bitcoin", callback_data="marketv2:chart:BTC-USD")],
        [InlineKeyboardButton(text="🥇 Gold", callback_data="marketv2:chart:GC=F"), InlineKeyboardButton(text="🔥 Top Movers", callback_data="marketv2:movers")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="marketv2:refresh")],
    ]
    movers = [*gainers, *losers]
    mover_buttons: list[InlineKeyboardButton] = []
    for mover in movers[:6]:
        mover_buttons.append(InlineKeyboardButton(text=mover.symbol[:10], callback_data=f"marketv2:chart:{mover.symbol}"))
    if mover_buttons:
        rows.append(mover_buttons[:2])
        if len(mover_buttons) > 2:
            rows.append(mover_buttons[2:4])
        if len(mover_buttons) > 4:
            rows.append(mover_buttons[4:6])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _snapshot(market: MarketService) -> tuple[str, InlineKeyboardMarkup]:
    quotes = await asyncio.gather(*(market.get_quote(symbol) for symbol in SYMBOLS), return_exceptions=True)
    gainers, losers = await get_top_movers()

    valid_quotes = [q for q in quotes if not isinstance(q, Exception)]
    us_status = _session_label(getattr(quotes[0], "market_status", None) if not isinstance(quotes[0], Exception) else None)
    tone, _ = _market_tone(valid_quotes)

    lines = [
        "🌍 <b>MARKET OVERVIEW</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "🇺🇸 <b>US MARKETS</b>",
        "",
    ]

    for symbol in SYMBOLS[:3]:
        quote = quotes[SYMBOLS.index(symbol)]
        if isinstance(quote, Exception):
            lines.append(f"<b>{LABELS[symbol]}</b>  <code>n/a</code>  ⚪ unavailable")
        else:
            lines.append(f"<b>{LABELS[symbol]}</b>  <code>{_price(symbol, quote.price)}</code>  {_badge(quote.change_percent)}")

    lines.extend(["", f"US Market: {us_status}", "", "🪙 <b>CRYPTO</b>", ""])
    btc = quotes[3]
    if isinstance(btc, Exception):
        lines.append("<b>Bitcoin</b>  <code>n/a</code>  ⚪ unavailable")
    else:
        lines.append(f"<b>Bitcoin</b>  <code>{_price('BTC-USD', btc.price)}</code>  {_badge(btc.change_percent)}")

    lines.extend(["", "🥇 <b>COMMODITIES</b>", ""])
    gold = quotes[4]
    if isinstance(gold, Exception):
        lines.append("<b>Gold</b>  <code>n/a</code>  ⚪ unavailable")
    else:
        lines.append(f"<b>Gold</b>  <code>{_price('GC=F', gold.price)}</code>  {_badge(gold.change_percent)}")

    lines.extend(["", "━━━━━━━━━━━━━━━━", "", "🔥 <b>TOP MOVERS</b>", ""])
    if gainers:
        lines.append("<b>🚀 GAINERS</b>")
        lines.extend(_mover_line(row, True) for row in gainers)
    else:
        lines.append("🚀 Gainers unavailable right now.")
    lines.append("")
    if losers:
        lines.append("<b>🔻 LOSERS</b>")
        lines.extend(_mover_line(row, False) for row in losers)
    else:
        lines.append("🔻 Losers unavailable right now.")

    updated = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines.extend(["", "━━━━━━━━━━━━━━━━", f"📊 Market tone: <b>{tone}</b>", f"🕐 Updated: <code>{updated}</code>"])
    return "\n".join(lines), _market_keyboard(gainers, losers)


async def market_cmd(message: Message) -> None:
    text, keyboard = await _snapshot(MarketService())
    await message.answer(text, reply_markup=keyboard)


async def _market_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    action = data.split(":", 2)
    if len(action) < 2:
        await callback.answer()
        return
    kind = action[1]
    if kind == "refresh":
        text, keyboard = await _snapshot(MarketService())
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            pass
        await callback.answer("Market refreshed")
        return
    if kind == "movers":
        gainers, losers = await get_top_movers()
        lines = ["🔥 <b>TOP MOVERS</b>", ""]
        if gainers:
            lines.append("<b>🚀 GAINERS</b>")
            lines.extend(_mover_line(row, True) for row in gainers)
        else:
            lines.append("🚀 Gainers unavailable right now.")
        lines.append("")
        if losers:
            lines.append("<b>🔻 LOSERS</b>")
            lines.extend(_mover_line(row, False) for row in losers)
        else:
            lines.append("🔻 Losers unavailable right now.")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Market Overview", callback_data="marketv2:refresh")]])
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=keyboard)
        except Exception:
            pass
        await callback.answer()
        return
    if kind == "chart" and len(action) == 3:
        symbol = action[2]
        from app.bot import chart_callback
        callback.data = f"chart:{symbol}"
        await chart_callback(callback)
        return
    await callback.answer()


def install(bot_module) -> None:
    """Replace the legacy /market handler while preserving the existing router."""
    if getattr(bot_module.router, "_market_dashboard_installed", False):
        return
    for handler in bot_module.router.message.handlers:
        if getattr(handler.callback, "__name__", "") == "market_cmd":
            handler.callback = market_cmd
            break
    bot_module.router.callback_query.register(_market_callback, F.data.startswith("marketv2:"))
    bot_module.router._market_dashboard_installed = True

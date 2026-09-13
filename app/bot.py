from __future__ import annotations

import asyncio

import pandas as pd
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.alerts import create_price_alert, create_smart_alert, list_alerts, remove_alert
from app.charts import render_chart
from app.db import Alert, Watchlist, WatchlistItem, consume_usage, get_or_create_user, session_factory
from app.domain import MarketQuote
from app.indicators import add_basic_indicators
from app.market import MarketService
from app.news import NewsService
from config import settings

router = Router()
market = MarketService()
news = NewsService()

LIMITS = {
    "price": 50,
    "chart": 10,
    "news": 30,
    "scanner": 5,
    "brief": 1,
    "why": 3,
    "advanced": 3,
}


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Market", callback_data="menu:market"), InlineKeyboardButton(text="⭐ Watchlist", callback_data="menu:watchlist")],
            [InlineKeyboardButton(text="📰 News", callback_data="menu:news"), InlineKeyboardButton(text="🔔 Alerts", callback_data="menu:alerts")],
            [InlineKeyboardButton(text="🔎 Scanner", callback_data="menu:scanner"), InlineKeyboardButton(text="🌅 Brief", callback_data="menu:brief")],
            [InlineKeyboardButton(text="👤 Account", callback_data="menu:account")],
        ]
    )


def asset_actions(symbol: str) -> InlineKeyboardMarkup:
    symbol = symbol.upper()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Chart", callback_data=f"chart:{symbol}"), InlineKeyboardButton(text="📰 News", callback_data=f"news:{symbol}")],
            [InlineKeyboardButton(text="⭐ Add", callback_data=f"add:{symbol}"), InlineKeyboardButton(text="🧠 Smart alert", callback_data=f"smart:{symbol}")],
        ]
    )


def _move_badge(change_percent: float | None) -> str:
    if change_percent is None:
        return "⚪ n/a"
    if change_percent > 0:
        return f"🟢 +{change_percent:.2f}%"
    if change_percent < 0:
        return f"🔴 {change_percent:.2f}%"
    return "⚪ 0.00%"


def _market_label(symbol: str) -> str:
    return {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI": "Dow Jones",
        "BTC-USD": "Bitcoin",
        "GC=F": "Gold",
    }.get(symbol, symbol)


def fmt_quote(q: MarketQuote) -> str:
    move = _move_badge(q.change_percent)
    status = "STALE" if q.is_stale else (q.market_status or "LIVE").upper()
    return (
        f"<b>📌 {q.symbol}</b>\n\n"
        f"💰 <b>{q.price:.6g}</b>   {move}\n\n"
        f"<b>Session</b>\n"
        f"├ Open   <code>{q.open if q.open is not None else 'n/a'}</code>\n"
        f"├ High   <code>{q.high if q.high is not None else 'n/a'}</code>\n"
        f"├ Low    <code>{q.low if q.low is not None else 'n/a'}</code>\n"
        f"└ Volume <code>{q.volume:,.0f}</code>\n\n"
        f"🕒 <code>{q.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</code>\n"
        f"📡 {q.source} • {status}"
    )


async def limit_for_user(user_id: int, username: str | None, key: str) -> bool:
    async with session_factory() as session:
        user = await get_or_create_user(session, user_id, username)
        if user.plan != "free":
            return True
        ok, _ = await consume_usage(session, user.id, key, LIMITS[key])
    return ok


async def limit_or_message(message: Message, key: str) -> bool:
    ok = await limit_for_user(message.from_user.id, message.from_user.username, key)
    if not ok:
        await message.answer(f"⚠️ Free plan limit reached: <b>{LIMITS[key]}/day</b> for {key}.")
    return ok


@router.message(Command("start"))
async def start(message: Message) -> None:
    async with session_factory() as session:
        await get_or_create_user(session, message.from_user.id, message.from_user.username)
    await message.answer(
        "<b>Tickaro — Trading Intelligence</b>\n\n"
        "Your market command centre inside Telegram.\n\n"
        "<b>Track</b> prices • charts • news • alerts\n"
        "<b>Discover</b> moves • scanners • market brief\n\n"
        "Choose an action:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "<b>📚 Tickaro Commands</b>\n\n"
        "<b>Market</b>\n"
        "/price SYMBOL — live quote\n"
        "/market — market overview\n"
        "/brief — daily market brief\n\n"
        "<b>Analysis</b>\n"
        "/chart SYMBOL [PERIOD] [advanced]\n"
        "/why SYMBOL — move context\n"
        "/scanner [MODE] — market scanner\n\n"
        "<b>News & Watchlist</b>\n"
        "/news SYMBOL\n"
        "/watchlist\n"
        "/add SYMBOL\n"
        "/remove SYMBOL\n\n"
        "<b>Alerts</b>\n"
        "/alerts\n"
        "/alert SYMBOL CONDITION VALUE\n"
        "/alert SYMBOL smart\n"
        "/remove_alert ID\n\n"
        "<b>Account</b>\n"
        "/account\n\n"
        "<b>Examples</b>\n"
        "<code>/price AAPL</code>\n"
        "<code>/chart NVDA 3mo</code>\n"
        "<code>/chart NVDA 3mo advanced</code>\n"
        "<code>/alert NVDA above 200</code>\n"
        "<code>/alert BTCUSD pct_down 5</code>\n"
        "<code>/alert NVDA smart</code>"
    )


@router.message(Command("account"))
async def account(message: Message) -> None:
    from datetime import date
    from app.db import Usage

    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watch_count = await session.scalar(select(func.count(WatchlistItem.id)).join(Watchlist).where(Watchlist.user_id == user.id)) or 0
        alerts = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "price")) or 0
        smart = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "smart")) or 0
        usage_result = await session.execute(
            select(Usage.key, Usage.count).where(
                Usage.user_id == user.id,
                Usage.day == date.today(),
            )
        )
        usage = dict(usage_result.all())
        await message.answer(
            "👤 <b>MY ACCOUNT</b>\n\n"
            "<b>PLAN</b>\n"
            f"🆓 {user.plan.title()}\n\n"
            "<b>PORTFOLIO</b>\n"
            f"⭐ Watchlist       <b>{watch_count} / 10</b>\n"
            f"🔔 Price alerts   <b>{alerts} / 3</b>\n"
            f"🧠 Smart alerts   <b>{smart} / 3</b>\n\n"
            "<b>SETTINGS</b>\n"
            f"🌍 Timezone        <code>{user.timezone}</code>\n\n"
            "<b>USAGE • TODAY</b>\n"
            f"💰 Price           <code>{usage.get('price', 0)} / 50</code>\n"
            f"📈 Charts          <code>{usage.get('chart', 0)} / 10</code>\n"
            f"📰 News            <code>{usage.get('news', 0)} / 30</code>\n"
            f"🔎 Scanner         <code>{usage.get('scanner', 0)} / 5</code>\n"
            f"🌅 Brief           <code>{usage.get('brief', 0)} / 1</code>\n"
            f"🔍 Why             <code>{usage.get('why', 0)} / 3</code>\n"
            f"📊 Advanced        <code>{usage.get('advanced', 0)} / 3</code>"
        )


@router.message(Command("price"))
async def price(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: <code>/price AAPL</code>")
        return
    symbol = parts[1].strip().upper()
    if not await limit_or_message(message, "price"):
        return
    try:
        quote = await market.get_quote(symbol)
    except Exception:
        await message.answer(f"❌ Could not fetch market data for <b>{symbol}</b> right now.")
        return
    await message.answer(fmt_quote(quote), reply_markup=asset_actions(symbol))


@router.message(Command("chart"))
async def chart(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) < 2 or len(parts) > 4:
        await message.answer("Usage: <code>/chart AAPL [1d|5d|1mo|3mo|6mo|1y] [advanced]</code>")
        return
    symbol = parts[1].upper()
    period = parts[2] if len(parts) >= 3 and parts[2].lower() != "advanced" else "1mo"
    advanced = any(p.lower() == "advanced" for p in parts[2:])
    allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y"}
    if period not in allowed_periods:
        await message.answer("Unsupported period. Use: 1d, 5d, 1mo, 3mo, 6mo, 1y")
        return
    if advanced and not await limit_or_message(message, "advanced"):
        return
    if not await limit_or_message(message, "chart"):
        return
    interval = "15m" if period in {"1d", "5d"} else "1d"
    try:
        df = await market.get_history(symbol, period=period, interval=interval)
        image = await render_chart(df, symbol, f"{period}/{interval}", advanced=advanced)
        caption = f"📈 <b>{symbol}</b> • {period}/{interval}" + (" • advanced" if advanced else "")
        await message.answer_photo(BufferedInputFile(image.getvalue(), filename=f"{symbol}.png"), caption=caption)
    except Exception:
        await message.answer(f"❌ Could not generate a chart for <b>{symbol}</b> right now.")


@router.message(Command("news"))
async def news_cmd(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: <code>/news AAPL</code>")
        return
    symbol = parts[1].strip().upper()
    if not await limit_or_message(message, "news"):
        return
    items = await news.search(symbol, 8)
    if not items:
        await message.answer(f"📰 No recent news found for <b>{symbol}</b>.")
        return
    body = [f"📰 <b>Latest News — {symbol}</b>", ""]
    for idx, item in enumerate(items, 1):
        body.append(f"<b>{idx}.</b> <a href=\"{item.url}\">{item.title}</a>\n<i>{item.source}</i>\n")
    await message.answer("\n".join(body), disable_web_page_preview=True)


@router.message(Command("why"))
async def why_cmd(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: <code>/why AAPL</code>")
        return
    symbol = parts[1].strip().upper()
    if not await limit_or_message(message, "why"):
        return
    try:
        quote = await market.get_quote(symbol)
        items = await news.search(symbol, 5)
    except Exception:
        await message.answer(f"❌ Could not analyse <b>{symbol}</b> right now.")
        return
    direction = "up" if (quote.change_percent or 0) > 0 else "down" if (quote.change_percent or 0) < 0 else "flat"
    move = f"{quote.change_percent:+.2f}%" if quote.change_percent is not None else "n/a"
    body = [f"🔎 <b>Why {symbol} moved</b>", f"Today: <b>{move}</b> ({direction})", ""]
    if items:
        body.append("<b>Relevant recent headlines</b>")
        body.extend([f"• {item.title}" for item in items[:3]])
    body.append("\n<i>Context summary — not causal certainty.</i>")
    await message.answer("\n".join(body))


async def get_watchlist(session, user_id: int) -> list[WatchlistItem]:
    result = await session.execute(select(WatchlistItem).join(Watchlist).where(Watchlist.user_id == user_id).order_by(WatchlistItem.id))
    return list(result.scalars().all())


@router.message(Command("watchlist"))
async def watchlist(message: Message) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        items = await get_watchlist(session, user.id)
    if not items:
        await message.answer("⭐ <b>Your Watchlist</b>\n\nYour watchlist is empty.\nUse <code>/add AAPL</code> to add a ticker.")
        return
    quotes = await asyncio.gather(*(market.get_quote(i.symbol) for i in items), return_exceptions=True)
    lines = ["⭐ <b>My Watchlist</b>", ""]
    for item, quote in zip(items, quotes):
        if isinstance(quote, Exception):
            lines.append(f"🔴 <b>{item.symbol}</b> — unavailable")
        else:
            lines.append(f"{'🟢' if (quote.change_percent or 0) >= 0 else '🔴'} <b>{item.symbol}</b>  <code>{quote.price:.6g}</code>  {_move_badge(quote.change_percent)}")
    await message.answer("\n".join(lines))


@router.message(Command("add"))
async def add(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: <code>/add AAPL</code>")
        return
    symbol = parts[1].strip().upper()
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watchlist = (await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))).scalar_one()
        count = await session.scalar(select(func.count(WatchlistItem.id)).where(WatchlistItem.watchlist_id == watchlist.id)) or 0
        if count >= 10 and user.plan == "free":
            await message.answer("⚠️ Free plan limit: <b>10 tickers</b> in your watchlist.")
            return
        existing = await session.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.symbol == symbol))
        if existing:
            await message.answer(f"ℹ️ <b>{symbol}</b> is already in your watchlist.")
            return
        try:
            quote = await market.get_quote(symbol)
        except Exception:
            await message.answer(f"❌ I can't validate <b>{symbol}</b> right now.")
            return
        session.add(WatchlistItem(watchlist_id=watchlist.id, symbol=symbol, asset_class=quote.asset_class))
        await session.commit()
    await message.answer(f"✅ <b>{symbol}</b> added to your watchlist.")


@router.message(Command("remove"))
async def remove(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: <code>/remove AAPL</code>")
        return
    symbol = parts[1].strip().upper()
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        result = await session.execute(select(WatchlistItem).join(Watchlist).where(Watchlist.user_id == user.id, WatchlistItem.symbol == symbol))
        item = result.scalar_one_or_none()
        if not item:
            await message.answer(f"ℹ️ <b>{symbol}</b> is not in your watchlist.")
            return
        await session.delete(item)
        await session.commit()
    await message.answer(f"✅ <b>{symbol}</b> removed from your watchlist.")


@router.message(Command("alerts"))
async def alerts(message: Message) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        rows = await list_alerts(session, user.id)
    if not rows:
        await message.answer("🔔 <b>Your Alerts</b>\n\nNo alerts yet.\nExample: <code>/alert NVDA above 200</code>")
        return
    lines = ["🔔 <b>Your Alerts</b>", ""]
    for row in rows:
        state = "🟢 Active" if row.active else "🔴 Inactive"
        detail = "🧠 Smart • unusual move" if row.alert_type == "smart" else f"{row.condition} {row.threshold}"
        lines.append(f"<b>#{row.id} {row.symbol}</b> • {detail}\n{state}\n")
    await message.answer("\n".join(lines))


@router.message(Command("alert"))
async def alert(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) == 3 and parts[2].lower() == "smart":
        symbol = parts[1].upper()
        async with session_factory() as session:
            user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
            try:
                row = await create_smart_alert(session, user, symbol)
            except ValueError as exc:
                await message.answer(str(exc))
                return
        await message.answer(f"🧠 <b>Smart alert #{row.id}</b> enabled for <b>{symbol}</b>.")
        return
    if len(parts) != 4:
        await message.answer("Usage: <code>/alert AAPL above 250</code>\nConditions: above, below, pct_up, pct_down\nSmart: <code>/alert NVDA smart</code>")
        return
    symbol, condition, raw = parts[1].upper(), parts[2].lower(), parts[3]
    try:
        threshold = float(raw)
    except ValueError:
        await message.answer("❌ Threshold must be numeric.")
        return
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        try:
            row = await create_price_alert(session, user, symbol, condition, threshold)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    await message.answer(f"✅ <b>Alert #{row.id}</b> created\n{symbol} • {condition} • {threshold:g}")


@router.message(Command("remove_alert"))
async def remove_alert_cmd(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/remove_alert 12</code>")
        return
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        ok = await remove_alert(session, user.id, int(parts[1]))
    await message.answer("✅ Alert removed." if ok else "❌ Alert not found.")


async def scan_symbols(kind: str) -> list[str]:
    async def one(symbol: str):
        try:
            df = await market.get_history(symbol, period="1mo", interval="1d")
            if len(df) < 5:
                return None
            close = df["Close"].astype(float)
            pct = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
            avg_vol = float(df["Volume"].tail(20).mean()) if "Volume" in df else 0.0
            vol = float(df["Volume"].iloc[-1]) if "Volume" in df else 0.0
            ind = add_basic_indicators(df)
            rsi_value = ind["RSI14"].iloc[-1]
            rsi = float(rsi_value) if pd.notna(rsi_value) else 50.0
            volume_ratio = vol / avg_vol if avg_vol else 0.0
            if kind == "gainers":
                score = pct
            elif kind == "losers":
                score = -pct
            elif kind == "volume":
                score = volume_ratio
            elif kind == "overbought":
                score = rsi if rsi > 70 else -999
            elif kind == "oversold":
                score = -rsi if rsi < 30 else -999
            else:
                score = pct
            return symbol, score, pct, volume_ratio, rsi
        except Exception:
            return None

    rows = [r for r in await asyncio.gather(*(one(s) for s in settings.scanner_symbols)) if r]
    rows.sort(key=lambda x: x[1], reverse=True)
    return [f"{s} • {pct:+.2f}% • vol {vr:.1f}× • RSI {rsi:.0f}" for s, _, pct, vr, rsi in rows[:10]]


@router.message(Command("scanner"))
async def scanner(message: Message) -> None:
    if not await limit_or_message(message, "scanner"):
        return
    parts = message.text.split(maxsplit=1) if message.text else []
    raw_kind = parts[1].lower() if len(parts) == 2 else "gainers"
    mapping = {
        "top_gainers": "gainers",
        "gainers": "gainers",
        "top_losers": "losers",
        "losers": "losers",
        "volume_spike": "volume",
        "volume": "volume",
        "overbought": "overbought",
        "oversold": "oversold",
    }
    kind = mapping.get(raw_kind, "gainers")
    rows = await scan_symbols(kind)
    titles = {
        "gainers": "🚀 Top Gainers",
        "losers": "📉 Top Losers",
        "volume": "🔥 Volume Spikes",
        "overbought": "⚠️ Overbought",
        "oversold": "🟢 Oversold",
    }
    await message.answer("🔎 <b>Scanner</b>\n" + titles[kind] + "\n\n" + ("\n".join(rows) if rows else "No results."))


@router.message(Command("market"))
async def market_cmd(message: Message) -> None:
    symbols = ["^GSPC", "^IXIC", "^DJI", "BTC-USD", "GC=F"]
    quotes = await asyncio.gather(*(market.get_quote(s) for s in symbols), return_exceptions=True)
    lines = ["🌍 <b>Market Overview</b>", ""]
    for symbol, quote in zip(symbols, quotes):
        label = _market_label(symbol)
        if isinstance(quote, Exception):
            lines.append(f"<b>{label}</b>\n   unavailable\n")
            continue
        pct = _move_badge(quote.change_percent)
        lines.append(f"<b>{label}</b>\n   <code>{quote.price:.6g}</code>  {pct}\n")
    lines.append("<i>Live snapshot • data sources may vary by asset</i>")
    await message.answer("\n".join(lines))


@router.message(Command("brief"))
async def brief(message: Message) -> None:
    if not await limit_or_message(message, "brief"):
        return
    symbols = ["^GSPC", "^IXIC", "BTC-USD", "GC=F"]
    quotes = await asyncio.gather(*(market.get_quote(s) for s in symbols), return_exceptions=True)
    news_items = await news.search("market", 5)
    lines = ["🌅 <b>Daily Market Brief</b>", ""]
    for symbol, quote in zip(symbols, quotes):
        if not isinstance(quote, Exception):
            lines.append(f"{_market_label(symbol)}  <code>{quote.price:.6g}</code>  {_move_badge(quote.change_percent)}")
    if news_items:
        lines.append("\n📰 <b>Top headlines</b>")
        lines.extend([f"• {x.title}" for x in news_items[:3]])
    lines.append("\n<i>Snapshot for orientation, not investment advice.</i>")
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("chart:"))
async def chart_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    if not await _callback_limit(callback, "chart"):
        return
    try:
        df = await market.get_history(symbol, "1mo", "1d")
        image = await render_chart(df, symbol, "1mo/1d")
        await callback.message.answer_photo(BufferedInputFile(image.getvalue(), filename=f"{symbol}.png"), caption=f"📈 <b>{symbol}</b> • 1mo/1d")
    except Exception:
        await callback.message.answer(f"❌ Could not generate a chart for <b>{symbol}</b>.")
    await callback.answer()


async def _callback_limit(callback: CallbackQuery, key: str) -> bool:
    ok = await limit_for_user(callback.from_user.id, callback.from_user.username, key)
    if not ok:
        await callback.message.answer(f"⚠️ Free plan limit reached: <b>{LIMITS[key]}/day</b>.")
    return ok


@router.callback_query(F.data.startswith("news:"))
async def news_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    if not await _callback_limit(callback, "news"):
        return
    items = await news.search(symbol, 6)
    if not items:
        await callback.message.answer(f"📰 No recent news found for <b>{symbol}</b>.")
    else:
        body = [f"📰 <b>News — {symbol}</b>", ""]
        body.extend([f"• <a href=\"{x.url}\">{x.title}</a>\n<i>{x.source}</i>\n" for x in items])
        await callback.message.answer("\n".join(body), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("add:"))
async def add_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        watchlist = (await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))).scalar_one()
        count = await session.scalar(select(func.count(WatchlistItem.id)).where(WatchlistItem.watchlist_id == watchlist.id)) or 0
        if count >= 10 and user.plan == "free":
            await callback.message.answer("⚠️ Free plan limit: <b>10 tickers</b>.")
            await callback.answer()
            return
        existing = await session.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.symbol == symbol))
        if not existing:
            try:
                quote = await market.get_quote(symbol)
            except Exception:
                await callback.message.answer(f"❌ I can't validate <b>{symbol}</b> right now.")
                await callback.answer()
                return
            session.add(WatchlistItem(watchlist_id=watchlist.id, symbol=symbol, asset_class=quote.asset_class))
            await session.commit()
            msg = f"✅ <b>{symbol}</b> added to your watchlist."
        else:
            msg = f"ℹ️ <b>{symbol}</b> is already in your watchlist."
    await callback.message.answer(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("smart:"))
async def smart_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        try:
            row = await create_smart_alert(session, user, symbol)
            msg = f"🧠 <b>Smart alert #{row.id}</b> enabled for <b>{symbol}</b>."
        except ValueError as exc:
            msg = str(exc)
    await callback.message.answer(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery) -> None:
    target = callback.data.split(":", 1)[1]
    prompts = {
        "market": "📊 Use <code>/market</code> for a live overview.",
        "watchlist": "⭐ Use <code>/watchlist</code>, <code>/add SYMBOL</code> and <code>/remove SYMBOL</code>.",
        "news": "📰 Use <code>/news SYMBOL</code>.",
        "alerts": "🔔 Use <code>/alerts</code> or <code>/alert SYMBOL above 200</code>.",
        "scanner": "🔎 Use <code>/scanner</code>, <code>/scanner volume_spike</code> or another scanner mode.",
        "brief": "🌅 Use <code>/brief</code> for the daily summary.",
        "account": "👤 Use <code>/account</code> to see your plan and usage.",
    }
    await callback.message.answer(prompts.get(target, "Use <code>/help</code> to see available commands."))
    await callback.answer()


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp

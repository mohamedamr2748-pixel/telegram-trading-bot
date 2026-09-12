from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.alerts import create_price_alert, create_smart_alert, list_alerts, remove_alert
from app.charts import render_chart
from app.db import Alert, NewsItem, NewsAsset, Watchlist, WatchlistItem, consume_usage, get_or_create_user, session_factory
from app.domain import MarketQuote
from app.indicators import add_advanced_indicators, add_basic_indicators
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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Market", callback_data="menu:market"), InlineKeyboardButton(text="⭐ Watchlist", callback_data="menu:watchlist")],
        [InlineKeyboardButton(text="📰 News", callback_data="menu:news"), InlineKeyboardButton(text="🔔 Alerts", callback_data="menu:alerts")],
        [InlineKeyboardButton(text="🔎 Scanner", callback_data="menu:scanner"), InlineKeyboardButton(text="🌅 Brief", callback_data="menu:brief")],
        [InlineKeyboardButton(text="👤 Account", callback_data="menu:account")],
    ])


def asset_actions(symbol: str) -> InlineKeyboardMarkup:
    symbol = symbol.upper()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Chart", callback_data=f"chart:{symbol}"), InlineKeyboardButton(text="📰 News", callback_data=f"news:{symbol}")],
        [InlineKeyboardButton(text="⭐ Add", callback_data=f"add:{symbol}"), InlineKeyboardButton(text="🔔 Alert", callback_data=f"smart:{symbol}")],
    ])


def fmt_quote(q: MarketQuote) -> str:
    change = f"{q.change:+.4f}" if q.change is not None else "n/a"
    pct = f"{q.change_percent:+.2f}%" if q.change_percent is not None else "n/a"
    status = q.market_status
    if q.is_stale and status == "open":
        status = "stale"
    return (
        f"<b>{q.symbol}</b>\n"
        f"Price: <b>{q.price:.6g}</b>\n"
        f"Change: {change} ({pct})\n"
        f"Open: {q.open if q.open is not None else 'n/a'}\n"
        f"High: {q.high if q.high is not None else 'n/a'}\n"
        f"Low: {q.low if q.low is not None else 'n/a'}\n"
        f"Volume: {q.volume:,.0f}\n\n"
        f"🕒 {q.timestamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"📡 {q.source} • {status}"
    )


async def ensure_user(message: Message):
    async with session_factory() as session:
        return await get_or_create_user(session, message.from_user.id, message.from_user.username)


async def limit_or_message(message: Message, key: str) -> bool:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        if user.plan != "free":
            return True
        ok, used = await consume_usage(session, user.id, key, LIMITS[key])
    if not ok:
        await message.answer(f"Free plan limit reached for {key}: {LIMITS[key]}/day.")
    return ok


@router.message(Command("start"))
async def start(message: Message) -> None:
    await ensure_user(message)
    await message.answer(
        "<b>Trading Intelligence Bot</b>\n\n"
        "Watch the market, get relevant news, build charts and set alerts — inside Telegram.\n\n"
        "Choose an action:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "<b>Commands</b>\n\n"
        "/price SYMBOL\n/chart SYMBOL\n/news SYMBOL\n/why SYMBOL\n"
        "/watchlist\n/add SYMBOL\n/remove SYMBOL\n"
        "/alerts\n/alert SYMBOL CONDITION VALUE\n/remove_alert ID\n"
        "/market\n/brief\n/scanner\n/account\n\n"
        "Examples:\n"
        "/price AAPL\n"
        "/alert NVDA above 200\n"
        "/alert BTCUSD pct_down 5\n"
        "/alert NVDA smart"
    )


@router.message(Command("account"))
async def account(message: Message) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watch_count = await session.scalar(select(func.count(WatchlistItem.id)).join(Watchlist).where(Watchlist.user_id == user.id)) or 0
        alerts = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "price")) or 0
        smart = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "smart")) or 0
        lines = [
            "👤 <b>My Account</b>",
            f"Plan: <b>{user.plan.title()}</b>",
            f"Watchlists: 1 / 1",
            f"Tickers: {watch_count} / 10",
            f"Active alerts: {alerts} / 3",
            f"Smart alerts: {smart} / 3",
            f"Timezone: {user.timezone}",
            "",
            "Daily limits: Price 50 • Charts 10 • News 30 • Scanner 5 • Brief 1 • Why 3 • Advanced indicators 3",
        ]
    await message.answer("\n".join(lines))


@router.message(Command("price"))
async def price(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: /price AAPL")
        return
    if not await limit_or_message(message, "price"):
        return
    symbol = parts[1].strip().upper()
    try:
        quote = await market.get_quote(symbol)
    except Exception as exc:
        await message.answer(f"Could not fetch {symbol}: {exc}")
        return
    await message.answer(fmt_quote(quote), reply_markup=asset_actions(symbol))


@router.message(Command("chart"))
async def chart(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) < 2:
        await message.answer("Usage: /chart AAPL [timeframe]\nTimeframes: 1d, 5d, 1mo, 3mo, 6mo, 1y")
        return
    if not await limit_or_message(message, "chart"):
        return
    symbol = parts[1].upper()
    period = parts[2] if len(parts) > 2 else "1mo"
    interval = "1d"
    if period in {"1d", "5d"}:
        interval = "15m"
    try:
        df = await market.get_history(symbol, period=period, interval=interval)
        image = await render_chart(df, symbol, f"{period}/{interval}")
        await message.answer_photo(BufferedInputFile(image.getvalue(), filename=f"{symbol}.png"), caption=f"{symbol} • {period} • {interval}")
    except Exception as exc:
        await message.answer(f"Could not generate chart: {exc}")


@router.message(Command("news"))
async def news_cmd(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: /news AAPL")
        return
    if not await limit_or_message(message, "news"):
        return
    symbol = parts[1].strip().upper()
    items = await news.search(symbol, 8)
    if not items:
        await message.answer(f"No recent news found for {symbol}.")
        return
    body = [f"📰 <b>Latest news — {symbol}</b>"]
    for idx, item in enumerate(items, 1):
        body.append(f"\n{idx}. <a href=\"{item.url}\">{item.title}</a>\n   {item.source}")
    await message.answer("\n".join(body), disable_web_page_preview=True)


@router.message(Command("why"))
async def why_cmd(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: /why AAPL")
        return
    if not await limit_or_message(message, "why"):
        return
    symbol = parts[1].strip().upper()
    try:
        quote = await market.get_quote(symbol)
        items = await news.search(symbol, 5)
    except Exception as exc:
        await message.answer(f"Could not analyse {symbol}: {exc}")
        return
    direction = "up" if (quote.change_percent or 0) > 0 else "down" if (quote.change_percent or 0) < 0 else "flat"
    body = [f"🔎 <b>Why {symbol} moved</b>", f"Price is {direction} {quote.change_percent:+.2f}% today." if quote.change_percent is not None else "Price change unavailable."]
    if items:
        body.append("\n<b>Relevant recent headlines:</b>")
        body.extend([f"• {item.title}" for item in items[:3]])
    body.append("\nThis is a context summary, not a causal certainty.")
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
        await message.answer("⭐ Your watchlist is empty. Use /add AAPL")
        return
    quotes = await asyncio.gather(*(market.get_quote(i.symbol) for i in items), return_exceptions=True)
    lines = ["⭐ <b>My Watchlist</b>"]
    for item, quote in zip(items, quotes):
        if isinstance(quote, Exception):
            lines.append(f"{item.symbol} — unavailable")
        else:
            pct = f"{quote.change_percent:+.2f}%" if quote.change_percent is not None else "n/a"
            lines.append(f"{item.symbol} — {quote.price:.6g} ({pct})")
    await message.answer("\n".join(lines))


@router.message(Command("add"))
async def add(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: /add AAPL")
        return
    symbol = parts[1].strip().upper()
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watchlist = (await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))).scalar_one()
        count = await session.scalar(select(func.count(WatchlistItem.id)).where(WatchlistItem.watchlist_id == watchlist.id)) or 0
        if count >= 10 and user.plan == "free":
            await message.answer("Free plan limit reached: 10 tickers in your watchlist.")
            return
        existing = await session.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.symbol == symbol))
        if existing:
            await message.answer(f"{symbol} is already in your watchlist.")
            return
        try:
            quote = await market.get_quote(symbol)
        except Exception as exc:
            await message.answer(f"I can't validate {symbol}: {exc}")
            return
        session.add(WatchlistItem(watchlist_id=watchlist.id, symbol=symbol, asset_class=quote.asset_class))
        await session.commit()
    await message.answer(f"✅ Added {symbol} to your watchlist.")


@router.message(Command("remove"))
async def remove(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) != 2:
        await message.answer("Usage: /remove AAPL")
        return
    symbol = parts[1].strip().upper()
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        result = await session.execute(select(WatchlistItem).join(Watchlist).where(Watchlist.user_id == user.id, WatchlistItem.symbol == symbol))
        item = result.scalar_one_or_none()
        if not item:
            await message.answer(f"{symbol} is not in your watchlist.")
            return
        await session.delete(item)
        await session.commit()
    await message.answer(f"✅ Removed {symbol}.")


@router.message(Command("alerts"))
async def alerts(message: Message) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        rows = await list_alerts(session, user.id)
    if not rows:
        await message.answer("🔔 No alerts yet. Example: /alert NVDA above 200")
        return
    lines = ["🔔 <b>Your Alerts</b>"]
    for row in rows:
        state = "🟢 Active" if row.active else "🔴 Inactive"
        if row.alert_type == "smart":
            detail = "smart • unusual move"
        else:
            detail = f"{row.condition} {row.threshold}"
        lines.append(f"#{row.id} {row.symbol} • {detail} • {state}")
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
        await message.answer(f"🧠 Smart alert #{row.id} enabled for {symbol}.")
        return
    if len(parts) != 4:
        await message.answer("Usage: /alert AAPL above 250\nConditions: above, below, pct_up, pct_down\nSmart: /alert NVDA smart")
        return
    symbol, condition, raw = parts[1].upper(), parts[2].lower(), parts[3]
    try:
        threshold = float(raw)
    except ValueError:
        await message.answer("Threshold must be numeric.")
        return
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        try:
            row = await create_price_alert(session, user, symbol, condition, threshold)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    await message.answer(f"✅ Alert #{row.id} created: {symbol} {condition} {threshold:g}")


@router.message(Command("remove_alert"))
async def remove_alert_cmd(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /remove_alert 12")
        return
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        ok = await remove_alert(session, user.id, int(parts[1]))
    await message.answer("✅ Alert removed." if ok else "Alert not found.")


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
            rsi_df = add_basic_indicators(df)
            rsi = float(rsi_df["RSI14"].iloc[-1]) if not pd_is_na(rsi_df["RSI14"].iloc[-1]) else 50.0
            if kind == "gainers": score = pct
            elif kind == "losers": score = -pct
            elif kind == "volume": score = (vol / avg_vol) if avg_vol else 0
            elif kind == "overbought": score = rsi if rsi > 70 else -999
            elif kind == "oversold": score = -rsi if rsi < 30 else -999
            else: score = pct
            return symbol, score, pct, vol / avg_vol if avg_vol else 0, rsi
        except Exception:
            return None
    rows = [r for r in await asyncio.gather(*(one(s) for s in settings.scanner_symbols)) if r]
    rows.sort(key=lambda x: x[1], reverse=True)
    return [f"{s} • {pct:+.2f}% • vol {vr:.1f}× • RSI {rsi:.0f}" for s, _, pct, _, rsi in rows[:10]]


def pd_is_na(value) -> bool:
    try:
        return bool(__import__("pandas").isna(value))
    except Exception:
        return False


@router.message(Command("scanner"))
async def scanner(message: Message) -> None:
    if not await limit_or_message(message, "scanner"):
        return
    parts = message.text.split(maxsplit=1) if message.text else []
    kind = parts[1].lower() if len(parts) == 2 else "gainers"
    mapping = {"top_gainers": "gainers", "gainers": "gainers", "top_losers": "losers", "losers": "losers", "volume_spike": "volume", "volume": "volume", "overbought": "overbought", "oversold": "oversold"}
    kind = mapping.get(kind, "gainers")
    rows = await scan_symbols(kind)
    title = kind.replace("_", " ").title()
    await message.answer("🔎 <b>Scanner • " + title + "</b>\n\n" + ("\n".join(rows) if rows else "No results."))


@router.message(Command("market"))
async def market_cmd(message: Message) -> None:
    symbols = ["^GSPC", "^IXIC", "^DJI", "BTC-USD", "GC=F"]
    quotes = await asyncio.gather(*(market.get_quote(s) for s in symbols), return_exceptions=True)
    lines = ["🌍 <b>Market</b>"]
    for symbol, quote in zip(symbols, quotes):
        if isinstance(quote, Exception):
            lines.append(f"{symbol}: unavailable")
        else:
            pct = f"{quote.change_percent:+.2f}%" if quote.change_percent is not None else "n/a"
            lines.append(f"{symbol}: {quote.price:.6g} ({pct})")
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
            pct = f"{quote.change_percent:+.2f}%" if quote.change_percent is not None else "n/a"
            lines.append(f"{symbol}: {quote.price:.6g} ({pct})")
    if news_items:
        lines.append("\n📰 <b>Top headlines</b>")
        lines.extend([f"• {x.title}" for x in news_items[:3]])
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("chart:"))
async def chart_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    if not await _callback_limit(callback, "chart"):
        return
    try:
        df = await market.get_history(symbol, "1mo", "1d")
        image = await render_chart(df, symbol, "1mo/1d")
        await callback.message.answer_photo(BufferedInputFile(image.getvalue(), filename=f"{symbol}.png"))
    except Exception as exc:
        await callback.message.answer(f"Chart error: {exc}")
    await callback.answer()


async def _callback_limit(callback: CallbackQuery, key: str) -> bool:
    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        ok, _ = await consume_usage(session, user.id, key, LIMITS[key]) if user.plan == "free" else (True, 0)
    if not ok:
        await callback.message.answer(f"Free plan limit reached: {LIMITS[key]}/day.")
    return ok


@router.callback_query(F.data.startswith("news:"))
async def news_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    if not await _callback_limit(callback, "news"):
        return
    items = await news.search(symbol, 6)
    if not items:
        await callback.message.answer(f"No recent news found for {symbol}.")
    else:
        body = [f"📰 <b>News — {symbol}</b>"]
        body.extend([f"• <a href=\"{x.url}\">{x.title}</a>" for x in items])
        await callback.message.answer("\n".join(body), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("add:"))
async def add_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    fake = type("M", (), {"from_user": callback.from_user})
    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        watchlist = (await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))).scalar_one()
        count = await session.scalar(select(func.count(WatchlistItem.id)).where(WatchlistItem.watchlist_id == watchlist.id)) or 0
        if count >= 10 and user.plan == "free":
            await callback.message.answer("Free plan limit reached: 10 tickers.")
            await callback.answer()
            return
        existing = await session.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.symbol == symbol))
        if not existing:
            session.add(WatchlistItem(watchlist_id=watchlist.id, symbol=symbol, asset_class="unknown"))
            await session.commit()
    await callback.message.answer(f"✅ Added {symbol} to your watchlist.")
    await callback.answer()


@router.callback_query(F.data.startswith("smart:"))
async def smart_callback(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":", 1)[1]
    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        try:
            row = await create_smart_alert(session, user, symbol)
            msg = f"🧠 Smart alert #{row.id} enabled for {symbol}."
        except ValueError as exc:
            msg = str(exc)
    await callback.message.answer(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery) -> None:
    target = callback.data.split(":", 1)[1]
    prompts = {
        "market": "Use /market for a live overview.",
        "watchlist": "Use /watchlist, /add SYMBOL and /remove SYMBOL.",
        "news": "Use /news SYMBOL.",
        "alerts": "Use /alerts or /alert SYMBOL above 200.",
        "scanner": "Use /scanner or /scanner volume_spike.",
        "brief": "Use /brief for the daily summary.",
        "account": "Use /account to see your plan and usage.",
    }
    await callback.message.answer(prompts[target])
    await callback.answer()


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp

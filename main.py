from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot
from aiogram.types import BotCommand
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.alerts import evaluate_alerts
from app.cache_cleanup import purge_market_cache
from app.db import init_db, session_factory
from app.market import MarketService
from app.market_enrichment import install_market_enrichment
from app.news_feed import NewsFeedWorker
from app.symbol_aliases import install_symbol_aliases
from config import settings

install_market_enrichment()
install_symbol_aliases()

from app.ticker_guide import ticker_format_image
import app.bot as bot_module
bot_module.ticker_format_image = ticker_format_image

from app.chart_typography import install as install_chart_typography
install_chart_typography()

from app import charts as charts_module
from app.chart_reference_style import configure_observed_bounds
charts_module._configure_us_equity_x_axis = configure_observed_bounds

from app.index_stats import install as install_index_stats
install_index_stats(charts_module)

# Keep provider/canonical symbols internal; charts use friendly index names.
from app.chart_display_symbols import chart_display_symbol
_original_render_chart = bot_module.render_chart


async def _render_chart_with_friendly_symbol(
    df,
    symbol,
    timeframe,
    advanced=False,
    **kwargs,
):
    display_symbol = chart_display_symbol(symbol)
    return await _original_render_chart(
        df,
        display_symbol,
        timeframe,
        advanced=advanced,
        **kwargs,
    )


bot_module.render_chart = _render_chart_with_friendly_symbol

from app.market_dashboard import install as install_market_dashboard
install_market_dashboard(bot_module)

from app.bot import build_dispatcher

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Trading Intelligence Bot", version="0.1.0")
db_ready = False


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "db_ready": db_ready})


async def init_db_with_retry() -> None:
    global db_ready
    delay = 2
    while True:
        try:
            await init_db()
            if settings.purge_market_cache_on_startup:
                await purge_market_cache()
                logger.warning("One-time non-user market/news cache purge completed")
            db_ready = True
            logger.info("Database initialization completed")
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            db_ready = False
            logger.exception("Database initialization failed; retrying in %ss", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def alert_loop(bot: Bot) -> None:
    market = MarketService()
    while True:
        try:
            async with session_factory() as session:
                async def send_message(user_id: int, text: str) -> None:
                    try:
                        await bot.send_message(user_id, text)
                    except Exception:
                        logger.exception("Failed to deliver alert to user %s", user_id)

                await evaluate_alerts(session, market, send_message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Alert worker failed")
        await asyncio.sleep(max(5, settings.alert_poll_seconds))


async def run_news_feed() -> None:
    worker = NewsFeedWorker()
    try:
        await worker.run()
    finally:
        await worker.close()


async def run_health_server() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot() -> None:
    health_server = asyncio.create_task(run_health_server())
    db_task = asyncio.create_task(init_db_with_retry())
    bot: Bot | None = None
    alert_worker: asyncio.Task | None = None
    news_worker: asyncio.Task | None = None
    try:
        if not settings.bot_token.strip():
            raise RuntimeError("BOT_TOKEN is required to start the Telegram bot.")

        bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        await bot.set_my_commands([
            BotCommand(command="start", description="Start Tradely"),
            BotCommand(command="price", description="View a live market price"),
            BotCommand(command="chart", description="View a price chart for any symbol"),
            BotCommand(command="news", description="View the latest market news"),
            BotCommand(command="why", description="Analyse why an asset moved"),
            BotCommand(command="add", description="Add a ticker to your watchlist"),
            BotCommand(command="remove", description="Remove a ticker from your watchlist"),
            BotCommand(command="alert", description="Create a price or smart alert"),
            BotCommand(command="market", description="View the market overview"),
            BotCommand(command="scanner", description="Scan the market"),
            BotCommand(command="brief", description="View the daily market brief"),
            BotCommand(command="watchlist", description="View your watchlist"),
            BotCommand(command="alerts", description="View and manage your alerts"),
            BotCommand(command="premium", description="View Premium and subscription options"),
            BotCommand(command="account", description="View your account and usage"),
            BotCommand(command="help", description="Show help and instructions"),
        ])
        dp = build_dispatcher()

        # Do not start database-dependent workers until initialization succeeds.
        await db_task
        alert_worker = asyncio.create_task(alert_loop(bot))
        news_worker = asyncio.create_task(run_news_feed())
        await dp.start_polling(bot)
    finally:
        for task in (alert_worker, news_worker):
            if task is not None:
                task.cancel()
        if not db_task.done():
            db_task.cancel()
        health_server.cancel()
        tasks = [task for task in (alert_worker, news_worker, db_task, health_server) if task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
        if bot is not None:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())

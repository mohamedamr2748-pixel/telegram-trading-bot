from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.alerts import evaluate_alerts
from app.db import init_db, session_factory
from app.market import MarketService
from app.market_enrichment import install_market_enrichment
from app.symbol_aliases import install_symbol_aliases
from config import settings

# Install market/symbol enrichment before importing app.bot because bot.py
# constructs its MarketService at import time.
install_market_enrichment()
install_symbol_aliases()

# Keep the invalid-ticker guide portable and use the dedicated implementation.
from app.ticker_guide import ticker_format_image
import app.bot as bot_module
bot_module.ticker_format_image = ticker_format_image

# The chart renderer owns UTC display labels, period performance and the
# US-equity session classification. Typography remains orthogonal.
from app.chart_typography import install as install_chart_typography
install_chart_typography()

# Match the reference chart: use the real observation domain for the x-axis
# while retaining centralized US session colouring and no synthetic prices.
from app import charts as charts_module
from app.chart_reference_style import configure_observed_bounds
charts_module._configure_us_equity_x_axis = configure_observed_bounds

# Replace only the legacy /market handler with the upgraded interactive
# dashboard; all other bot handlers remain intact.
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


async def run_health_server() -> None:
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot() -> None:
    health_server = asyncio.create_task(run_health_server())
    db_task = asyncio.create_task(init_db_with_retry())
    bot: Bot | None = None
    worker: asyncio.Task | None = None
    try:
        if not settings.bot_token.strip():
            raise RuntimeError("BOT_TOKEN is required to start the Telegram bot.")

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = build_dispatcher()
        worker = asyncio.create_task(alert_loop(bot))
        await dp.start_polling(bot)
    finally:
        if worker is not None:
            worker.cancel()
        db_task.cancel()
        health_server.cancel()
        tasks = [task for task in (worker, db_task, health_server) if task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
        if bot is not None:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())

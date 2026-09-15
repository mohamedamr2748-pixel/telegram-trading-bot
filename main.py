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
from config import settings

# Install before importing app.bot: bot.py creates its MarketService at import time.
install_market_enrichment()

# Keep the invalid-ticker guide portable and use the dedicated implementation.
from app.ticker_guide import ticker_format_image
import app.bot as bot_module
bot_module.ticker_format_image = ticker_format_image

# Make the timezone explicit on every chart caption without changing any
# non-chart photo captions.
_original_answer_photo = bot_module.Message.answer_photo


async def _chart_answer_photo_with_explicit_utc(self, *args, **kwargs):
    caption = kwargs.get("caption")
    if caption and caption.startswith("📈 ") and " • UTC" in caption:
        kwargs["caption"] = caption.replace(" • UTC", " • UTC Timezone", 1)
    return await _original_answer_photo(self, *args, **kwargs)


bot_module.Message.answer_photo = _chart_answer_photo_with_explicit_utc

# All user-facing chart time labels are UTC. Session classification inside
# app.charts still uses New York time for U.S. market hours.
from app.chart_utc import install as install_chart_utc
install_chart_utc()

# For ranges longer than 1D, colour the chart and headline percentage by the
# selected chart-period return rather than by today's daily move.
from app.chart_period_performance import install as install_chart_period_performance
install_chart_period_performance()

# Use richer Yahoo-style standard charts: OHLC candlesticks plus volume while
# preserving the existing chart captions, selectors and statistics.
from app.chart_enhanced import install as install_chart_enhanced
install_chart_enhanced()

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

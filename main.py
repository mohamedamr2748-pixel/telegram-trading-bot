from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.alerts import evaluate_alerts
from app.bot import build_dispatcher
from app.db import init_db, session_factory
from app.market import MarketService
from app.news import NewsService
from config import settings

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Trading Intelligence Bot", version="0.1.0")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


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


async def run_bot() -> None:
    await init_db()
    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher()
    worker = asyncio.create_task(alert_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        worker.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())

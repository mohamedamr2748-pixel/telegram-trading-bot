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

# Increase chart text sizes for readability while preserving the existing
# Yahoo-style line/area chart design.
from app.chart_typography import install as install_chart_typography
install_chart_typography()

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

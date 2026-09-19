from __future__ import annotations

from datetime import datetime, timezone

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.db import get_or_create_user, session_factory


class LastActivityMiddleware(BaseMiddleware):
    """Persist the UTC timestamp of the user's latest incoming interaction."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user is not None:
            try:
                async with session_factory() as session:
                    db_user = await get_or_create_user(
                        session,
                        user.id,
                        getattr(user, "username", None),
                    )
                    db_user.last_active_at = datetime.now(timezone.utc)
                    await session.commit()
            except Exception:
                # Activity analytics must never prevent a command/button from working.
                pass

        return await handler(event, data)

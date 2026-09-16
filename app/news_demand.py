from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db import NewsDemand, session_factory

INACTIVE_HOURS = 24


def _normalise(symbol: str) -> str:
    return symbol.strip().upper()


class NewsDemandTracker:
    """Stores aggregate ticker demand only; never stores Telegram identity data."""

    async def mark_requested(self, symbol: str) -> None:
        symbol = _normalise(symbol)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            row = await session.get(NewsDemand, symbol)
            if row is None:
                session.add(NewsDemand(symbol=symbol, last_requested_at=now))
            else:
                row.last_requested_at = now
            await session.commit()

    async def mark_fetched(self, symbol: str) -> None:
        symbol = _normalise(symbol)
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            row = await session.get(NewsDemand, symbol)
            if row is not None:
                row.last_fetched_at = now
                await session.commit()

    async def get_last_requested(self, symbol: str) -> datetime | None:
        async with session_factory() as session:
            row = await session.get(NewsDemand, _normalise(symbol))
            return row.last_requested_at if row else None

    async def get_last_fetched(self, symbol: str) -> datetime | None:
        async with session_factory() as session:
            row = await session.get(NewsDemand, _normalise(symbol))
            return row.last_fetched_at if row else None

    async def symbols(self) -> list[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=INACTIVE_HOURS)
        async with session_factory() as session:
            result = await session.scalars(select(NewsDemand.symbol).where(NewsDemand.last_requested_at >= cutoff))
            return [str(symbol).upper() for symbol in result]

    async def prune_inactive(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=INACTIVE_HOURS)
        async with session_factory() as session:
            result = await session.execute(delete(NewsDemand).where(NewsDemand.last_requested_at < cutoff))
            await session.commit()
            return int(result.rowcount or 0)

    async def close(self) -> None:
        return None

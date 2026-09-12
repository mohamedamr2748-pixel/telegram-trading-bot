from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Alert, User
from app.market import MarketService


FREE_ACTIVE_ALERTS = 3
FREE_ACTIVE_SMART_ALERTS = 3


async def active_alert_count(session: AsyncSession, user_id: int, alert_type: str | None = None) -> int:
    stmt = select(Alert).where(Alert.user_id == user_id, Alert.active.is_(True))
    if alert_type:
        stmt = stmt.where(Alert.alert_type == alert_type)
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def create_price_alert(session: AsyncSession, user: User, symbol: str, condition: str, threshold: float) -> Alert:
    count = await active_alert_count(session, user.id, "price")
    if user.plan == "free" and count >= FREE_ACTIVE_ALERTS:
        raise ValueError(f"Free plan limit reached: {FREE_ACTIVE_ALERTS} active alerts.")
    if condition not in {"above", "below", "pct_up", "pct_down"}:
        raise ValueError("Condition must be above, below, pct_up, or pct_down.")
    alert = Alert(user_id=user.id, symbol=symbol.upper(), alert_type="price", condition=condition, threshold=threshold, active=True)
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def create_smart_alert(session: AsyncSession, user: User, symbol: str) -> Alert:
    count = await active_alert_count(session, user.id, "smart")
    if user.plan == "free" and count >= FREE_ACTIVE_SMART_ALERTS:
        raise ValueError(f"Free plan limit reached: {FREE_ACTIVE_SMART_ALERTS} smart alerts.")
    alert = Alert(user_id=user.id, symbol=symbol.upper(), alert_type="smart", condition="unusual_move", active=True)
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def list_alerts(session: AsyncSession, user_id: int) -> list[Alert]:
    result = await session.execute(select(Alert).where(Alert.user_id == user_id).order_by(Alert.id.desc()))
    return list(result.scalars().all())


async def remove_alert(session: AsyncSession, user_id: int, alert_id: int) -> bool:
    result = await session.execute(select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id))
    alert = result.scalar_one_or_none()
    if not alert:
        return False
    alert.active = False
    await session.commit()
    return True


async def evaluate_alerts(session: AsyncSession, market: MarketService, send_message) -> None:
    result = await session.execute(select(Alert).where(Alert.active.is_(True)))
    alerts = list(result.scalars().all())
    by_symbol: dict[str, object] = {}
    for alert in alerts:
        if alert.symbol not in by_symbol:
            try:
                by_symbol[alert.symbol] = await market.get_quote(alert.symbol)
            except Exception:
                continue
        quote = by_symbol[alert.symbol]
        triggered = False
        text = ""
        if alert.alert_type == "price":
            value = quote.price
            if alert.condition == "above" and value >= float(alert.threshold):
                triggered = True
                text = f"Price crossed above {alert.threshold:g}."
            elif alert.condition == "below" and value <= float(alert.threshold):
                triggered = True
                text = f"Price crossed below {alert.threshold:g}."
            elif alert.condition in {"pct_up", "pct_down"} and quote.change_percent is not None:
                pct = float(quote.change_percent)
                if alert.condition == "pct_up" and pct >= float(alert.threshold):
                    triggered = True
                    text = f"Daily move reached +{pct:.2f}%."
                elif alert.condition == "pct_down" and pct <= -abs(float(alert.threshold)):
                    triggered = True
                    text = f"Daily move reached {pct:.2f}%."
        else:
            pct = abs(float(quote.change_percent or 0))
            if pct >= 3:
                triggered = True
                text = f"Unusual move detected: {quote.change_percent:+.2f}% today."
        if triggered:
            now = datetime.now(timezone.utc)
            if alert.last_triggered_at and (now - alert.last_triggered_at).total_seconds() < 3600:
                continue
            alert.last_triggered_at = now
            await session.commit()
            await send_message(alert.user_id, f"🚨 Alert #{alert.id}\n\n{alert.symbol}: {quote.price:.4f}\n{text}\nSource: {quote.source}")

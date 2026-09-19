from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


OWNER_USERNAME = "moegy_1"
OWNER_PLAN = "unlimited"


def _normalise_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="My Watchlist")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    asset_class: Mapped[str] = mapped_column(String(32), default="unknown")
    smart_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    alert_type: Mapped[str] = mapped_column(String(32), default="price")
    condition: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[float | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NewsItem(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255), default="unknown")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    relevance: Mapped[int] = mapped_column(Integer, default=0)
    urgency: Mapped[int] = mapped_column(Integer, default=0)


class NewsAsset(Base):
    __tablename__ = "news_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    __table_args__ = (UniqueConstraint("news_id", "symbol", name="uq_news_asset"),)


class NewsDemand(Base):
    __tablename__ = "news_demand"
    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price: Mapped[float] = mapped_column()
    volume: Mapped[float] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(64))


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "day", "key", name="uq_usage"),)


class PlanLimit(Base):
    __tablename__ = "plan_limits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan: Mapped[str] = mapped_column(String(32), index=True)
    feature_key: Mapped[str] = mapped_column(String(64), index=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persistent_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    __table_args__ = (UniqueConstraint("plan", "feature_key", name="uq_plan_limit_feature"),)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_name: Mapped[str] = mapped_column(String(64), index=True)
    command: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    plan: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(32), default="pro")
    telegram_payment_charge_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_payload: Mapped[str] = mapped_column(String(255), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="XTR")
    amount_stars: Mapped[int] = mapped_column(Integer)
    subscription_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    is_first_recurring: Mapped[bool] = mapped_column(Boolean, default=False)


class BriefReport(Base):
    __tablename__ = "brief_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    report_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


engine = create_async_engine(_normalise_database_url(settings.database_url), pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.execute(text("ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMP WITH TIME ZONE"))
        else:
            result = await conn.execute(text("PRAGMA table_info(users)"))
            columns = {row[1] for row in result.fetchall()}
            if "plan_expires_at" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN plan_expires_at DATETIME"))
    await seed_plan_limits()


PLAN_LIMITS_DEFAULTS = {
    "free": {
        "price": (30, None), "market": (5, None), "chart": (5, None), "news": (5, None),
        "why": (2, None), "scanner": (2, None), "brief": (1, None), "brief_pdf": (2, None),
        "watchlist": (20, None), "add": (10, None), "remove": (10, None), "alerts": (20, None),
        "alert": (3, None), "watchlist_tickers": (None, 10), "price_alerts": (None, 3), "smart_alerts": (None, 3),
    },
    "premium": {
        "price": (150, None), "market": (30, None), "chart": (30, None), "news": (30, None),
        "why": (15, None), "scanner": (12, None), "brief": (5, None), "brief_pdf": (10, None),
        "watchlist": (100, None), "add": (50, None), "remove": (50, None), "alerts": (100, None),
        "alert": (20, None), "watchlist_tickers": (None, 50), "price_alerts": (None, 20), "smart_alerts": (None, 20),
    },
    "unlimited": {
        "price": (None, None), "market": (None, None), "chart": (None, None), "news": (None, None),
        "why": (None, None), "scanner": (None, None), "brief": (None, None), "brief_pdf": (None, None),
        "watchlist": (None, None), "add": (None, None), "remove": (None, None), "alerts": (None, None),
        "alert": (None, None), "watchlist_tickers": (None, None), "price_alerts": (None, None), "smart_alerts": (None, None),
    },
}


def normalise_plan_key(plan: str) -> str:
    return "premium" if plan == "pro" else plan


async def seed_plan_limits() -> None:
    async with session_factory() as session:
        for plan, features in PLAN_LIMITS_DEFAULTS.items():
            for feature_key, (daily_limit, persistent_limit) in features.items():
                row = await session.scalar(
                    select(PlanLimit).where(
                        PlanLimit.plan == plan,
                        PlanLimit.feature_key == feature_key,
                    )
                )
                if row is None:
                    session.add(
                        PlanLimit(
                            plan=plan,
                            feature_key=feature_key,
                            daily_limit=daily_limit,
                            persistent_limit=persistent_limit,
                        )
                    )
        await session.commit()


async def get_plan_limit(plan: str, feature_key: str, persistent: bool = False) -> int | None:
    plan_key = normalise_plan_key(plan)
    async with session_factory() as session:
        row = await session.scalar(
            select(PlanLimit).where(
                PlanLimit.plan == plan_key,
                PlanLimit.feature_key == feature_key,
            )
        )
        if row is not None:
            return row.persistent_limit if persistent else row.daily_limit
    fallback = PLAN_LIMITS_DEFAULTS.get(plan_key, PLAN_LIMITS_DEFAULTS["free"]).get(feature_key)
    return fallback[1 if persistent else 0] if fallback else None


async def get_plan_limits(plan: str) -> dict[str, tuple[int | None, int | None]]:
    plan_key = normalise_plan_key(plan)
    async with session_factory() as session:
        result = await session.execute(
            select(PlanLimit.feature_key, PlanLimit.daily_limit, PlanLimit.persistent_limit)
            .where(PlanLimit.plan == plan_key)
        )
        rows = {key: (daily, persistent) for key, daily, persistent in result.all()}
    return rows or PLAN_LIMITS_DEFAULTS.get(plan_key, PLAN_LIMITS_DEFAULTS["free"]).copy()


async def record_usage_event(
    user_id: int,
    event_name: str,
    *,
    command: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    plan: str | None = None,
    success: bool | None = None,
    latency_ms: float | None = None,
    ai_model: str | None = None,
    metadata: dict | None = None,
) -> None:
    try:
        import json
        async with session_factory() as session:
            session.add(
                UsageEvent(
                    user_id=user_id,
                    event_name=event_name,
                    command=command,
                    source=source,
                    symbol=symbol,
                    plan=normalise_plan_key(plan or "free"),
                    success=success,
                    latency_ms=latency_ms,
                    ai_model=ai_model,
                    metadata_json=json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                )
            )
            await session.commit()
    except Exception:
        return


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    normalized_username = username.strip().lstrip("@").lower() if username else None
    is_owner = normalized_username == OWNER_USERNAME

    if user:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if is_owner and user.plan != OWNER_PLAN:
            user.plan = OWNER_PLAN
            changed = True
        if changed:
            await session.commit()
        return user

    user = User(telegram_id=telegram_id, username=username, plan=OWNER_PLAN if is_owner else "free")
    session.add(user)
    await session.flush()
    session.add(Watchlist(user_id=user.id, name="My Watchlist"))
    await session.commit()
    return user


async def is_owner(session: AsyncSession, telegram_id: int, username: str | None = None) -> bool:
    # Prefer the persisted owner Telegram ID once the owner's account exists.
    owner_row = await session.scalar(
        select(User.telegram_id).where(User.username.ilike(OWNER_USERNAME)).limit(1)
    )
    if owner_row is not None:
        return int(owner_row) == int(telegram_id)

    normalized = username.strip().lstrip("@").lower() if username else ""
    return normalized == OWNER_USERNAME


async def delete_latest_brief_report() -> tuple[bool, datetime | None]:
    async with session_factory() as session:
        row = await session.scalar(
            select(BriefReport).order_by(BriefReport.created_at.desc(), BriefReport.id.desc()).limit(1)
        )
        if row is None:
            return False, None
        created_at = row.created_at
        await session.delete(row)
        await session.commit()
        return True, created_at


async def consume_feature_quota(
    telegram_id: int,
    username: str | None,
    feature_key: str,
    *,
    source: str = "command",
    symbol: str | None = None,
) -> tuple[bool, int, int | None, str, bool]:
    """Consume the daily quota and record the relevant analytics event.

    Returns: (allowed, used, limit, plan_key, limit_warning)
    """
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                plan=OWNER_PLAN if (username or "").strip().lstrip("@").lower() == OWNER_USERNAME else "free",
            )
            session.add(user)
            await session.flush()
            session.add(Watchlist(user_id=user.id, name="My Watchlist"))
            await session.flush()

        if username and user.username != username:
            user.username = username

        if user.plan == UNLIMITED_PLAN:
            plan_key = "unlimited"
        elif user.plan == "pro" and user.plan_expires_at and (
            user.plan_expires_at if user.plan_expires_at.tzinfo else user.plan_expires_at.replace(tzinfo=timezone.utc)
        ) > now:
            plan_key = "premium"
        else:
            plan_key = "free"

        limit_row = await session.scalar(
            select(PlanLimit).where(
                PlanLimit.plan == plan_key,
                PlanLimit.feature_key == feature_key,
            )
        )
        limit = limit_row.daily_limit if limit_row is not None else PLAN_LIMITS_DEFAULTS.get(
            plan_key, PLAN_LIMITS_DEFAULTS["free"]
        ).get(feature_key, (None, None))[0]

        if limit is None:
            used = 0
            allowed = True
            warning = False
        else:
            today = date.today()
            usage_row = await session.scalar(
                select(Usage).where(
                    Usage.user_id == user.id,
                    Usage.day == today,
                    Usage.key == feature_key,
                )
            )
            if usage_row is None:
                usage_row = Usage(user_id=user.id, day=today, key=feature_key, count=0)
                session.add(usage_row)
                await session.flush()

            if usage_row.count >= limit:
                allowed = False
                used = usage_row.count
                warning = False
                session.add(
                    UsageEvent(
                        user_id=user.id,
                        event_name="limit_reached",
                        command=feature_key,
                        source=source,
                        symbol=symbol,
                        plan=plan_key,
                        success=False,
                        metadata_json=f'{{"used":{used},"limit":{limit}}}',
                    )
                )
            else:
                usage_row.count += 1
                used = usage_row.count
                allowed = True
                warning_threshold = max(1, int((limit * 0.8) + 0.999999))
                warning = warning_threshold < limit and used == warning_threshold
                session.add(
                    UsageEvent(
                        user_id=user.id,
                        event_name="feature_used",
                        command=feature_key,
                        source=source,
                        symbol=symbol,
                        plan=plan_key,
                        success=None,
                        metadata_json=f'{{"used":{used},"limit":{limit}}}',
                    )
                )
                if warning:
                    session.add(
                        UsageEvent(
                            user_id=user.id,
                            event_name="limit_warning",
                            command=feature_key,
                            source=source,
                            symbol=symbol,
                            plan=plan_key,
                            success=True,
                            metadata_json=f'{{"used":{used},"limit":{limit}}}',
                        )
                    )

        await session.commit()
        return allowed, used, limit, plan_key, warning


async def consume_usage(session: AsyncSession, user_id: int, key: str, limit: int) -> tuple[bool, int]:
    today = date.today()
    result = await session.execute(select(Usage).where(Usage.user_id == user_id, Usage.day == today, Usage.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        row = Usage(user_id=user_id, day=today, key=key, count=0)
        session.add(row)
        await session.flush()
    if row.count >= limit:
        return False, row.count
    row.count += 1
    await session.commit()
    return True, row.count

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select

from app.db import SubscriptionPayment, User, get_or_create_user, session_factory
from config import settings

SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60
PAYLOAD_PREFIX = "tickaro:pro:"
PRO_PLAN = "pro"
UNLIMITED_PLAN = "unlimited"


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def is_active_paid_plan(user: User) -> bool:
    if user.plan == UNLIMITED_PLAN:
        return True
    if user.plan != PRO_PLAN:
        return False
    expires_at = _aware_utc(user.plan_expires_at)
    return expires_at is not None and expires_at > datetime.now(timezone.utc)


def effective_plan(user: User) -> str:
    if user.plan == UNLIMITED_PLAN:
        return UNLIMITED_PLAN
    return PRO_PLAN if is_active_paid_plan(user) else "free"


def _format_expiry(user: User) -> str:
    expiry = _aware_utc(user.plan_expires_at)
    return expiry.strftime("%d %b %Y, %H:%M UTC") if expiry else "n/a"


def _payload(user_id: int) -> str:
    return f"{PAYLOAD_PREFIX}{user_id}:{uuid4().hex}"


def _parse_payload(payload: str) -> tuple[int, str] | None:
    if not payload.startswith(PAYLOAD_PREFIX):
        return None
    parts = payload.split(":")
    if len(parts) != 4:
        return None
    try:
        return int(parts[2]), parts[3]
    except (TypeError, ValueError):
        return None


def subscribe_keyboard(*, can_buy: bool, payment_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_buy and payment_url:
        rows.append([InlineKeyboardButton(text="⭐ Pay 80 Stars / 30 days", url=payment_url)])
    elif can_buy:
        rows.append([InlineKeyboardButton(text="⭐ Subscribe to Pro", callback_data="subscribe:pro")])
    rows.append([InlineKeyboardButton(text="👤 Account", callback_data="subscribe:account")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _subscribe_screen(user: User) -> tuple[str, InlineKeyboardMarkup]:
    plan = effective_plan(user)
    if plan == UNLIMITED_PLAN:
        return (
            "<b>⭐ Tickaro Pro</b>\n\n"
            "You have owner access with unlimited usage.\n"
            "No subscription is required.",
            subscribe_keyboard(can_buy=False),
        )

    if plan == PRO_PLAN:
        return (
            "<b>⭐ Tickaro Pro</b>\n\n"
            "<b>Status:</b> Active\n"
            f"<b>Expires:</b> {_format_expiry(user)}\n\n"
            "Your Pro access is active for the current subscription period.\n"
            "Automatic renewal is handled by Telegram Stars.",
            subscribe_keyboard(can_buy=False),
        )

    features = [
        "Up to 10 AI market briefs/day",
        "Higher usage limits across trading tools",
        "More watchlist and alert capacity",
        "Premium trading workflows as they are released",
    ]
    body = "<b>⭐ Tickaro Pro</b>\n\n" + "\n".join(f"• {x}" for x in features) + "\n\n"
    if settings.pro_price_stars > 0:
        body += f"<b>Price:</b> {settings.pro_price_stars} ⭐ / 30 days\n"
        body += "Payment is processed securely through Telegram Stars.\n"
        body += "Tap the button below to open Telegram's secure checkout."
        return body, subscribe_keyboard(can_buy=True)

    body += "<b>Payment:</b> Not configured yet.\n"
    body += "Set <code>PRO_PRICE_STARS</code> before enabling checkout."
    return body, subscribe_keyboard(can_buy=False)


async def show_subscribe(message: Message) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    body, keyboard = await _subscribe_screen(user)
    await message.answer(body, reply_markup=keyboard)


async def subscribe_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    action = data.split(":", 1)[1] if ":" in data else ""
    if action == "show":
        async with session_factory() as session:
            user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        body, keyboard = await _subscribe_screen(user)
        await callback.message.answer(body, reply_markup=keyboard)
        await callback.answer()
        return
    if action == "account":
        await callback.message.answer("👤 Use <code>/account</code> to view your current plan and usage.")
        await callback.answer()
        return
    if action != "pro":
        await callback.answer()
        return

    async with session_factory() as session:
        user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)

    if is_active_paid_plan(user):
        await callback.message.answer(
            f"✅ <b>Tickaro Pro is already active</b> until <code>{_format_expiry(user)}</code>."
        )
        await callback.answer()
        return

    price = settings.pro_price_stars
    if price <= 0:
        await callback.message.answer("⚠️ Pro checkout is not configured yet.")
        await callback.answer()
        return

    payload = _payload(user.id)
    invoice_data = {
        "title": settings.pro_plan_name,
        "description": settings.pro_plan_description,
        "payload": payload,
        "currency": "XTR",
        "prices": [LabeledPrice(label="Tickaro Pro — 30 days", amount=price)],
        "subscription_period": SUBSCRIPTION_PERIOD_SECONDS,
    }

    try:
        invoice_link = await callback.bot.create_invoice_link(**invoice_data)
    except Exception:
        await callback.message.answer(
            "⚠️ Telegram could not create the Pro checkout right now. Please try again in a moment."
        )
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ Pay {price} Stars / 30 days", url=invoice_link)],
            [InlineKeyboardButton(text="👤 Account", callback_data="subscribe:account")],
        ]
    )
    await callback.message.answer(
        "<b>⭐ Tickaro Pro Checkout</b>\n\n"
        f"Price: <b>{price} Telegram Stars</b>\n"
        "Billing period: <b>30 days</b>\n\n"
        "Tap the button below to open Telegram's secure checkout.\n"
        "The subscription renews automatically each month unless cancelled.",
        reply_markup=keyboard,
    )
    await callback.answer()


async def pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    payload_info = _parse_payload(pre_checkout_query.invoice_payload)
    valid = (
        payload_info is not None
        and pre_checkout_query.currency == "XTR"
        and settings.pro_price_stars > 0
        and pre_checkout_query.total_amount == settings.pro_price_stars
        and payload_info[0] == pre_checkout_query.from_user.id
    )
    if not valid:
        await pre_checkout_query.answer(
            ok=False,
            error_message="This subscription invoice is no longer valid. Please open /subscribe and try again.",
        )
        return
    await pre_checkout_query.answer(ok=True)


async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None or payment.currency != "XTR":
        return

    payload_info = _parse_payload(payment.invoice_payload)
    if payload_info is None or payload_info[0] != message.from_user.id:
        return

    paid_at = datetime.now(timezone.utc)
    expiration = (
        datetime.fromtimestamp(payment.subscription_expiration_date, tz=timezone.utc)
        if payment.subscription_expiration_date
        else None
    )

    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)

        existing = await session.scalar(
            select(SubscriptionPayment).where(
                SubscriptionPayment.telegram_payment_charge_id == payment.telegram_payment_charge_id
            )
        )
        if existing is not None:
            await message.answer("✅ Payment already recorded; your Pro access is unchanged.")
            return

        current_expiry = _aware_utc(user.plan_expires_at)
        if expiration is None:
            base = current_expiry if current_expiry and current_expiry > paid_at else paid_at
            expiration = base + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS)

        user.plan = PRO_PLAN
        user.plan_expires_at = expiration

        session.add(
            SubscriptionPayment(
                user_id=user.id,
                plan=PRO_PLAN,
                telegram_payment_charge_id=payment.telegram_payment_charge_id,
                provider_payment_charge_id=payment.provider_payment_charge_id,
                invoice_payload=payment.invoice_payload,
                currency=payment.currency,
                amount_stars=payment.total_amount,
                subscription_expires_at=expiration,
                paid_at=paid_at,
                is_recurring=bool(payment.is_recurring),
                is_first_recurring=bool(payment.is_first_recurring),
            )
        )
        await session.commit()

    await message.answer(
        "<b>✅ Tickaro Pro activated</b>\n\n"
        f"Active until: <code>{expiration.strftime('%d %b %Y, %H:%M UTC')}</code>\n"
        "Your subscription will renew automatically through Telegram Stars."
    )


def install(router: Router) -> None:
    if getattr(router, "_subscriptions_installed", False):
        return
    router.message.register(show_subscribe, Command("subscribe"))
    router.callback_query.register(subscribe_callback, F.data.startswith("subscribe:"))
    router.pre_checkout_query.register(pre_checkout)
    router.message.register(successful_payment, F.successful_payment)
    router._subscriptions_installed = True

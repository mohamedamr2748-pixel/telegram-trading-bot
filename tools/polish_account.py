from pathlib import Path
import re

path = Path("app/bot.py")
text = path.read_text()

pattern = r'@router\\.message\\(Command\("account"\)\\)\\nasync def account\\(message: Message\\) -> None:\\n.*?\\n\\n\\n@router\\.message\\(Command\("price"\)\\)'
replacement = '''@router.message(Command("account"))
async def account(message: Message) -> None:
    from datetime import date

    from app.db import Usage

    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watch_count = await session.scalar(select(func.count(WatchlistItem.id)).join(Watchlist).where(Watchlist.user_id == user.id)) or 0
        alerts = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "price")) or 0
        smart = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "smart")) or 0
        usage_result = await session.execute(
            select(Usage.key, Usage.count).where(
                Usage.user_id == user.id,
                Usage.day == date.today(),
            )
        )
        usage = dict(usage_result.all())

        limits = {
            "price": 50,
            "chart": 10,
            "news": 30,
            "scanner": 5,
            "brief": 1,
            "why": 3,
            "advanced": 3,
        }

        await message.answer(
            "👤 <b>MY ACCOUNT</b>\\n\\n"
            "<b>PLAN</b>\\n"
            f"🆓 {user.plan.title()}\\n\\n"
            "<b>PORTFOLIO</b>\\n"
            f"⭐ Watchlist       <b>{watch_count} / 10</b>\\n"
            f"🔔 Price alerts   <b>{alerts} / 3</b>\\n"
            f"🧠 Smart alerts   <b>{smart} / 3</b>\\n\\n"
            "<b>SETTINGS</b>\\n"
            f"🌍 Timezone        <code>{user.timezone}</code>\\n\\n"
            "<b>USAGE • TODAY</b>\\n"
            f"💰 Price           <code>{usage.get('price', 0)} / {limits['price']}</code>\\n"
            f"📈 Charts          <code>{usage.get('chart', 0)} / {limits['chart']}</code>\\n"
            f"📰 News            <code>{usage.get('news', 0)} / {limits['news']}</code>\\n"
            f"🔎 Scanner         <code>{usage.get('scanner', 0)} / {limits['scanner']}</code>\\n"
            f"🌅 Brief           <code>{usage.get('brief', 0)} / {limits['brief']}</code>\\n"
            f"🔍 Why             <code>{usage.get('why', 0)} / {limits['why']}</code>\\n"
            f"📊 Advanced        <code>{usage.get('advanced', 0)} / {limits['advanced']}</code>"
        )


@router.message(Command("price"))'''

new_text, count = re.subn(pattern, replacement, text, flags=re.S)
if count != 1:
    raise SystemExit(f"Expected exactly one account handler, found {count}")
path.write_text(new_text)

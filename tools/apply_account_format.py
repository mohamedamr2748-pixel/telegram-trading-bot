from pathlib import Path
from textwrap import dedent

path = Path("app/bot.py")
text = path.read_text(encoding="utf-8")
start_marker = '@router.message(Command("account"))\nasync def account(message: Message) -> None:'
end_marker = '\n@router.message(Command("price"))'
start = text.find(start_marker)
end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
if start < 0 or end < 0:
    raise SystemExit("account handler markers not found")

replacement = dedent('''
@router.message(Command("account"))
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
        await message.answer(
            "👤 <b>MY ACCOUNT</b>\n\n"
            "<b>PLAN</b>\n"
            f"{user.plan.title()}\n\n"
            "<b>ACCOUNT</b>\n"
            f"Joined: {user.created_at.strftime('%d %b %Y')}\n\n"
            "<b>PORTFOLIO</b>\n"
            f"Watchlist: {watch_count}/10\n"
            f"Price alerts: {alerts}/3\n"
            f"Smart alerts: {smart}/3\n\n"
            "<b>SETTINGS</b>\n"
            f"Timezone: {user.timezone}\n\n"
            "<b>USAGE • TODAY</b>\n"
            f"Price: {usage.get('price', 0)}/50\n"
            f"Charts: {usage.get('chart', 0)}/10\n"
            f"News: {usage.get('news', 0)}/30\n"
            f"Scanner: {usage.get('scanner', 0)}/5\n"
            f"Brief: {usage.get('brief', 0)}/1\n"
            f"Why: {usage.get('why', 0)}/3\n"
            f"Advanced: {usage.get('advanced', 0)}/3"
        )
''').rstrip()

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")

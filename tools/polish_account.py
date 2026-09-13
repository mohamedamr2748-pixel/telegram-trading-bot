from pathlib import Path
import re

path = Path("app/bot.py")
text = path.read_text()

pattern = r'@router\.message\(Command\("account"\)\)\nasync def account\(message: Message\) -> None:\n.*?\n\n\n@router\.message\(Command\("price"\)\)'
replacement = '''@router.message(Command("account"))
async def account(message: Message) -> None:
    from datetime import date
    from app.db import Usage

    async with session_factory() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        watch_count = await session.scalar(select(func.count(WatchlistItem.id)).join(Watchlist).where(Watchlist.user_id == user.id)) or 0
        alerts = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "price")) or 0
        smart = await session.scalar(select(func.count(Alert.id)).where(Alert.user_id == user.id, Alert.active.is_(True), Alert.alert_type == "smart")) or 0
        usage_result = await session.execute(select(Usage.key, Usage.count).where(Usage.user_id == user.id, Usage.day == date.today()))
        usage = dict(usage_result.all())

        await message.answer(
            "👤 <b>MY ACCOUNT</b>\n\n"
            "<b>PLAN</b>\n"
            "<code>Free</code>\n\n"
            "<b>ACCOUNT</b>\n"
            f"<code>Timezone       {user.timezone}</code>\n\n"
            "<b>PORTFOLIO</b>\n"
            f"<code>Watchlist      {watch_count} / 10</code>\n"
            f"<code>Price alerts   {alerts} / 3</code>\n"
            f"<code>Smart alerts   {smart} / 3</code>\n\n"
            "<b>USAGE • TODAY</b>\n"
            f"<code>Price          {usage.get('price', 0)} / 50</code>\n"
            f"<code>Charts         {usage.get('chart', 0)} / 10</code>\n"
            f"<code>News           {usage.get('news', 0)} / 30</code>\n"
            f"<code>Scanner        {usage.get('scanner', 0)} / 5</code>\n"
            f"<code>Brief          {usage.get('brief', 0)} / 1</code>\n"
            f"<code>Why            {usage.get('why', 0)} / 3</code>\n"
            f"<code>Advanced       {usage.get('advanced', 0)} / 3</code>"
        )


@router.message(Command("price"))'''

new_text, count = re.subn(pattern, replacement, text, flags=re.S)
if count != 1:
    raise SystemExit(f"Expected exactly one account handler, found {count}")
path.write_text(new_text)

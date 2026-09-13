from __future__ import annotations

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

        def row(label: str, value: str) -> str:
            return f"<code>{label:<16}{value}</code>"

        await message.answer(
            "👤 <b>MY ACCOUNT</b>\n\n"
            "<b>PLAN</b>\n"
            f"<code>{user.plan.title()}</code>\n\n"
            "<b>ACCOUNT</b>\n"
            + row("Joined", user.created_at.strftime("%d %b %Y")) + "\n\n"
            "<b>PORTFOLIO</b>\n"
            + row("Watchlist", f"{watch_count} / 10") + "\n"
            + row("Price alerts", f"{alerts} / 3") + "\n"
            + row("Smart alerts", f"{smart} / 3") + "\n\n"
            "<b>SETTINGS</b>\n"
            + row("Timezone", user.timezone) + "\n\n"
            "<b>USAGE • TODAY</b>\n"
            + row("Price", f"{usage.get('price', 0)} / 50") + "\n"
            + row("Charts", f"{usage.get('chart', 0)} / 10") + "\n"
            + row("News", f"{usage.get('news', 0)} / 30") + "\n"
            + row("Scanner", f"{usage.get('scanner', 0)} / 5") + "\n"
            + row("Brief", f"{usage.get('brief', 0)} / 1") + "\n"
            + row("Why", f"{usage.get('why', 0)} / 3") + "\n"
            + row("Advanced", f"{usage.get('advanced', 0)} / 3")
        )
''').rstrip()

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")

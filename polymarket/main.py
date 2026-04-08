import asyncio
import logging
import sys
from datetime import datetime, timezone

import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from polymarket.config import settings
from polymarket.database import connect, disconnect, get_db, get_pause_state, set_pause_state
from polymarket.services.clob_listener import ClobListener
from polymarket.services.gamma_poller import GammaPoller, fetch_event_by_slug, _extract_prices

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_token)
dp = Dispatcher()
_poller: GammaPoller | None = None
_clob: ClobListener | None = None


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    status = "PAUSED" if await get_pause_state() else "ACTIVE"
    await message.answer(
        f"Polymarket Sniper Bot online.\nStatus: <b>{status}</b>\n\n"
        f"/pause — suspend all alerts\n"
        f"/resume — restore alerts\n"
        f"/add_event &lt;url_or_slug&gt; — track a specific event\n"
        f"/add_keyword &lt;word&gt; — add a keyword to monitor",
        parse_mode="HTML",
    )


@dp.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    if await get_pause_state():
        await message.answer("Bot is already paused.")
        return
    await set_pause_state(True)
    logger.info("Bot paused by %s", message.from_user.id if message.from_user else "?")
    await message.answer("Alerts suspended. Use /resume to re-enable.")


@dp.message(Command(commands=["resume", "continue"]))
async def cmd_resume(message: Message) -> None:
    if not await get_pause_state():
        await message.answer("Bot is already active.")
        return
    await set_pause_state(False)
    logger.info("Bot resumed by %s", message.from_user.id if message.from_user else "?")
    await message.answer("Alerts restored.")


@dp.message(Command("add_event"))
async def cmd_add_event(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /add_event &lt;polymarket_url_or_slug&gt;", parse_mode="HTML")
        return
    raw = args[1].strip()
    slug = (
        raw.split("polymarket.com/event/")[1].split("/")[0].split("?")[0]
        if "polymarket.com/event/" in raw else raw
    )
    await message.answer(f"Looking up: <code>{slug}</code>…", parse_mode="HTML")
    async with httpx.AsyncClient(timeout=15.0) as client:
        event = await fetch_event_by_slug(client, slug)
    if not event:
        await message.answer(f"Not found: <code>{slug}</code>", parse_mode="HTML")
        return
    event_id = str(event["id"])
    title = event.get("title", "")
    volume = float(event.get("volume") or 0)
    db = get_db()
    if await db.tracked_events.find_one({"event_id": event_id}):
        await message.answer(f"Already tracking: <b>{title}</b>", parse_mode="HTML")
        return
    await db.tracked_events.insert_one({
        "event_id": event_id, "title": title, "volume": volume,
        "last_prices": _extract_prices(event.get("markets", [])),
        "is_manual": True, "updated_at": datetime.now(timezone.utc),
    })
    await message.answer(f"Now tracking: <b>{title}</b>  Vol: ${volume:,.0f}", parse_mode="HTML")


async def main() -> None:
    global _poller, _clob
    await connect()
    _poller = GammaPoller(bot=bot, chat_id=settings.telegram_chat_id)
    _clob = ClobListener(bot=bot, chat_id=settings.telegram_chat_id)
    pt = asyncio.create_task(_poller.start(), name="gamma_poller")
    ct = asyncio.create_task(_clob.start(), name="clob_listener")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        pt.cancel(); ct.cancel()
        await _poller.stop(); await _clob.stop()
        await disconnect(); await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

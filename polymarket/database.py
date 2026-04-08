import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from polymarket.config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client.get_default_database(default="polymarket_bot")
    await _ensure_indexes()
    logger.info("MongoDB connected")


async def disconnect() -> None:
    if _client:
        _client.close()
        logger.info("MongoDB disconnected")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call connect() first")
    return _db


async def _ensure_indexes() -> None:
    db = get_db()
    await db.tracked_events.create_index("event_id", unique=True)
    await db.keywords.create_index("word", unique=True)
    await db.whale_wallets.create_index("address", unique=True)
    await db.whale_wallets.create_index("cached_at", expireAfterSeconds=86400)


async def get_pause_state() -> bool:
    doc = await get_db().bot_state.find_one({"_id": "global"})
    return bool(doc and doc.get("is_paused", False))


async def set_pause_state(paused: bool) -> None:
    await get_db().bot_state.update_one(
        {"_id": "global"},
        {"$set": {"is_paused": paused}},  # $set operator — not empty string
        upsert=True,
    )
    logger.info("Pause state → %s", paused)

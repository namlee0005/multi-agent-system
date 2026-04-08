import logging
from datetime import datetime, timezone

import httpx

from polymarket.config import settings
from polymarket.database import get_db

POLYGONSCAN_API = "https://api.polygonscan.com/api"
logger = logging.getLogger(__name__)


async def get_wallet_tx_count(address: str) -> int | None:
    """
    Returns outgoing tx count (nonce) for a Polygon wallet.
    Cached 24h in MongoDB whale_wallets — TTL index handles expiry.
    Returns None if API key is missing or fetch fails.
    """
    if not settings.polygonscan_api_key:
        logger.debug("POLYGONSCAN_API_KEY not set, skipping enrichment")
        return None

    db = get_db()
    cached = await db.whale_wallets.find_one({"address": address})
    if cached and "tx_count" in cached:
        return cached["tx_count"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                POLYGONSCAN_API,
                params={
                    "module": "proxy",
                    "action": "eth_getTransactionCount",
                    "address": address,
                    "tag": "latest",
                    "apikey": settings.polygonscan_api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", "0x0")
            if not isinstance(result, str) or not result.startswith("0x"):
                logger.warning("Unexpected Polygonscan result for %s: %s", address, result)
                return None
            tx_count = int(result, 16)
    except Exception:
        logger.exception("Polygonscan fetch failed for address=%s", address)
        return None

    # Upsert — TTL index on cached_at auto-expires after 24h
    await db.whale_wallets.update_one(
        {"address": address},
        {"$set": {
            "address": address,
            "tx_count": tx_count,
            "cached_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    logger.info("Polygonscan cached: address=%s tx_count=%d", address[:10], tx_count)
    return tx_count

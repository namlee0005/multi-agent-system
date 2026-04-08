"""
Polymarket-native wallet analytics — data-api.polymarket.com/activity
Cached 24h in MongoDB whale_wallets via TTL index.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from polymarket.database import get_db

DATA_API = "https://data-api.polymarket.com"
logger = logging.getLogger(__name__)


@dataclass
class WalletProfile:
    address: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    profit_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    loss_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    volume_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def win_rate(self) -> float:
        resolved = self.wins + self.losses
        return round(self.wins / resolved, 4) if resolved > 0 else 0.0

    @property
    def net_pnl(self) -> Decimal:
        return self.profit_usd - self.loss_usd


async def get_wallet_profile(address: str) -> WalletProfile | None:
    db = get_db()
    cached = await db.whale_wallets.find_one({"address": address})
    if cached and "trades" in cached:
        return WalletProfile(
            address=address,
            trades=cached.get("trades", 0),
            wins=cached.get("wins", 0),
            losses=cached.get("losses", 0),
            profit_usd=Decimal(str(cached.get("profit_usd", "0"))),
            loss_usd=Decimal(str(cached.get("loss_usd", "0"))),
            volume_usd=Decimal(str(cached.get("volume_usd", "0"))),
        )

    profile = await _fetch_profile(address)
    if profile is None:
        return None

    await db.whale_wallets.update_one(
        {"address": address},
        {"$set": {
            "address": address,
            "trades": profile.trades, "wins": profile.wins, "losses": profile.losses,
            "profit_usd": str(profile.profit_usd), "loss_usd": str(profile.loss_usd),
            "volume_usd": str(profile.volume_usd),
            "cached_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    logger.info("Wallet cached: %s trades=%d pnl=%s", address[:10], profile.trades, profile.net_pnl)
    return profile


async def _fetch_profile(address: str) -> WalletProfile | None:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                f"{DATA_API}/activity",
                params={"user": address, "limit": 500, "offset": 0},
            )
            resp.raise_for_status()
            body = resp.json()
            items: list[dict] = body if isinstance(body, list) else body.get("data", [])
    except Exception:
        logger.exception("Wallet fetch failed: %s", address)
        return None

    profile = WalletProfile(address=address)
    for item in items:
        profile.trades += 1
        cash_out = Decimal(str(item.get("cashOut") or item.get("cash_out") or "0"))
        cash_in = Decimal(str(item.get("cashIn") or item.get("cash_in") or item.get("size") or "0"))
        pnl = cash_out - cash_in
        profile.volume_usd += cash_in
        if pnl > 0:
            profile.wins += 1
            profile.profit_usd += pnl
        elif pnl < 0:
            profile.losses += 1
            profile.loss_usd += abs(pnl)
    return profile

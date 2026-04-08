import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from polymarket.config import settings
from polymarket.database import get_db, get_pause_state

GAMMA_API = "https://gamma-api.polymarket.com"
logger = logging.getLogger(__name__)


class GammaPoller:
    def __init__(self, bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "polymarket-bot/1.0"})
        logger.info("GammaPoller started interval=%ss", settings.gamma_poll_interval_seconds)
        while True:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("GammaPoller error")
            await asyncio.sleep(settings.gamma_poll_interval_seconds)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    async def poll_once(self) -> None:
        events = await self._fetch_events()
        logger.info("Fetched %d events", len(events))
        for event in events:
            try:
                await self._process_event(event)
            except Exception:
                logger.exception("Error event_id=%s", event.get("id"))

    async def _fetch_events(self) -> list[dict]:
        resp = await self._client.get(
            f"{GAMMA_API}/events",
            params={
                "limit": 100, "order": "volume", "ascending": "false",
                "volume_num_min": settings.volume_min_usd,
                "active": "true", "closed": "false",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])

    async def _process_event(self, event: dict) -> None:
        event_id = str(event["id"])
        title = event.get("title", "")
        volume = Decimal(str(event.get("volume") or "0"))
        markets: list[dict] = event.get("markets", [])
        url = f"https://polymarket.com/event/{event.get('slug', event_id)}"

        db = get_db()
        existing = await db.tracked_events.find_one({"event_id": event_id})

        if existing is None:
            await db.tracked_events.insert_one({
                "event_id": event_id, "title": title,
                "volume": float(volume),
                "last_prices": _extract_prices(markets),
                "condition_ids": _extract_condition_ids(markets),
                "is_manual": False,
                "updated_at": datetime.now(timezone.utc),
            })
            logger.info("New event: %s vol=$%s", title, volume)
            return

        last_prices = existing.get("last_prices", {})
        new_prices: dict = {}
        alerts: list[dict] = []

        for market in markets:
            market_id = str(market["id"])
            outcomes = _parse_json_field(market.get("outcomes", "[]"))
            prices = _parse_json_field(market.get("outcomePrices", "[]"))
            new_prices[market_id] = prices
            prev = last_prices.get(market_id, [])
            for i, (outcome, p) in enumerate(zip(outcomes, prices)):
                try:
                    cur = Decimal(str(p))
                    if i < len(prev) and prev[i]:
                        old = Decimal(str(prev[i]))
                        if old > 0:
                            delta = (cur - old) / old
                            if abs(delta) >= Decimal(str(settings.volatility_threshold)):
                                alerts.append({
                                    "question": market.get("question", ""),
                                    "outcome": outcome, "delta": delta,
                                    "current": cur, "previous": old,
                                })
                except Exception:
                    logger.warning("Price parse failed market=%s idx=%d", market_id, i)

        await db.tracked_events.update_one(
            {"event_id": event_id},
            {"$set": {"volume": float(volume), "last_prices": new_prices,
                      "updated_at": datetime.now(timezone.utc)}},
        )
        if alerts and not await get_pause_state():
            await self._send_alerts(title, url, volume, alerts)

    async def _send_alerts(self, title: str, url: str, volume: Decimal, alerts: list[dict]) -> None:
        for a in alerts:
            sign = "+" if a["delta"] > 0 else ""
            pct = f"{sign}{float(a['delta']) * 100:.1f}%"
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=(
                    f"📈 <b>POLYMARKET ALERT</b>\n\n"
                    f"<b>Event:</b> {title}\n<b>Market:</b> {a['question']}\n"
                    f"<b>Outcome:</b> {a['outcome']}\n<b>Change:</b> {pct}\n"
                    f"<b>Price:</b> {a['current']:.3f} (was {a['previous']:.3f})\n"
                    f"<b>Volume:</b> ${float(volume):,.0f}\n"
                    f"<a href=\"{url}\">View on Polymarket</a>"
                ),
                parse_mode="HTML", disable_web_page_preview=True,
            )
            logger.info("Alert: %s | %s | %s", title, a["outcome"], pct)


def _parse_json_field(value) -> list:
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _extract_prices(markets: list[dict]) -> dict:
    return {str(m["id"]): _parse_json_field(m.get("outcomePrices", "[]")) for m in markets}


def _extract_condition_ids(markets: list[dict]) -> list[str]:
    return [str(cid) for m in markets if (cid := m.get("conditionId") or m.get("condition_id"))]


async def fetch_event_by_slug(client: httpx.AsyncClient, slug: str) -> dict | None:
    resp = await client.get(f"{GAMMA_API}/events", params={"slug": slug, "limit": 1})
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return items[0] if items else None

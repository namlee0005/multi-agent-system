import asyncio
import json
import logging
from decimal import Decimal

import websockets
from websockets.exceptions import ConnectionClosed

from polymarket.config import settings
from polymarket.database import get_db, get_pause_state
from polymarket.services.wallet_profiler import WalletProfile, get_wallet_profile

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SUBSCRIPTION_BATCH = 500
logger = logging.getLogger(__name__)


class ClobListener:
    def __init__(self, bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self._running = False

    async def start(self) -> None:
        self._running = True
        backoff = 5
        while self._running:
            try:
                await self._run_session()
                backoff = 5
            except (ConnectionClosed, OSError):
                logger.warning("CLOB disconnected, retry in %ds", backoff)
            except Exception:
                logger.exception("CLOB error, retry in %ds", backoff)
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def stop(self) -> None:
        self._running = False

    async def _run_session(self) -> None:
        cids = await self._get_condition_ids()
        if not cids:
            logger.info("No condition_ids, waiting 30s")
            await asyncio.sleep(30)
            return
        async with websockets.connect(CLOB_WS_URL, ping_interval=20, ping_timeout=30) as ws:
            logger.info("CLOB connected, subscribing to %d IDs", len(cids))
            for i in range(0, len(cids), SUBSCRIPTION_BATCH):
                await ws.send(json.dumps({"assets_ids": cids[i:i + SUBSCRIPTION_BATCH], "type": "market"}))
            async for raw in ws:
                if not self._running:
                    break
                try:
                    await self._handle_message(raw)
                except Exception:
                    logger.exception("CLOB message error")

    async def _get_condition_ids(self) -> list[str]:
        ids: list[str] = []
        async for doc in get_db().tracked_events.find({}, {"condition_ids": 1}):
            ids.extend(doc.get("condition_ids", []))
        return ids

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        for event in (data if isinstance(data, list) else [data]):
            if event.get("event_type") == "trade":
                await self._process_trade(event)

    async def _process_trade(self, event: dict) -> None:
        try:
            value_usd = Decimal(str(event.get("size", "0"))) * Decimal(str(event.get("price", "0")))
        except Exception:
            return
        if value_usd < Decimal(str(settings.whale_threshold_usd)):
            return

        side: str = event.get("side", "BUY")
        maker: str = event.get("maker_address", "")
        tx_hash: str = event.get("transaction_hash", "")
        price = Decimal(str(event.get("price", "0")))

        profile = await get_wallet_profile(maker) if maker else None
        logger.info("Whale: side=%s $%s maker=%s", side, value_usd, maker[:10] if maker else "?")

        if not await get_pause_state():
            await self._send_alert(side, value_usd, price, maker, profile, tx_hash)

    async def _send_alert(
        self, side: str, value_usd: Decimal, price: Decimal,
        maker: str, profile: WalletProfile | None, tx_hash: str,
    ) -> None:
        emoji = "🟢" if side == "BUY" else "🔴"
        short = f"{maker[:6]}…{maker[-4:]}" if len(maker) > 10 else maker
        pm_url = f"https://polymarket.com/profile/{maker}"

        if profile:
            sign = "+" if profile.net_pnl >= 0 else ""
            wallet_block = (
                f'\n<b>Wallet:</b> <a href="{pm_url}">{short}</a>\n'
                f"<b>PM Trades:</b> {profile.trades:,}\n"
                f"<b>Win/Loss:</b> {profile.wins}W / {profile.losses}L ({profile.win_rate * 100:.1f}% WR)\n"
                f"<b>Net PnL:</b> {sign}${float(profile.net_pnl):,.0f}\n"
                f"<b>Volume:</b> ${float(profile.volume_usd):,.0f}"
            )
        else:
            wallet_block = f'\n<b>Wallet:</b> <a href="{pm_url}">{short}</a>'

        tx_line = (
            f'\n<b>TX:</b> <a href="https://polygonscan.com/tx/{tx_hash}">Polygonscan</a>'
            if tx_hash else ""
        )
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"{emoji} <b>WHALE ALERT</b>\n\n"
                f"<b>Side:</b> {side}\n<b>Size:</b> ${float(value_usd):,.0f}\n"
                f"<b>Price:</b> {price:.4f}{wallet_block}{tx_line}"
            ),
            parse_mode="HTML", disable_web_page_preview=True,
        )

"""Entry point — wires Telegram bot, Hyperliquid WebSocket, storage, detector."""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from logging.handlers import RotatingFileHandler

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from bot.formatter import (
    format_anomaly,
    format_fills_aggregated,
    format_position_close,
    format_position_open,
    format_position_scaled,
    short_addr,
)
from bot.handlers import Handlers
from database.storage import Order, Position, Storage
from hl_monitor.client import HyperliquidWS
from hl_monitor.detector import AnomalyDetector
from hl_monitor.parser import FillEvent, OrderEvent, PositionEvent
from hl_monitor.rest import HyperliquidREST

# ---------------------------------------------------------------------------
#  logging
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(config.LOG_PATH, maxBytes=5 * 1024 * 1024,
                            backupCount=3, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)
    # tame chatty libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


log = logging.getLogger("main")


# ---------------------------------------------------------------------------
#  Glue
# ---------------------------------------------------------------------------

class Bot:
    """Owns the storage, WS client, telegram app and the wiring between them."""

    def __init__(self):
        self.storage = Storage(config.DB_PATH, config.SCHEMA_PATH)
        self.detector = AnomalyDetector(
            window_sec=config.ANOMALY_TIME_WINDOW,
            min_wallets=config.ANOMALY_MIN_WALLETS,
        )
        self.labels: dict[str, str] = {}  # address -> label

        # Unrealized PnL cache: {wallet: {coin: unrealized_pnl}}
        self.unrealized_pnl: dict[str, dict[str, float]] = {}

        # Recent fills cache for exact PnL: {wallet: {coin: closed_pnl}}
        self._fill_pnl: dict[str, dict[str, float]] = {}

        # Fill aggregation: {(wallet, coin): {count, total_size, total_notional, ...}}
        self._fill_agg: dict[tuple[str, str], dict] = {}

        # Rate limiter: simple semaphore for Telegram sends
        self._send_semaphore = asyncio.Semaphore(20)

        self.rest = HyperliquidREST()

        self.ws = HyperliquidWS(
            url=config.HL_WS_URL,
            on_position=self._on_position_event,
            on_order=self._on_order_event,
            on_fill=self._on_fill_event,
            ping_interval=config.WS_PING_INTERVAL,
            reconnect_delay=config.WS_RECONNECT_DELAY,
            max_reconnect_delay=config.WS_MAX_RECONNECT_DELAY,
        )

        self.tg_app: Application | None = None
        self._ws_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._stop_flush = asyncio.Event()

    # ------------------------------------------------------------------
    #  Notifications back to user
    # ------------------------------------------------------------------

    async def _send(self, text: str) -> None:
        if not self.tg_app or not config.MY_CHAT_ID:
            log.info("[notify] %s", text.replace("\n", " | "))
            return
        async with self._send_semaphore:
            try:
                await self.tg_app.bot.send_message(
                    chat_id=config.MY_CHAT_ID,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.warning("Failed to send tg message: %s", e)
            await asyncio.sleep(0.05)

    # ------------------------------------------------------------------
    #  WebSocket -> Telegram pipeline
    # ------------------------------------------------------------------

    async def _on_position_event(self, ev: PositionEvent) -> None:
        wallet = ev.wallet.lower()
        label = self.labels.get(wallet) or short_addr(wallet)

        if config.MIN_POSITION_USD and ev.notional < config.MIN_POSITION_USD:
            return

        # For scale events also require the *change* to clear the threshold —
        # otherwise a $37K position growing by $400 would spam the chat.
        if ev.kind == "scale":
            prev_notional = ev.pnl or 0.0
            delta = abs(ev.notional - prev_notional)
            if config.MIN_POSITION_USD and delta < config.MIN_POSITION_USD:
                return

        if ev.kind == "open":
            try:
                await self.storage.open_position(Position(
                    id=None, wallet=wallet, coin=ev.coin, side=ev.side,
                    size=ev.size, notional=ev.notional,
                    entry_price=ev.entry_price, leverage=ev.leverage,
                    opened_at=int(time.time()),
                ))
                await self.storage.add_history(
                    wallet, "open", ev.coin, ev.side,
                    {"size": ev.size, "notional": ev.notional,
                     "entry": ev.entry_price, "lev": ev.leverage},
                )
            except Exception:
                log.exception("DB open_position failed")

            await self._send(format_position_open(ev, label))

            hit = self.detector.record_open(
                wallet=wallet, label=label, coin=ev.coin,
                side=ev.side, notional=ev.notional,
            )
            if hit:
                await self._send(format_anomaly(hit, self.labels))

        elif ev.kind == "close":
            try:
                fill_pnl = self._fill_pnl.get(wallet, {}).pop(ev.coin, None)
                pnl = fill_pnl if fill_pnl is not None else (ev.pnl or 0.0)
                close_px = ev.close_price or ev.entry_price
                stored = await self.storage.close_position(
                    wallet=wallet, coin=ev.coin,
                    close_price=close_px, pnl=pnl,
                )
                if stored and ev.holding_seconds is None:
                    ev.holding_seconds = int(time.time()) - stored.opened_at
                ev.pnl = pnl
                await self.storage.add_history(
                    wallet, "close", ev.coin, ev.side,
                    {"close": close_px, "pnl": pnl},
                )
            except Exception:
                log.exception("DB close_position failed")

            self.unrealized_pnl.get(wallet, {}).pop(ev.coin, None)
            await self._send(format_position_close(ev, label))

        elif ev.kind == "scale":
            prev_size = ev.close_price or ev.size  # overloaded in diff
            prev_notional = ev.pnl or ev.notional  # overloaded in diff
            await self._send(format_position_scaled(
                ev, label, prev_size, prev_notional,
            ))
            await self.storage.add_history(
                wallet, "scale", ev.coin, ev.side,
                {"size": ev.size, "notional": ev.notional,
                 "entry": ev.entry_price},
            )

    async def _on_fill_event(self, ev: FillEvent) -> None:
        wallet = ev.wallet.lower()
        if ev.closed_pnl != 0:
            wallet_fills = self._fill_pnl.setdefault(wallet, {})
            wallet_fills[ev.coin] = wallet_fills.get(ev.coin, 0) + ev.closed_pnl
        self.unrealized_pnl.setdefault(wallet, {})

        notional = ev.size * ev.price
        now = int(time.time())
        # Aggregation is keyed by (wallet, coin, side) so BUY-into-LONG and
        # SELL-out-of-LONG don't share a buffer.
        key = (wallet, ev.coin, ev.side)
        agg = self._fill_agg.get(key)
        if agg is None:
            agg = {
                "wallet": wallet, "coin": ev.coin, "side": ev.side,
                "count": 0, "total_size": 0.0, "total_notional": 0.0,
                "total_pnl": 0.0, "total_fee": 0.0, "avg_price": 0.0,
                "open_fills": 0, "close_fills": 0,
                "open_notional": 0.0, "close_notional": 0.0,
                "first_ts": ev.timestamp or now,
                "last_ts": ev.timestamp or now,
            }
            self._fill_agg[key] = agg

        agg["count"] += 1
        agg["total_size"] += ev.size
        agg["total_notional"] += notional
        agg["total_pnl"] += ev.closed_pnl
        agg["total_fee"] += ev.fee
        agg["last_ts"] = ev.timestamp or now
        if ev.closed_pnl != 0:
            agg["close_fills"] += 1
            agg["close_notional"] += notional
        else:
            agg["open_fills"] += 1
            agg["open_notional"] += notional
        if agg["total_size"]:
            agg["avg_price"] = agg["total_notional"] / agg["total_size"]

        if agg["total_notional"] >= config.FILL_AGG_THRESHOLD:
            self._attach_position_avg(agg)
            label = self.labels.get(wallet) or short_addr(wallet)
            await self._send(format_fills_aggregated(agg, label))
            del self._fill_agg[key]

    def _attach_position_avg(self, agg: dict) -> None:
        """Look up the live position snapshot to enrich agg with avg entry."""
        try:
            snap = self.ws.get_positions(agg["wallet"]).get(agg["coin"])
            if snap:
                agg["position_entry_price"] = snap.entry_price
                agg["position_notional"] = snap.notional
        except Exception:
            log.exception("attach position avg failed")

    async def _flush_loop(self) -> None:
        """Periodically flush stale fill aggregations that haven't crossed the threshold."""
        while not self._stop_flush.is_set():
            try:
                await asyncio.wait_for(self._stop_flush.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            else:
                return
            now = int(time.time())
            stale = [
                k for k, a in self._fill_agg.items()
                if now - a["last_ts"] > config.FILL_AGG_FLUSH_SEC
                and a["total_notional"] >= config.FILL_AGG_THRESHOLD
            ]
            for k in stale:
                agg = self._fill_agg.pop(k, None)
                if not agg:
                    continue
                self._attach_position_avg(agg)
                wallet = agg["wallet"]
                label = self.labels.get(wallet) or short_addr(wallet)
                try:
                    await self._send(format_fills_aggregated(agg, label))
                except Exception:
                    log.exception("flush send failed")

    async def _on_order_event(self, ev: OrderEvent) -> None:
        wallet = ev.wallet.lower()

        if ev.kind == "placed":
            is_new, _ = await self.storage.upsert_order(Order(
                id=None, wallet=wallet, oid=ev.oid, coin=ev.coin,
                type=ev.type, size=ev.size, notional=ev.notional,
                price=ev.price, status="open", created_at=int(time.time()),
            ))
            if is_new:
                await self.storage.add_history(
                    wallet, "order_open", ev.coin, ev.type,
                    {"oid": ev.oid, "price": ev.price, "size": ev.size},
                )
        elif ev.kind == "canceled":
            closed = await self.storage.close_order(wallet, ev.oid, "canceled")
            if closed:
                await self.storage.add_history(
                    wallet, "order_cancel", ev.coin, closed.type,
                    {"oid": ev.oid},
                )
        elif ev.kind == "filled":
            closed = await self.storage.close_order(wallet, ev.oid, "filled")
            if closed:
                await self.storage.add_history(
                    wallet, "order_fill", ev.coin, closed.type,
                    {"oid": ev.oid},
                )

    # ------------------------------------------------------------------
    #  WS subscription bridge for handlers
    # ------------------------------------------------------------------

    async def _subscribe_active(self, addr: str, label: str) -> None:
        await self.ws.add_wallet(addr, label)

    async def _unsubscribe(self, addr: str) -> None:
        await self.ws.remove_wallet(addr)

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        await self.storage.init()

        # restore active wallets from DB
        for w in await self.storage.list_wallets(only_active=True):
            self.labels[w.address] = w.label
            await self.ws.add_wallet(w.address, w.label)
        # remember labels of paused too — для показа в /list
        for w in await self.storage.list_wallets():
            self.labels.setdefault(w.address, w.label)

        # build telegram app
        self.tg_app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
        h = Handlers(
            storage=self.storage,
            ws_subscribe=self._subscribe_active,
            ws_unsubscribe=self._unsubscribe,
            labels=self.labels,
        )
        h._ws_ref = self.ws
        h._rest_ref = self.rest
        app = self.tg_app
        app.add_handler(CommandHandler("start", h.start))
        app.add_handler(CommandHandler("help", h.help_cmd))
        app.add_handler(CommandHandler("menu", h.menu))
        app.add_handler(CommandHandler("add", h.add))
        app.add_handler(CommandHandler("remove", h.remove))
        app.add_handler(CommandHandler("list", h.list_cmd))
        app.add_handler(CommandHandler("positions", h.positions))
        app.add_handler(CommandHandler("rename", h.rename))
        app.add_handler(CommandHandler("pause", h.pause))
        app.add_handler(CommandHandler("resume", h.resume))
        app.add_handler(CommandHandler("stats", h.stats))
        app.add_handler(CommandHandler("cancel", h.cancel))
        app.add_handler(CallbackQueryHandler(h.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.on_message))
        app.add_error_handler(_error_handler)

    async def run(self) -> None:
        await self.setup()
        assert self.tg_app is not None

        # start WS + flush task
        self._ws_task = asyncio.create_task(self.ws.run(), name="hl-ws")
        self._flush_task = asyncio.create_task(self._flush_loop(), name="agg-flush")

        # start telegram polling (retry on Conflict from stale sessions)
        await self.tg_app.initialize()
        await self.tg_app.start()
        for attempt in range(5):
            try:
                await self.tg_app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                break
            except Exception as e:
                if "Conflict" in str(e) and attempt < 4:
                    log.warning("Polling conflict (attempt %d/5), retrying in 5s...", attempt + 1)
                    await asyncio.sleep(5)
                else:
                    raise
        log.info("Bot started. Listening for %d chat_id only.", config.MY_CHAT_ID)

        # wait until SIGINT/SIGTERM
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                # Windows / restricted env
                pass
        await stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        log.info("Shutting down...")
        self.ws.stop()
        self._stop_flush.set()
        if self._flush_task:
            try:
                await asyncio.wait_for(self._flush_task, timeout=3)
            except asyncio.TimeoutError:
                self._flush_task.cancel()
        if self._ws_task:
            try:
                await asyncio.wait_for(self._ws_task, timeout=5)
            except asyncio.TimeoutError:
                self._ws_task.cancel()
        if self.tg_app:
            try:
                await self.tg_app.updater.stop()
            except Exception:
                pass
            await self.tg_app.stop()
            await self.tg_app.shutdown()
        log.info("Bye.")


async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Telegram handler error", exc_info=ctx.error)


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------

def _validate_config() -> None:
    if config.TELEGRAM_TOKEN in ("", "YOUR_TOKEN"):
        raise SystemExit(
            "TELEGRAM_TOKEN не задан. Положите его в .env или переменные окружения."
        )
    if not config.MY_CHAT_ID:
        raise SystemExit(
            "MY_CHAT_ID не задан. Узнайте свой chat_id у @userinfobot и пропишите его."
        )


def main() -> None:
    setup_logging()
    _validate_config()
    bot = Bot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

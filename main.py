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
from bot.users import UserService
from database.storage import Order, Position, Storage, User
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
        self.users = UserService(self.storage)

        # per-user anomaly detectors (each user watches their own whale set)
        self.detectors: dict[int, AnomalyDetector] = {}

        # routing: address -> {chat_id: label}
        self.subscribers: dict[str, dict[int, str]] = {}
        # (chat_id, address) -> label
        self.labels: dict[tuple[int, str], str] = {}

        # Recent fills cache for exact PnL: {wallet: {coin: closed_pnl}}
        self._fill_pnl: dict[str, dict[str, float]] = {}

        # Fill aggregation: {(chat_id, wallet, coin, side): {count, ...}}
        self._fill_agg: dict[tuple[int, str, str, str], dict] = {}

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

    def _detector(self, chat_id: int) -> AnomalyDetector:
        det = self.detectors.get(chat_id)
        if det is None:
            det = AnomalyDetector(
                window_sec=config.ANOMALY_TIME_WINDOW,
                min_wallets=config.ANOMALY_MIN_WALLETS,
            )
            self.detectors[chat_id] = det
        return det

    def _user_labels(self, chat_id: int) -> dict[str, str]:
        return {addr: lbl for (cid, addr), lbl in self.labels.items()
                if cid == chat_id}

    # ------------------------------------------------------------------
    #  Notifications back to users
    # ------------------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> None:
        if not self.tg_app or not chat_id:
            log.info("[notify:%s] %s", chat_id, text.replace("\n", " | "))
            return
        async with self._send_semaphore:
            try:
                await self.tg_app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.warning("Failed to send tg message to %s: %s", chat_id, e)
            await asyncio.sleep(0.05)

    async def _subscribers_of(self, wallet: str) -> list[tuple[User, str]]:
        """(user, label) pairs subscribed to the wallet, with settings."""
        result = []
        for chat_id, label in (self.subscribers.get(wallet) or {}).items():
            user = await self.users.get(chat_id)
            if user:
                result.append((user, label or short_addr(wallet)))
        return result

    # ------------------------------------------------------------------
    #  WebSocket -> Telegram pipeline
    # ------------------------------------------------------------------

    async def _on_position_event(self, ev: PositionEvent) -> None:
        wallet = ev.wallet.lower()
        subs = await self._subscribers_of(wallet)
        if not subs:
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

            for user, label in subs:
                if user.min_position_usd and ev.notional < user.min_position_usd:
                    continue
                await self._send(user.chat_id,
                                 format_position_open(user.lang, ev, label))
                hit = self._detector(user.chat_id).record_open(
                    wallet=wallet, label=label, coin=ev.coin,
                    side=ev.side, notional=ev.notional,
                )
                if hit:
                    await self._send(
                        user.chat_id,
                        format_anomaly(user.lang, hit,
                                       self._user_labels(user.chat_id)),
                    )

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

            for user, label in subs:
                if user.min_position_usd and ev.notional < user.min_position_usd:
                    continue
                await self._send(user.chat_id,
                                 format_position_close(user.lang, ev, label))

        elif ev.kind == "scale":
            prev_size = ev.close_price or ev.size  # overloaded in diff
            prev_notional = ev.pnl or ev.notional  # overloaded in diff
            delta = abs(ev.notional - prev_notional)
            await self.storage.add_history(
                wallet, "scale", ev.coin, ev.side,
                {"size": ev.size, "notional": ev.notional,
                 "entry": ev.entry_price},
            )
            for user, label in subs:
                if user.min_position_usd and ev.notional < user.min_position_usd:
                    continue
                # For scale events also require the *change* to clear the
                # threshold — otherwise a $37K position growing by $400
                # would spam the chat.
                if user.min_position_usd and delta < user.min_position_usd:
                    continue
                await self._send(
                    user.chat_id,
                    format_position_scaled(user.lang, ev, label,
                                           prev_size, prev_notional),
                )

    async def _on_fill_event(self, ev: FillEvent) -> None:
        wallet = ev.wallet.lower()
        if ev.closed_pnl != 0:
            wallet_fills = self._fill_pnl.setdefault(wallet, {})
            wallet_fills[ev.coin] = wallet_fills.get(ev.coin, 0) + ev.closed_pnl

        subs = await self._subscribers_of(wallet)
        if not subs:
            return

        notional = ev.size * ev.price
        now = int(time.time())
        for user, label in subs:
            # Aggregation is keyed by (user, wallet, coin, side) so BUY-into-
            # LONG and SELL-out-of-LONG don't share a buffer, and each user
            # accumulates toward their own threshold.
            key = (user.chat_id, wallet, ev.coin, ev.side)
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

            if agg["total_notional"] >= user.fill_agg_threshold:
                self._attach_position_avg(agg)
                await self._send(
                    user.chat_id,
                    format_fills_aggregated(user.lang, agg, label))
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
            stale: list[tuple[int, str, str, str]] = []
            for k, a in self._fill_agg.items():
                if now - a["last_ts"] <= config.FILL_AGG_FLUSH_SEC:
                    continue
                user = await self.users.get(k[0])
                if user and a["total_notional"] >= user.fill_agg_threshold:
                    stale.append(k)
            for k in stale:
                agg = self._fill_agg.pop(k, None)
                if not agg:
                    continue
                self._attach_position_avg(agg)
                chat_id, wallet = k[0], k[1]
                user = await self.users.get(chat_id)
                if not user:
                    continue
                label = (self.labels.get((chat_id, wallet))
                         or short_addr(wallet))
                try:
                    await self._send(
                        chat_id,
                        format_fills_aggregated(user.lang, agg, label))
                except Exception:
                    log.exception("flush send failed")

    async def _on_order_event(self, ev: OrderEvent) -> None:
        wallet = ev.wallet.lower()
        if wallet not in self.subscribers:
            return

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
    #  WS subscription bridge for handlers (refcounted per address)
    # ------------------------------------------------------------------

    async def _subscribe_active(self, chat_id: int, addr: str,
                                label: str) -> None:
        addr = addr.lower()
        first = addr not in self.subscribers
        self.subscribers.setdefault(addr, {})[chat_id] = label
        self.labels[(chat_id, addr)] = label
        if first:
            await self.ws.add_wallet(addr, label)

    async def _unsubscribe(self, chat_id: int, addr: str) -> None:
        addr = addr.lower()
        subs = self.subscribers.get(addr)
        if subs:
            subs.pop(chat_id, None)
            if not subs:
                del self.subscribers[addr]
                await self.ws.remove_wallet(addr)
        self.labels.pop((chat_id, addr), None)
        # drop this user's pending aggregation buffers for the address
        for k in [k for k in self._fill_agg
                  if k[0] == chat_id and k[1] == addr]:
            del self._fill_agg[k]

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        await self.storage.init(legacy_owner_chat_id=config.ADMIN_CHAT_ID)

        # restore active (user, wallet) pairs from DB
        for w in await self.storage.list_active_subscriptions():
            first = w.address not in self.subscribers
            self.subscribers.setdefault(w.address, {})[w.chat_id] = w.label
            self.labels[(w.chat_id, w.address)] = w.label
            if first:
                await self.ws.add_wallet(w.address, w.label)

        # build telegram app
        self.tg_app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
        h = Handlers(
            storage=self.storage,
            users=self.users,
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
        app.add_handler(CommandHandler("settings", h.settings))
        app.add_handler(CommandHandler("admin", h.admin))
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
        log.info("Bot started (multi-user). Tracking %d addresses.",
                 len(self.subscribers))

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
    if not config.ADMIN_CHAT_ID:
        raise SystemExit(
            "ADMIN_CHAT_ID не задан. Узнайте свой chat_id у @userinfobot и "
            "пропишите его в .env (это админ бота и владелец кошельков при "
            "миграции со старой версии)."
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

"""Hyperliquid WebSocket client — single connection, many wallets, auto-reconnect."""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from typing import Awaitable, Callable, Optional

import certifi
import websockets
from websockets.exceptions import ConnectionClosed

from .parser import (
    AccountState,
    FillEvent,
    OrderEvent,
    PositionEvent,
    PositionSnapshot,
    diff_positions,
    parse_account_state,
    parse_order_updates,
    parse_user_fills,
    parse_web_data2,
)

log = logging.getLogger("hl.ws")


PositionCallback = Callable[[PositionEvent], Awaitable[None]]
OrderCallback = Callable[[OrderEvent], Awaitable[None]]
FillCallback = Callable[[FillEvent], Awaitable[None]]


class HyperliquidWS:
    """Single WebSocket multiplexed across many tracked wallets."""

    def __init__(
        self,
        url: str,
        on_position: PositionCallback,
        on_order: OrderCallback,
        on_fill: FillCallback | None = None,
        ping_interval: int = 30,
        reconnect_delay: int = 5,
        max_reconnect_delay: int = 60,
    ):
        self.url = url
        self.on_position = on_position
        self.on_order = on_order
        self.on_fill = on_fill
        self.ping_interval = ping_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._wallets: set[str] = set()
        self._labels: dict[str, str] = {}

        # snapshot caches per wallet
        self._pos_state: dict[str, dict[str, PositionSnapshot]] = {}
        self._open_times: dict[str, dict[str, int]] = {}
        # known oid set per wallet (for cancel detection through webData2)
        self._known_oids: dict[str, set[int]] = {}
        # full open orders snapshot per wallet (raw dicts from webData2)
        self._open_orders_state: dict[str, list[dict]] = {}
        # account-level state per wallet (balance, margin)
        self._account_state: dict[str, AccountState] = {}
        self._mids: dict[str, float] = {}

        # Priming: first snapshot per wallet is saved silently (no diff/events)
        self._priming: set[str] = set()

        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._connected = asyncio.Event()

    # ---------- public API ----------

    async def add_wallet(self, address: str, label: str = "") -> None:
        addr = address.lower()
        self._wallets.add(addr)
        self._labels[addr] = label or addr
        self._pos_state.setdefault(addr, {})
        self._open_times.setdefault(addr, {})
        self._known_oids.setdefault(addr, set())
        self._priming.add(addr)
        if self._connected.is_set():
            await self._subscribe(addr)

    async def remove_wallet(self, address: str) -> None:
        addr = address.lower()
        self._wallets.discard(addr)
        self._labels.pop(addr, None)
        self._pos_state.pop(addr, None)
        self._open_times.pop(addr, None)
        self._known_oids.pop(addr, None)
        self._open_orders_state.pop(addr, None)
        self._account_state.pop(addr, None)
        if self._connected.is_set():
            await self._unsubscribe(addr)

    def stop(self) -> None:
        self._stop.set()

    # ---------- main loop ----------

    async def run(self) -> None:
        delay = self.reconnect_delay
        while not self._stop.is_set():
            try:
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
                async with websockets.connect(
                    self.url,
                    ssl=ssl_ctx,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_interval,
                    close_timeout=5,
                    max_size=20 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    log.info("WebSocket connected: %s", self.url)
                    delay = self.reconnect_delay  # reset backoff

                    # (re)subscribe every wallet
                    for addr in list(self._wallets):
                        await self._subscribe(addr)

                    # HL drops connections idle for ~60s; the protocol-level
                    # WS ping doesn't count — an app-level ping is required.
                    ping_task = asyncio.create_task(self._app_ping_loop())
                    try:
                        await self._read_loop(ws)
                    finally:
                        ping_task.cancel()
            except (ConnectionClosed, OSError) as e:
                log.warning("WebSocket dropped: %s", e)
            except Exception:
                log.exception("WebSocket error")
            finally:
                self._connected.clear()
                self._ws = None

            if self._stop.is_set():
                break
            log.info("Reconnecting in %ds...", delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self.max_reconnect_delay)

    # ---------- internals ----------

    # webData2 was removed from the HL API (mid-2026); positions and open
    # orders now come from the dedicated clearinghouseState / openOrders
    # channels, so a wallet costs 4 subscriptions.
    SUB_TYPES = ("clearinghouseState", "openOrders", "orderUpdates",
                 "userFills")

    async def _subscribe(self, addr: str) -> None:
        for sub_type in self.SUB_TYPES:
            await self._send({"method": "subscribe",
                              "subscription": {"type": sub_type, "user": addr}})

    async def _unsubscribe(self, addr: str) -> None:
        for sub_type in self.SUB_TYPES:
            await self._send({"method": "unsubscribe",
                              "subscription": {"type": sub_type, "user": addr}})

    async def _app_ping_loop(self) -> None:
        while True:
            await asyncio.sleep(45)
            await self._send({"method": "ping"})

    async def _send(self, payload: dict) -> None:
        async with self._send_lock:
            if self._ws is None:
                return
            try:
                await self._ws.send(json.dumps(payload))
            except Exception as e:
                log.warning("send failed: %s", e)

    async def _read_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            try:
                await self._dispatch(msg)
            except Exception:
                log.exception("dispatch error: %s", str(msg)[:300])

    async def _dispatch(self, msg: dict) -> None:
        channel = msg.get("channel")
        data = msg.get("data") or {}

        if channel == "clearinghouseState":
            user = (data.get("user") or "").lower()
            if user not in self._wallets:
                return
            await self._handle_clearinghouse_state(user, data)

        elif channel == "openOrders":
            user = (data.get("user") or "").lower()
            if user not in self._wallets:
                return
            orders = data.get("orders") or []
            self._open_orders_state[user] = orders
            ko = self._known_oids.setdefault(user, set())
            for oo in orders:
                oid = int(oo.get("oid") or 0)
                if oid:
                    ko.add(oid)

        elif channel == "orderUpdates":
            updates = data if isinstance(data, list) else data.get("orders", [])
            user = self._resolve_order_user(msg, updates)
            if not user or user not in self._wallets:
                return

            if user in self._priming:
                ko = self._known_oids.setdefault(user, set())
                for upd in updates:
                    oid = int((upd.get("order") or {}).get("oid") or 0)
                    if oid:
                        ko.add(oid)
                return

            events = parse_order_updates(user, updates, self._mids)
            ko = self._known_oids.setdefault(user, set())
            for e in events:
                if e.kind == "placed":
                    ko.add(e.oid)
                else:
                    ko.discard(e.oid)
            for e in events:
                await self.on_order(e)

        elif channel == "userFills":
            if isinstance(data, dict) and data.get("isSnapshot"):
                return  # historical snapshot on subscribe — not live fills
            user = (data.get("user") or msg.get("user") or "").lower()
            fills_list = data.get("fills") if isinstance(data, dict) else data
            if not isinstance(fills_list, list):
                fills_list = []
            if not user:
                for f in fills_list:
                    u = (f.get("user") or "").lower()
                    if u and u in self._wallets:
                        user = u
                        break
            if not user or user not in self._wallets:
                return
            if user in self._priming:
                return
            if self.on_fill:
                events = parse_user_fills(user, fills_list)
                for ev in events:
                    try:
                        await self.on_fill(ev)
                    except Exception:
                        log.exception("on_fill handler failed")

        elif channel == "subscriptionResponse":
            log.debug("subscribed: %s", data)

        elif channel == "pong":
            pass

        elif channel == "error":
            log.warning("hyperliquid error: %s", data)

    def _resolve_order_user(self, msg: dict, updates: list[dict]) -> str:
        """Extract user from orderUpdates message — try multiple locations."""
        user = (msg.get("user") or "").lower()
        if user and user in self._wallets:
            return user
        for upd in updates:
            u = (upd.get("user") or
                 (upd.get("order") or {}).get("user") or "").lower()
            if u and u in self._wallets:
                return u
        return self._guess_user_for_orders(updates)

    def _guess_user_for_orders(self, updates: list[dict]) -> str:
        """Fallback: when orderUpdates omits user, find by oid match."""
        for upd in updates:
            oid = int((upd.get("order") or {}).get("oid") or 0)
            for addr, oids in self._known_oids.items():
                if oid in oids:
                    return addr
        if len(self._wallets) == 1:
            return next(iter(self._wallets))
        return ""

    async def _handle_clearinghouse_state(self, user: str,
                                          data: dict) -> None:
        # channel payload: {"dex","user","clearinghouseState":{...}} — the
        # inner object matches what webData2 used to embed, so the parser
        # is reused as-is (openOrders/mids just come out empty).
        positions, _, _ = parse_web_data2(data)
        self._account_state[user] = parse_account_state(data)

        now = int(time.time())

        if user in self._priming:
            self._priming.discard(user)
            self._pos_state[user] = positions
            open_times = self._open_times.setdefault(user, {})
            for coin in positions:
                open_times.setdefault(coin, now)
            log.info("Priming snapshot for %s: %d positions",
                     user, len(positions))
            return

        prev = self._pos_state.get(user, {})
        open_times = self._open_times.setdefault(user, {})

        events = diff_positions(user, prev, positions, open_times)

        for coin in positions:
            open_times.setdefault(coin, now)
        for coin in list(open_times):
            if coin not in positions:
                open_times.pop(coin, None)

        self._pos_state[user] = positions

        for ev in events:
            try:
                await self.on_position(ev)
            except Exception:
                log.exception("on_position handler failed")

    def get_unrealized_pnl(self, wallet: str) -> dict[str, float]:
        """Return {coin: unrealized_pnl} for a wallet from latest snapshot."""
        return {
            coin: snap.unrealized_pnl
            for coin, snap in self._pos_state.get(wallet.lower(), {}).items()
        }

    def get_positions(self, wallet: str) -> dict[str, PositionSnapshot]:
        """Return live position snapshot for a wallet ({coin: PositionSnapshot})."""
        return dict(self._pos_state.get(wallet.lower(), {}))

    def get_open_orders(self, wallet: str) -> list[dict]:
        """Return live open orders (raw dicts) for a wallet."""
        return list(self._open_orders_state.get(wallet.lower(), []))

    def get_account_state(self, wallet: str) -> AccountState:
        """Return live account state (balance, margin) for a wallet."""
        return self._account_state.get(wallet.lower()) or AccountState()

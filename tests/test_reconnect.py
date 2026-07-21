"""Test: HyperliquidWS auto-reconnects and re-subscribes after connection drop."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from hl_monitor.client import HyperliquidWS
from hl_monitor.parser import PositionEvent

pytestmark = pytest.mark.asyncio


class FakeWS:
    """Simulates a websockets connection that drops after delivering messages."""

    def __init__(self, messages: list[str]):
        self._messages = messages
        self.sent: list[str] = []
        self._idx = 0

    async def send(self, data: str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._messages):
            raise ConnectionClosed(None, None)
        msg = self._messages[self._idx]
        self._idx += 1
        return msg


async def test_reconnect_resubscribes():
    """After a connection drop, WS should reconnect and re-subscribe all wallets."""
    connect_count = 0
    all_ws: list[FakeWS] = []

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        ws = FakeWS([])
        all_ws.append(ws)
        yield ws

    on_pos = AsyncMock()
    on_ord = AsyncMock()

    client = HyperliquidWS(
        url="wss://fake",
        on_position=on_pos,
        on_order=on_ord,
        reconnect_delay=1,
        max_reconnect_delay=1,
    )

    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    await client.add_wallet(wallet_a, "test1")
    await client.add_wallet(wallet_b, "test2")

    async def run_then_stop():
        await asyncio.sleep(2.5)
        client.stop()

    with patch("hl_monitor.client.websockets.connect", side_effect=fake_connect):
        await asyncio.gather(client.run(), run_then_stop())

    assert connect_count >= 2, f"Expected at least 2 connects, got {connect_count}"

    for ws in all_ws:
        parsed = [json.loads(s) for s in ws.sent]
        sub_users = set()
        sub_types = set()
        for p in parsed:
            if p.get("method") == "subscribe":
                sub = p["subscription"]
                sub_types.add(sub["type"])
                if "user" in sub:  # allMids is global — no user field
                    sub_users.add(sub["user"])

        assert "clearinghouseState" in sub_types
        assert "openOrders" in sub_types
        assert "orderUpdates" in sub_types
        assert "userFills" in sub_types
        assert "allMids" in sub_types  # global, re-armed on every reconnect
        assert len(sub_users) == 2


async def test_priming_suppresses_events():
    """First clearinghouseState snapshot should not emit position events."""
    positions_received: list[PositionEvent] = []

    async def on_pos(ev):
        positions_received.append(ev)

    async def on_ord(ev):
        pass

    wallet = "0x" + "a" * 40

    first_snapshot = json.dumps({
        "channel": "clearinghouseState",
        "data": {
            "dex": "",
            "user": wallet,
            "clearinghouseState": {
                "assetPositions": [
                    {"position": {"coin": "BTC", "szi": "1.0", "entryPx": "65000",
                                  "positionValue": "65000", "unrealizedPnl": "500",
                                  "leverage": {"value": "10"}}},
                ]
            },
        }
    })

    second_snapshot = json.dumps({
        "channel": "clearinghouseState",
        "data": {
            "dex": "",
            "user": wallet,
            "clearinghouseState": {
                "assetPositions": [
                    {"position": {"coin": "BTC", "szi": "1.0", "entryPx": "65000",
                                  "positionValue": "65000", "unrealizedPnl": "600",
                                  "leverage": {"value": "10"}}},
                    {"position": {"coin": "ETH", "szi": "-2.0", "entryPx": "3200",
                                  "positionValue": "-6400", "unrealizedPnl": "-30",
                                  "leverage": {"value": "5"}}},
                ]
            },
        }
    })

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield FakeWS([first_snapshot, second_snapshot])

    client = HyperliquidWS(
        url="wss://fake",
        on_position=on_pos,
        on_order=on_ord,
    )
    await client.add_wallet(wallet, "test")

    async def run_then_stop():
        await asyncio.sleep(0.2)
        client.stop()

    with patch("hl_monitor.client.websockets.connect", side_effect=fake_connect):
        await asyncio.gather(client.run(), run_then_stop())

    assert len(positions_received) == 1, (
        f"Expected 1 event (ETH open), got {len(positions_received)}: "
        f"{[(e.kind, e.coin) for e in positions_received]}"
    )
    assert positions_received[0].kind == "open"
    assert positions_received[0].coin == "ETH"


async def test_all_mids_feeds_order_current_price():
    """allMids should populate the mid cache and reach OrderEvent.current_price."""
    orders_received: list = []

    async def on_pos(ev):
        pass

    async def on_ord(ev):
        orders_received.append(ev)

    wallet = "0x" + "a" * 40

    # Clears priming, so the orderUpdates below is treated as live.
    prime = json.dumps({
        "channel": "clearinghouseState",
        "data": {"dex": "", "user": wallet,
                 "clearinghouseState": {"assetPositions": []}},
    })
    mids = json.dumps({
        "channel": "allMids",
        "data": {"mids": {"BTC": "65300.0", "ETH": "3180.0"}},
    })
    order = json.dumps({
        "channel": "orderUpdates",
        "user": wallet,
        "data": [{"order": {"coin": "BTC", "side": "B", "limitPx": "64000",
                            "sz": "1.0", "oid": 777}, "status": "open"}],
    })

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        yield FakeWS([prime, mids, order])

    client = HyperliquidWS(url="wss://fake", on_position=on_pos, on_order=on_ord)
    await client.add_wallet(wallet, "test")

    async def run_then_stop():
        await asyncio.sleep(0.2)
        client.stop()

    with patch("hl_monitor.client.websockets.connect", side_effect=fake_connect):
        await asyncio.gather(client.run(), run_then_stop())

    assert client._mids["BTC"] == 65300.0
    assert len(orders_received) == 1
    assert orders_received[0].current_price == 65300.0

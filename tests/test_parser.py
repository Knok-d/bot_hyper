"""Tests for hl_monitor.parser — webData2 parsing, order parsing, diff logic."""
from __future__ import annotations

import time

from hl_monitor.parser import (
    PositionSnapshot,
    diff_positions,
    parse_order_updates,
    parse_user_fills,
    parse_web_data2,
)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

WALLET = "0xaabbccdd00112233445566778899aabbccddeeff"

WEB_DATA2_PAYLOAD = {
    "clearinghouseState": {
        "assetPositions": [
            {
                "position": {
                    "coin": "BTC",
                    "szi": "0.5",
                    "entryPx": "65000",
                    "positionValue": "32500",
                    "unrealizedPnl": "150.0",
                    "leverage": {"value": "10"},
                }
            },
            {
                "position": {
                    "coin": "ETH",
                    "szi": "-2.0",
                    "entryPx": "3200",
                    "positionValue": "-6400",
                    "unrealizedPnl": "-30.0",
                    "leverage": {"value": "5"},
                }
            },
            {
                "position": {
                    "coin": "DOGE",
                    "szi": "0",
                    "entryPx": "0.1",
                    "positionValue": "0",
                    "unrealizedPnl": "0",
                    "leverage": {"value": "1"},
                }
            },
        ]
    },
    "openOrders": [
        {"oid": 111, "coin": "BTC", "side": "B", "limitPx": "60000", "sz": "0.1"},
    ],
    "allMids": {"BTC": "65300", "ETH": "3180"},
}


# ---------------------------------------------------------------------------
#  webData2 parsing
# ---------------------------------------------------------------------------

def test_parse_web_data2_positions():
    positions, orders, mids = parse_web_data2(WEB_DATA2_PAYLOAD)

    assert "BTC" in positions
    assert "ETH" in positions
    assert "DOGE" not in positions  # szi == 0 → filtered

    btc = positions["BTC"]
    assert btc.side == "LONG"
    assert btc.size == 0.5
    assert btc.entry_price == 65000.0
    assert btc.notional == 32500.0
    assert btc.leverage == 10.0
    assert btc.unrealized_pnl == 150.0

    eth = positions["ETH"]
    assert eth.side == "SHORT"  # negative szi → SHORT
    assert eth.size == 2.0
    assert eth.unrealized_pnl == -30.0


def test_parse_web_data2_mids():
    _, _, mids = parse_web_data2(WEB_DATA2_PAYLOAD)
    assert mids["BTC"] == 65300.0
    assert mids["ETH"] == 3180.0


def test_parse_web_data2_open_orders():
    _, orders, _ = parse_web_data2(WEB_DATA2_PAYLOAD)
    assert len(orders) == 1
    assert orders[0]["oid"] == 111


def test_parse_web_data2_empty():
    positions, orders, mids = parse_web_data2({})
    assert positions == {}
    assert orders == []
    assert mids == {}


# ---------------------------------------------------------------------------
#  diff_positions — open / close / scale detection
# ---------------------------------------------------------------------------

def _snap(coin, side, size=1.0, entry=100.0, notional=100.0, lev=1.0, upnl=0.0):
    return PositionSnapshot(
        coin=coin, side=side, size=size,
        entry_price=entry, notional=notional,
        leverage=lev, unrealized_pnl=upnl,
    )


def test_diff_open():
    prev = {}
    curr = {"BTC": _snap("BTC", "LONG")}
    events = diff_positions(WALLET, prev, curr, {})
    assert len(events) == 1
    assert events[0].kind == "open"
    assert events[0].coin == "BTC"
    assert events[0].side == "LONG"


def test_diff_close():
    prev = {"BTC": _snap("BTC", "LONG", upnl=50)}
    curr = {}
    open_times = {"BTC": int(time.time()) - 3600}
    events = diff_positions(WALLET, prev, curr, open_times)
    assert len(events) == 1
    assert events[0].kind == "close"
    assert events[0].pnl == 50.0
    assert events[0].holding_seconds is not None
    assert events[0].holding_seconds >= 3599


def test_diff_side_flip():
    prev = {"BTC": _snap("BTC", "LONG")}
    curr = {"BTC": _snap("BTC", "SHORT")}
    events = diff_positions(WALLET, prev, curr, {"BTC": int(time.time()) - 60})
    assert len(events) == 2
    assert events[0].kind == "close"
    assert events[0].side == "LONG"
    assert events[1].kind == "open"
    assert events[1].side == "SHORT"


def test_diff_scale():
    prev = {"BTC": _snap("BTC", "LONG", size=1.0, notional=100)}
    curr = {"BTC": _snap("BTC", "LONG", size=2.0, notional=200)}
    events = diff_positions(WALLET, prev, curr, {})
    assert len(events) == 1
    assert events[0].kind == "scale"
    assert events[0].size == 2.0


def test_diff_no_change():
    snap = _snap("BTC", "LONG", size=1.0)
    events = diff_positions(WALLET, {"BTC": snap}, {"BTC": snap}, {})
    assert events == []


# ---------------------------------------------------------------------------
#  orderUpdates parsing
# ---------------------------------------------------------------------------

ORDER_UPDATES = [
    {
        "order": {"coin": "BTC", "side": "B", "limitPx": "60000",
                  "sz": "0.1", "oid": 42},
        "status": "open",
    },
    {
        "order": {"coin": "ETH", "side": "A", "limitPx": "3500",
                  "sz": "1.0", "oid": 43},
        "status": "filled",
    },
    {
        "order": {"coin": "SOL", "side": "B", "limitPx": "150",
                  "sz": "10", "oid": 44},
        "status": "canceled",
    },
    {
        "order": {"coin": "ARB", "side": "A", "limitPx": "1.5",
                  "sz": "100", "oid": 45},
        "status": "marginCanceled",
    },
    {
        "order": {"coin": "X", "side": "B", "limitPx": "1",
                  "sz": "1", "oid": 46},
        "status": "unknownStatus",
    },
]


def test_parse_order_placed():
    events = parse_order_updates(WALLET, ORDER_UPDATES[:1], {"BTC": 65000})
    assert len(events) == 1
    e = events[0]
    assert e.kind == "placed"
    assert e.type == "LIMIT BUY"
    assert e.oid == 42
    assert e.price == 60000.0
    assert e.current_price == 65000.0


def test_parse_order_filled():
    events = parse_order_updates(WALLET, ORDER_UPDATES[1:2])
    assert events[0].kind == "filled"
    assert events[0].type == "LIMIT SELL"  # side "A" → SELL


def test_parse_order_canceled_variants():
    events = parse_order_updates(WALLET, ORDER_UPDATES[2:4])
    assert len(events) == 2
    assert all(e.kind == "canceled" for e in events)


def test_parse_order_unknown_status_skipped():
    events = parse_order_updates(WALLET, ORDER_UPDATES[4:5])
    assert events == []


def test_parse_order_all_statuses():
    events = parse_order_updates(WALLET, ORDER_UPDATES)
    kinds = [e.kind for e in events]
    assert kinds == ["placed", "filled", "canceled", "canceled"]


# ---------------------------------------------------------------------------
#  userFills parsing
# ---------------------------------------------------------------------------

FILLS = [
    {"coin": "BTC", "side": "B", "sz": "0.5", "px": "65100",
     "closedPnl": "0", "fee": "1.5", "time": str(int(time.time() * 1000)), "oid": 100},
    {"coin": "ETH", "side": "A", "sz": "2.0", "px": "3300",
     "closedPnl": "200", "fee": "2.0", "time": str(int(time.time() * 1000)), "oid": 101},
]


def test_parse_user_fills():
    events = parse_user_fills(WALLET, FILLS)
    assert len(events) == 2
    assert events[0].side == "BUY"
    assert events[0].coin == "BTC"
    assert events[0].closed_pnl == 0.0
    assert events[1].side == "SELL"
    assert events[1].closed_pnl == 200.0

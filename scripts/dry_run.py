#!/usr/bin/env python3
"""Smoke-test: fake WS events → formatter output, no real Telegram or WebSocket.

Runs the full pipeline (parser → Bot._on_position_event / _on_order_event)
with pre-baked events and prints the formatted messages that *would* go to
Telegram.

Usage:
    python scripts/dry_run.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hl_monitor.parser import (
    OrderEvent,
    PositionEvent,
    parse_order_updates,
    parse_user_fills,
    parse_web_data2,
)
from bot.formatter import (
    format_anomaly,
    format_order_canceled,
    format_order_filled,
    format_order_placed,
    format_position_close,
    format_position_open,
    format_position_scaled,
)
from hl_monitor.detector import AnomalyDetector

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("dry_run")

WALLET = "0xaabbccdd00112233445566778899aabbccddeeff"
LABEL = "TestWhale"
SEPARATOR = "─" * 60

collected: list[str] = []


def emit(title: str, msg: str) -> None:
    collected.append(title)
    print(f"\n{SEPARATOR}")
    print(f"  [{title}]")
    print(SEPARATOR)
    print(msg)
    print()


async def main() -> None:
    # 1) Open BTC LONG
    ev_open = PositionEvent(
        kind="open", wallet=WALLET, coin="BTC", side="LONG",
        size=0.5, entry_price=65000, notional=32500, leverage=10,
    )
    emit("1. POSITION OPEN (BTC LONG)", format_position_open(ev_open, LABEL))

    # 2) Close BTC LONG with PnL
    ev_close = PositionEvent(
        kind="close", wallet=WALLET, coin="BTC", side="LONG",
        size=0.5, entry_price=65000, notional=32500, leverage=10,
        close_price=66500, pnl=750.0, holding_seconds=7200,
    )
    emit("2. POSITION CLOSE (BTC LONG, +$750)", format_position_close(ev_close, LABEL))

    # 3) Scale position — size change
    ev_scale = PositionEvent(
        kind="scale", wallet=WALLET, coin="ETH", side="SHORT",
        size=4.0, entry_price=3200, notional=12800, leverage=5,
        close_price=2.0, pnl=6400,  # prev_size, prev_notional overloaded
    )
    emit("3. POSITION SCALED (ETH SHORT 2→4)", format_position_scaled(
        ev_scale, LABEL, prev_size=2.0, prev_notional=6400))

    # 4) Order placed
    ev_order = OrderEvent(
        kind="placed", wallet=WALLET, oid=42, coin="SOL",
        type="LIMIT BUY", size=100, notional=15000, price=150,
        current_price=155,
    )
    emit("4. ORDER PLACED (SOL LIMIT BUY)", format_order_placed(ev_order, LABEL))

    # 5) Order canceled
    ev_cancel = OrderEvent(
        kind="canceled", wallet=WALLET, oid=42, coin="SOL",
        type="LIMIT BUY", size=100, notional=15000, price=150,
    )
    emit("5. ORDER CANCELED (SOL)", format_order_canceled(ev_cancel, LABEL))

    # 6) Order filled
    ev_fill_ord = OrderEvent(
        kind="filled", wallet=WALLET, oid=43, coin="ARB",
        type="LIMIT SELL", size=5000, notional=7500, price=1.50,
    )
    emit("6. ORDER FILLED (ARB)", format_order_filled(ev_fill_ord, LABEL))

    # 7) Anomaly detection
    detector = AnomalyDetector(window_sec=300, min_wallets=2)
    detector.record_open(WALLET, LABEL, "DOGE", "LONG", 50000)
    wallet_b = "0x1111222233334444555566667777888899990000"
    hit = detector.record_open(wallet_b, "Whale2", "DOGE", "LONG", 30000)
    if hit:
        labels = {WALLET: LABEL, wallet_b: "Whale2"}
        emit("7. ANOMALY DETECTED (DOGE LONG x2)", format_anomaly(hit, labels))

    # 8) webData2 full-cycle parse test
    payload = {
        "clearinghouseState": {
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "1.0", "entryPx": "67000",
                              "positionValue": "67000", "unrealizedPnl": "1200",
                              "leverage": {"value": "20"}}},
            ]
        },
        "openOrders": [
            {"oid": 100, "coin": "BTC", "side": "A", "limitPx": "70000", "sz": "0.5"},
        ],
        "allMids": {"BTC": "68200"},
    }
    positions, orders, mids = parse_web_data2(payload)
    log.info(f"  webData2 parse: {len(positions)} positions, "
             f"{len(orders)} orders, mids={mids}")

    # 9) orderUpdates parse test
    order_msgs = [
        {"order": {"coin": "ETH", "side": "B", "limitPx": "3000",
                   "sz": "2", "oid": 200}, "status": "open"},
        {"order": {"coin": "ETH", "side": "B", "limitPx": "3000",
                   "sz": "2", "oid": 200}, "status": "filled"},
    ]
    events = parse_order_updates(WALLET, order_msgs, mids)
    log.info(f"  orderUpdates parse: {[e.kind for e in events]}")

    # 10) userFills parse test
    fills_raw = [
        {"coin": "BTC", "side": "A", "sz": "0.5", "px": "68500",
         "closedPnl": "750", "fee": "3.42",
         "time": str(int(time.time() * 1000)), "oid": 300},
    ]
    fill_events = parse_user_fills(WALLET, fills_raw)
    log.info(f"  userFills parse: closedPnl={fill_events[0].closed_pnl}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  DRY RUN COMPLETE — {len(collected)} message types generated:")
    for i, title in enumerate(collected, 1):
        print(f"    {i}. {title}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())

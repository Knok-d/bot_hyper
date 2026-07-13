"""Parsing helpers for Hyperliquid WebSocket payloads.

Hyperliquid sends snapshot-style updates via the ``webData2`` subscription
and incremental updates via ``orderUpdates``. This module turns raw JSON
into typed events that the bot understands.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
#  Data classes
# ---------------------------------------------------------------------------

@dataclass
class PositionSnapshot:
    """Current state of a single perp position, as reported by HL."""
    coin: str
    side: str            # 'LONG' / 'SHORT'
    size: float          # absolute coin amount
    entry_price: float
    notional: float      # USD
    leverage: float
    unrealized_pnl: float
    liquidation_price: float = 0.0   # 0.0 means "not at risk" (HL returns null)
    margin_used: float = 0.0


@dataclass
class PositionEvent:
    """Position open/close event detected by diffing snapshots."""
    kind: str            # 'open' / 'close'
    wallet: str
    coin: str
    side: str
    size: float
    entry_price: float
    notional: float
    leverage: float
    # close-only:
    close_price: Optional[float] = None
    pnl: Optional[float] = None
    holding_seconds: Optional[int] = None


@dataclass
class OrderEvent:
    """Order placed / canceled / filled event."""
    kind: str            # 'placed' / 'canceled' / 'filled'
    wallet: str
    oid: int
    coin: str
    type: str            # 'LIMIT BUY' / 'LIMIT SELL' / 'TRIGGER BUY' ...
    size: float
    notional: float
    price: float
    current_price: Optional[float] = None  # mid price snapshot, when known


@dataclass
class FillEvent:
    """A trade fill from userFills."""
    wallet: str
    coin: str
    side: str            # 'BUY' / 'SELL'
    size: float
    price: float
    closed_pnl: float
    fee: float
    timestamp: int
    oid: int


@dataclass
class AccountState:
    """Account-level snapshot from clearinghouseState."""
    account_value: float = 0.0      # total USD equity
    margin_used: float = 0.0
    withdrawable: float = 0.0


# ---------------------------------------------------------------------------
#  webData2 — snapshot of clearinghouseState + open orders + mids
# ---------------------------------------------------------------------------

def _f(value: Any, default: float = 0.0) -> float:
    """Tolerant float conversion."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_web_data2(payload: dict) -> tuple[
    dict[str, PositionSnapshot], list[dict], dict[str, float]
]:
    """Return (positions_by_coin, open_orders_raw, mid_prices)."""
    positions: dict[str, PositionSnapshot] = {}
    mids: dict[str, float] = {}

    ch = payload.get("clearinghouseState") or {}
    asset_positions = ch.get("assetPositions") or []
    for ap in asset_positions:
        pos = ap.get("position") or {}
        szi = _f(pos.get("szi"))
        if szi == 0:
            continue
        coin = pos.get("coin") or ""
        leverage_obj = pos.get("leverage") or {}
        positions[coin] = PositionSnapshot(
            coin=coin,
            side="LONG" if szi > 0 else "SHORT",
            size=abs(szi),
            entry_price=_f(pos.get("entryPx")),
            notional=abs(_f(pos.get("positionValue"))),
            leverage=_f(leverage_obj.get("value")) or 1.0,
            unrealized_pnl=_f(pos.get("unrealizedPnl")),
            liquidation_price=_f(pos.get("liquidationPx")),
            margin_used=_f(pos.get("marginUsed")),
        )

    open_orders = payload.get("openOrders") or []
    mids_payload = (
        payload.get("midPrices")
        or payload.get("allMids")
        or payload.get("mids")
        or {}
    )
    if isinstance(mids_payload, dict):
        for k, v in mids_payload.items():
            mids[k] = _f(v)

    return positions, open_orders, mids


def parse_account_state(payload: dict) -> AccountState:
    """Extract account-level balance from a webData2 payload."""
    ch = payload.get("clearinghouseState") or {}
    ms = ch.get("marginSummary") or ch.get("crossMarginSummary") or {}
    return AccountState(
        account_value=_f(ms.get("accountValue")),
        margin_used=_f(ms.get("totalMarginUsed")),
        withdrawable=_f(ch.get("withdrawable")),
    )


def parse_active_asset_data(payload: dict) -> Optional[PositionSnapshot]:
    """Single-asset snapshot from ``activeAssetData`` subscription."""
    coin = payload.get("coin")
    pos_raw = payload.get("position")
    if not coin or not pos_raw:
        return None
    szi = _f(pos_raw.get("szi"))
    if szi == 0:
        return None
    leverage_obj = pos_raw.get("leverage") or {}
    return PositionSnapshot(
        coin=coin,
        side="LONG" if szi > 0 else "SHORT",
        size=abs(szi),
        entry_price=_f(pos_raw.get("entryPx")),
        notional=abs(_f(pos_raw.get("positionValue"))),
        leverage=_f(leverage_obj.get("value")) or 1.0,
        unrealized_pnl=_f(pos_raw.get("unrealizedPnl")),
        liquidation_price=_f(pos_raw.get("liquidationPx")),
        margin_used=_f(pos_raw.get("marginUsed")),
    )


# ---------------------------------------------------------------------------
#  orderUpdates — incremental status events
# ---------------------------------------------------------------------------

def parse_order_updates(
    wallet: str, payload: Iterable[dict], mids: dict[str, float] | None = None,
) -> list[OrderEvent]:
    """Convert orderUpdates messages into OrderEvent list.

    Each message looks like::
        {"order": {"coin","side","limitPx","sz","oid","timestamp","origSz"},
         "status": "open"|"filled"|"canceled"|...,
         "statusTimestamp": int}
    """
    events: list[OrderEvent] = []
    mids = mids or {}
    for msg in payload:
        order = msg.get("order") or {}
        status = msg.get("status") or ""
        coin = order.get("coin") or ""
        side = order.get("side") or ""
        oid = int(order.get("oid") or 0)
        sz = _f(order.get("sz"))
        price = _f(order.get("limitPx"))
        notional = sz * price
        side_str = "BUY" if side.upper().startswith("B") else "SELL"
        # 'trigger' info isn't in this minimal payload — labeling as LIMIT.
        otype = f"LIMIT {side_str}"

        if status == "open":
            kind = "placed"
        elif status == "filled":
            kind = "filled"
        elif status in ("canceled", "marginCanceled", "rejected"):
            kind = "canceled"
        else:
            continue

        events.append(OrderEvent(
            kind=kind,
            wallet=wallet,
            oid=oid,
            coin=coin,
            type=otype,
            size=sz,
            notional=notional,
            price=price,
            current_price=mids.get(coin),
        ))
    return events


# ---------------------------------------------------------------------------
#  Snapshot diff — open / close detection
# ---------------------------------------------------------------------------

def diff_positions(
    wallet: str,
    prev: dict[str, PositionSnapshot],
    curr: dict[str, PositionSnapshot],
    open_times: dict[str, int],
) -> list[PositionEvent]:
    """Return open / close events between two snapshots.

    ``open_times`` is a dict {coin: opened_at_unix} maintained externally so
    that close events carry the holding duration.
    """
    events: list[PositionEvent] = []
    now = int(time.time())

    prev_coins = set(prev.keys())
    curr_coins = set(curr.keys())

    # OPENED — appears in curr, not in prev (or side flipped)
    for coin in curr_coins - prev_coins:
        c = curr[coin]
        events.append(PositionEvent(
            kind="open", wallet=wallet, coin=coin, side=c.side,
            size=c.size, entry_price=c.entry_price,
            notional=c.notional, leverage=c.leverage,
        ))

    # SAME COIN — side flip or scale
    for coin in prev_coins & curr_coins:
        p, c = prev[coin], curr[coin]
        if p.side != c.side:
            opened_at = open_times.get(coin, now)
            events.append(PositionEvent(
                kind="close", wallet=wallet, coin=coin, side=p.side,
                size=p.size, entry_price=p.entry_price,
                notional=p.notional, leverage=p.leverage,
                close_price=c.entry_price,
                pnl=c.unrealized_pnl,
                holding_seconds=now - opened_at,
            ))
            events.append(PositionEvent(
                kind="open", wallet=wallet, coin=coin, side=c.side,
                size=c.size, entry_price=c.entry_price,
                notional=c.notional, leverage=c.leverage,
            ))
        elif abs(c.size - p.size) / max(p.size, 1e-9) > 0.01:
            events.append(PositionEvent(
                kind="scale", wallet=wallet, coin=coin, side=c.side,
                size=c.size, entry_price=c.entry_price,
                notional=c.notional, leverage=c.leverage,
                close_price=p.size,
                pnl=p.notional,
            ))

    # CLOSED — in prev, not in curr
    for coin in prev_coins - curr_coins:
        p = prev[coin]
        opened_at = open_times.get(coin, now)
        events.append(PositionEvent(
            kind="close", wallet=wallet, coin=coin, side=p.side,
            size=p.size, entry_price=p.entry_price,
            notional=p.notional, leverage=p.leverage,
            close_price=None,
            pnl=p.unrealized_pnl,  # last known
            holding_seconds=now - opened_at,
        ))

    return events


# ---------------------------------------------------------------------------
#  userFills — trade execution events
# ---------------------------------------------------------------------------

def parse_user_fills(wallet: str, fills: list[dict]) -> list[FillEvent]:
    events: list[FillEvent] = []
    for f in fills:
        coin = f.get("coin") or ""
        side = (f.get("side") or "").upper()
        if side.startswith("B"):
            side = "BUY"
        else:
            side = "SELL"
        events.append(FillEvent(
            wallet=wallet,
            coin=coin,
            side=side,
            size=_f(f.get("sz")),
            price=_f(f.get("px")),
            closed_pnl=_f(f.get("closedPnl")),
            fee=_f(f.get("fee")),
            timestamp=int(_f(f.get("time", 0)) / 1000) or int(time.time()),
            oid=int(f.get("oid") or 0),
        ))
    return events

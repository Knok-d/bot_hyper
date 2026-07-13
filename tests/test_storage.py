"""Tests for database.storage — SQLite CRUD with temp file DB."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import pytest_asyncio

from database.storage import Order, Position, Storage

SCHEMA_PATH = str(Path(__file__).resolve().parent.parent / "database" / "schema.sql")

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = Storage(db_path, SCHEMA_PATH)
    await s.init()
    return s


# ---------------------------------------------------------------------------
#  Wallets CRUD
# ---------------------------------------------------------------------------

async def test_add_wallet(storage):
    ok = await storage.add_wallet("0xABC", "alice")
    assert ok is True
    wallets = await storage.list_wallets()
    assert len(wallets) == 1
    assert wallets[0].address == "0xabc"
    assert wallets[0].label == "alice"
    assert wallets[0].active is True


async def test_add_wallet_duplicate(storage):
    await storage.add_wallet("0xABC", "alice")
    ok = await storage.add_wallet("0xABC", "bob")
    assert ok is False


async def test_remove_wallet(storage):
    await storage.add_wallet("0xABC", "alice")
    ok = await storage.remove_wallet("0xABC")
    assert ok is True
    wallets = await storage.list_wallets()
    assert len(wallets) == 0


async def test_remove_wallet_missing(storage):
    ok = await storage.remove_wallet("0xDEAD")
    assert ok is False


async def test_rename_wallet(storage):
    await storage.add_wallet("0xABC", "alice")
    ok = await storage.rename_wallet("0xABC", "bob")
    assert ok is True
    w = await storage.get_wallet("0xABC")
    assert w.label == "bob"


async def test_set_active(storage):
    await storage.add_wallet("0xABC", "alice")
    await storage.set_active("0xABC", False)
    w = await storage.get_wallet("0xABC")
    assert w.active is False
    await storage.set_active("0xABC", True)
    w = await storage.get_wallet("0xABC")
    assert w.active is True


async def test_list_wallets_only_active(storage):
    await storage.add_wallet("0xA1", "a1")
    await storage.add_wallet("0xA2", "a2")
    await storage.set_active("0xA2", False)
    active = await storage.list_wallets(only_active=True)
    assert len(active) == 1
    assert active[0].address == "0xa1"


# ---------------------------------------------------------------------------
#  Positions CRUD
# ---------------------------------------------------------------------------

async def test_open_and_close_position(storage):
    await storage.add_wallet("0xABC", "alice")
    now = int(time.time())
    pos = Position(
        id=None, wallet="0xABC", coin="BTC", side="LONG",
        size=0.5, notional=32500, entry_price=65000,
        leverage=10, opened_at=now,
    )
    pid = await storage.open_position(pos)
    assert pid > 0

    opens = await storage.get_open_positions("0xABC")
    assert len(opens) == 1
    assert opens[0].coin == "BTC"

    closed = await storage.close_position("0xABC", "BTC", close_price=66000, pnl=500)
    assert closed is not None
    assert closed.pnl == 500
    assert closed.close_price == 66000

    opens_after = await storage.get_open_positions("0xABC")
    assert len(opens_after) == 0


async def test_positions_since(storage):
    await storage.add_wallet("0xABC", "alice")
    now = int(time.time())
    pos = Position(
        id=None, wallet="0xABC", coin="BTC", side="LONG",
        size=0.5, notional=32500, entry_price=65000,
        leverage=10, opened_at=now,
    )
    await storage.open_position(pos)
    await storage.close_position("0xABC", "BTC", close_price=66000, pnl=500)

    results = await storage.positions_since("0xABC", now - 10)
    assert len(results) == 1
    assert results[0].pnl == 500

    results_future = await storage.positions_since("0xABC", now + 3600)
    assert len(results_future) == 0


async def test_get_open_position(storage):
    await storage.add_wallet("0xABC", "alice")
    pos = Position(
        id=None, wallet="0xABC", coin="ETH", side="SHORT",
        size=2.0, notional=6400, entry_price=3200,
        leverage=5, opened_at=int(time.time()),
    )
    await storage.open_position(pos)

    found = await storage.get_open_position("0xABC", "ETH")
    assert found is not None
    assert found.side == "SHORT"
    assert found.size == 2.0

    notfound = await storage.get_open_position("0xABC", "BTC")
    assert notfound is None


# ---------------------------------------------------------------------------
#  Orders CRUD
# ---------------------------------------------------------------------------

async def test_upsert_and_close_order(storage):
    await storage.add_wallet("0xABC", "alice")
    order = Order(
        id=None, wallet="0xABC", oid=42, coin="BTC",
        type="LIMIT BUY", size=0.1, notional=6000,
        price=60000, status="open", created_at=int(time.time()),
    )
    is_new, prev = await storage.upsert_order(order)
    assert is_new is True
    assert prev is None

    is_new2, prev2 = await storage.upsert_order(order)
    assert is_new2 is False
    assert prev2 is not None
    assert prev2.oid == 42

    oids = await storage.open_orders_oids("0xABC")
    assert 42 in oids

    closed = await storage.close_order("0xABC", 42, "filled")
    assert closed is not None
    assert closed.status == "filled"

    oids_after = await storage.open_orders_oids("0xABC")
    assert 42 not in oids_after


async def test_close_order_already_closed(storage):
    await storage.add_wallet("0xABC", "alice")
    order = Order(
        id=None, wallet="0xABC", oid=99, coin="ETH",
        type="LIMIT SELL", size=1.0, notional=3500,
        price=3500, status="open", created_at=int(time.time()),
    )
    await storage.upsert_order(order)
    await storage.close_order("0xABC", 99, "canceled")
    result = await storage.close_order("0xABC", 99, "filled")
    assert result is None


# ---------------------------------------------------------------------------
#  History
# ---------------------------------------------------------------------------

async def test_add_history(storage):
    await storage.add_wallet("0xABC", "alice")
    await storage.add_history("0xABC", "open", "BTC", "LONG",
                              {"size": 0.5, "notional": 32500})

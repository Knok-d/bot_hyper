"""Tests for database.storage — SQLite CRUD with temp file DB (multi-user)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
import pytest_asyncio

from database.storage import Order, Position, Storage

SCHEMA_PATH = str(Path(__file__).resolve().parent.parent / "database" / "schema.sql")

pytestmark = pytest.mark.asyncio

USER_A = 111
USER_B = 222


@pytest_asyncio.fixture
async def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = Storage(db_path, SCHEMA_PATH)
    await s.init()
    return s


# ---------------------------------------------------------------------------
#  Users CRUD
# ---------------------------------------------------------------------------

async def test_upsert_and_get_user(storage):
    u = await storage.upsert_user(USER_A, lang="ru")
    assert u.chat_id == USER_A
    assert u.lang == "ru"
    assert u.min_position_usd == 10000
    assert u.fill_agg_threshold == 50000

    # second upsert must not overwrite
    u2 = await storage.upsert_user(USER_A, lang="en")
    assert u2.lang == "ru"


async def test_update_user_setting(storage):
    await storage.upsert_user(USER_A)
    await storage.update_user_setting(USER_A, "min_position_usd", 25000)
    await storage.update_user_setting(USER_A, "lang", "ru")
    u = await storage.get_user(USER_A)
    assert u.min_position_usd == 25000
    assert u.lang == "ru"


async def test_update_user_setting_rejects_unknown_field(storage):
    await storage.upsert_user(USER_A)
    with pytest.raises(ValueError):
        await storage.update_user_setting(USER_A, "created_at", 0)


# ---------------------------------------------------------------------------
#  Wallets CRUD (scoped by chat_id)
# ---------------------------------------------------------------------------

async def test_add_wallet(storage):
    ok = await storage.add_wallet(USER_A, "0xABC", "alice")
    assert ok is True
    wallets = await storage.list_wallets(USER_A)
    assert len(wallets) == 1
    assert wallets[0].address == "0xabc"
    assert wallets[0].label == "alice"
    assert wallets[0].active is True


async def test_add_wallet_duplicate(storage):
    await storage.add_wallet(USER_A, "0xABC", "alice")
    ok = await storage.add_wallet(USER_A, "0xABC", "bob")
    assert ok is False


async def test_same_wallet_two_users(storage):
    """Different users may track the same address independently."""
    assert await storage.add_wallet(USER_A, "0xABC", "alice") is True
    assert await storage.add_wallet(USER_B, "0xABC", "bob") is True

    a = await storage.get_wallet(USER_A, "0xABC")
    b = await storage.get_wallet(USER_B, "0xABC")
    assert a.label == "alice"
    assert b.label == "bob"


async def test_wallet_isolation(storage):
    """User B must not see or affect user A's wallets."""
    await storage.add_wallet(USER_A, "0xABC", "alice")

    assert await storage.list_wallets(USER_B) == []
    assert await storage.get_wallet(USER_B, "0xABC") is None
    assert await storage.remove_wallet(USER_B, "0xABC") is False
    assert await storage.rename_wallet(USER_B, "0xABC", "hack") is False
    assert await storage.set_active(USER_B, "0xABC", False) is False

    # A's wallet untouched
    w = await storage.get_wallet(USER_A, "0xABC")
    assert w.label == "alice"
    assert w.active is True


async def test_count_wallets(storage):
    assert await storage.count_wallets(USER_A) == 0
    await storage.add_wallet(USER_A, "0xA1", "a1")
    await storage.add_wallet(USER_A, "0xA2", "a2")
    await storage.add_wallet(USER_B, "0xB1", "b1")
    assert await storage.count_wallets(USER_A) == 2
    assert await storage.count_wallets(USER_B) == 1


async def test_wallet_subscribers(storage):
    await storage.add_wallet(USER_A, "0xABC", "alice")
    await storage.add_wallet(USER_B, "0xABC", "bob")
    await storage.add_wallet(USER_B, "0xDEF", "other")
    await storage.set_active(USER_B, "0xABC", False)  # paused → not a subscriber

    subs = await storage.wallet_subscribers("0xABC")
    assert [(w.chat_id, w.label) for w in subs] == [(USER_A, "alice")]


async def test_list_active_subscriptions(storage):
    await storage.add_wallet(USER_A, "0xA1", "a1")
    await storage.add_wallet(USER_B, "0xA1", "b-copy")
    await storage.add_wallet(USER_B, "0xB1", "b1")
    await storage.set_active(USER_B, "0xB1", False)

    subs = await storage.list_active_subscriptions()
    pairs = {(w.chat_id, w.address) for w in subs}
    assert pairs == {(USER_A, "0xa1"), (USER_B, "0xa1")}


async def test_remove_wallet(storage):
    await storage.add_wallet(USER_A, "0xABC", "alice")
    ok = await storage.remove_wallet(USER_A, "0xABC")
    assert ok is True
    wallets = await storage.list_wallets(USER_A)
    assert len(wallets) == 0


async def test_rename_wallet(storage):
    await storage.add_wallet(USER_A, "0xABC", "alice")
    ok = await storage.rename_wallet(USER_A, "0xABC", "bob")
    assert ok is True
    w = await storage.get_wallet(USER_A, "0xABC")
    assert w.label == "bob"


async def test_set_active(storage):
    await storage.add_wallet(USER_A, "0xABC", "alice")
    await storage.set_active(USER_A, "0xABC", False)
    w = await storage.get_wallet(USER_A, "0xABC")
    assert w.active is False
    await storage.set_active(USER_A, "0xABC", True)
    w = await storage.get_wallet(USER_A, "0xABC")
    assert w.active is True


async def test_list_wallets_only_active(storage):
    await storage.add_wallet(USER_A, "0xA1", "a1")
    await storage.add_wallet(USER_A, "0xA2", "a2")
    await storage.set_active(USER_A, "0xA2", False)
    active = await storage.list_wallets(USER_A, only_active=True)
    assert len(active) == 1
    assert active[0].address == "0xa1"


async def test_count_stats(storage):
    await storage.upsert_user(USER_A)
    await storage.upsert_user(USER_B)
    await storage.add_wallet(USER_A, "0xA1", "a1")
    await storage.add_wallet(USER_B, "0xA1", "b-copy")
    await storage.add_wallet(USER_B, "0xB1", "b1")
    stats = await storage.count_stats()
    assert stats["users"] == 2
    assert stats["wallets"] == 3
    assert stats["unique_active_addresses"] == 2


# ---------------------------------------------------------------------------
#  Migration v1 -> v2
# ---------------------------------------------------------------------------

async def test_migration_from_v1(tmp_path):
    db_path = str(tmp_path / "old.db")
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE wallets (
            address TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            added_at INTEGER NOT NULL
        );
        INSERT INTO wallets VALUES ('0xaaa', 'whale1', 1, 100);
        INSERT INTO wallets VALUES ('0xbbb', 'whale2', 0, 200);
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL, coin TEXT NOT NULL, side TEXT NOT NULL,
            size REAL NOT NULL, notional REAL NOT NULL,
            entry_price REAL NOT NULL, leverage REAL,
            opened_at INTEGER NOT NULL, closed_at INTEGER,
            close_price REAL, pnl REAL
        );
        INSERT INTO positions(wallet,coin,side,size,notional,entry_price,opened_at)
            VALUES ('0xaaa','BTC','LONG',1,60000,60000,100);
    """)
    con.commit()
    con.close()

    owner = 999
    s = Storage(db_path, SCHEMA_PATH)
    await s.init(legacy_owner_chat_id=owner)

    # wallets assigned to the owner, active flags preserved
    wallets = await s.list_wallets(owner)
    assert {(w.address, w.active) for w in wallets} == {
        ("0xaaa", True), ("0xbbb", False)}

    # owner user auto-created
    u = await s.get_user(owner)
    assert u is not None
    assert u.lang == "ru"

    # positions survived
    opens = await s.get_open_positions("0xaaa")
    assert len(opens) == 1

    # backup file created
    backups = list(Path(tmp_path).glob("old.db.bak-*"))
    assert len(backups) == 1


async def test_migration_requires_owner(tmp_path):
    db_path = str(tmp_path / "old.db")
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE wallets (
            address TEXT PRIMARY KEY, label TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, added_at INTEGER NOT NULL
        );
    """)
    con.commit()
    con.close()

    s = Storage(db_path, SCHEMA_PATH)
    with pytest.raises(RuntimeError):
        await s.init(legacy_owner_chat_id=0)


async def test_init_idempotent(storage):
    """Re-running init on a v2 DB must be a no-op."""
    await storage.add_wallet(USER_A, "0xABC", "alice")
    await storage.init(legacy_owner_chat_id=1)
    wallets = await storage.list_wallets(USER_A)
    assert len(wallets) == 1


# ---------------------------------------------------------------------------
#  Positions CRUD
# ---------------------------------------------------------------------------

async def test_open_and_close_position(storage):
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
    await storage.add_history("0xABC", "open", "BTC", "LONG",
                              {"size": 0.5, "notional": 32500})

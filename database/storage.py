"""Async SQLite storage for users, wallets, positions, orders, history."""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("db")


@dataclass
class User:
    chat_id: int
    lang: str
    min_position_usd: float
    fill_agg_threshold: float
    created_at: int


@dataclass
class Wallet:
    chat_id: int
    address: str
    label: str
    active: bool
    added_at: int


@dataclass
class Position:
    id: Optional[int]
    wallet: str
    coin: str
    side: str
    size: float
    notional: float
    entry_price: float
    leverage: Optional[float]
    opened_at: int
    closed_at: Optional[int] = None
    close_price: Optional[float] = None
    pnl: Optional[float] = None


@dataclass
class Order:
    id: Optional[int]
    wallet: str
    oid: int
    coin: str
    type: str
    size: float
    notional: float
    price: float
    status: str
    created_at: int
    closed_at: Optional[int] = None


def _now() -> int:
    return int(time.time())


class Storage:
    """Async wrapper over aiosqlite."""

    def __init__(self, db_path: str, schema_path: str):
        self.db_path = db_path
        self.schema_path = schema_path

    async def init(self, legacy_owner_chat_id: int = 0) -> None:
        """Create database file & schema if missing; migrate v1 -> v2 if needed.

        ``legacy_owner_chat_id`` — chat_id, которому приписываются кошельки
        из старой single-user схемы (обычно ADMIN_CHAT_ID).
        """
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        await self._migrate_if_needed(legacy_owner_chat_id)
        async with aiosqlite.connect(self.db_path) as db:
            # Every query opens its own connection, so readers and the writer
            # overlap constantly; WAL keeps them from blocking each other.
            # Persisted in the db file — setting it once here is enough.
            await db.execute("PRAGMA journal_mode=WAL")
            with open(self.schema_path, "r", encoding="utf-8") as f:
                await db.executescript(f.read())
            await db.commit()

    async def _migrate_if_needed(self, owner_chat_id: int) -> None:
        """v1 (wallets without chat_id) -> v2 (multi-user)."""
        if not Path(self.db_path).exists():
            return
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("PRAGMA table_info(wallets)") as cur:
                cols = [r[1] for r in await cur.fetchall()]
            if not cols or "chat_id" in cols:
                return  # fresh DB or already migrated

            if not owner_chat_id:
                raise RuntimeError(
                    "DB migration v1->v2 requires ADMIN_CHAT_ID to assign "
                    "existing wallets to the owner."
                )

            backup = f"{self.db_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(self.db_path, backup)
            log.info("Migrating DB to multi-user schema; backup: %s", backup)

            await db.executescript(f"""
                BEGIN;
                CREATE TABLE IF NOT EXISTS users (
                    chat_id             INTEGER PRIMARY KEY,
                    lang                TEXT NOT NULL DEFAULT 'en',
                    min_position_usd    REAL NOT NULL DEFAULT 10000,
                    fill_agg_threshold  REAL NOT NULL DEFAULT 50000,
                    created_at          INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO users(chat_id, lang, created_at)
                    VALUES ({owner_chat_id}, 'ru', {_now()});
                CREATE TABLE wallets_v2 (
                    chat_id     INTEGER NOT NULL,
                    address     TEXT NOT NULL,
                    label       TEXT NOT NULL,
                    active      INTEGER NOT NULL DEFAULT 1,
                    added_at    INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, address)
                );
                INSERT INTO wallets_v2(chat_id, address, label, active, added_at)
                    SELECT {owner_chat_id}, address, label, active, added_at
                    FROM wallets;
                DROP TABLE wallets;
                ALTER TABLE wallets_v2 RENAME TO wallets;
                CREATE INDEX IF NOT EXISTS idx_wallets_address
                    ON wallets(address);
                COMMIT;
            """)
            log.info("Migration done: wallets assigned to chat_id %d",
                     owner_chat_id)

    # ---------- USERS ----------

    async def upsert_user(self, chat_id: int, lang: str = "en",
                          min_position_usd: float = 10000,
                          fill_agg_threshold: float = 50000) -> User:
        """Create the user if missing; return the stored row either way."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO users
                       (chat_id, lang, min_position_usd, fill_agg_threshold, created_at)
                       VALUES(?,?,?,?,?)""",
                (chat_id, lang, min_position_usd, fill_agg_threshold, _now()),
            )
            await db.commit()
        user = await self.get_user(chat_id)
        assert user is not None
        return user

    async def get_user(self, chat_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT chat_id, lang, min_position_usd, fill_agg_threshold,
                          created_at FROM users WHERE chat_id=?""",
                (chat_id,),
            ) as cur:
                row = await cur.fetchone()
        return User(*row) if row else None

    async def update_user_setting(self, chat_id: int, field: str,
                                  value: Any) -> bool:
        if field not in ("lang", "min_position_usd", "fill_agg_threshold"):
            raise ValueError(f"unknown user setting: {field}")
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                f"UPDATE users SET {field}=? WHERE chat_id=?",
                (value, chat_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def list_users(self) -> list[User]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT chat_id, lang, min_position_usd, fill_agg_threshold,
                          created_at FROM users ORDER BY created_at"""
            ) as cur:
                rows = await cur.fetchall()
        return [User(*r) for r in rows]

    # ---------- WALLETS ----------

    async def add_wallet(self, chat_id: int, address: str, label: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """INSERT INTO wallets(chat_id,address,label,active,added_at)
                       VALUES(?,?,?,1,?)""",
                    (chat_id, address, label, _now()),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_wallet(self, chat_id: int, address: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM wallets WHERE chat_id=? AND address=?",
                (chat_id, address),
            )
            await db.commit()
            return cur.rowcount > 0

    async def rename_wallet(self, chat_id: int, address: str,
                            new_label: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE wallets SET label=? WHERE chat_id=? AND address=?",
                (new_label, chat_id, address),
            )
            await db.commit()
            return cur.rowcount > 0

    async def set_active(self, chat_id: int, address: str,
                         active: bool) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE wallets SET active=? WHERE chat_id=? AND address=?",
                (1 if active else 0, chat_id, address),
            )
            await db.commit()
            return cur.rowcount > 0

    async def list_wallets(self, chat_id: int,
                           only_active: bool = False) -> list[Wallet]:
        sql = ("SELECT chat_id,address,label,active,added_at FROM wallets "
               "WHERE chat_id=?")
        if only_active:
            sql += " AND active=1"
        sql += " ORDER BY added_at"
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(sql, (chat_id,)) as cur:
                rows = await cur.fetchall()
        return [Wallet(r[0], r[1], r[2], bool(r[3]), r[4]) for r in rows]

    async def get_wallet(self, chat_id: int, address: str) -> Optional[Wallet]:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT chat_id,address,label,active,added_at FROM wallets
                   WHERE chat_id=? AND address=?""",
                (chat_id, address),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return Wallet(row[0], row[1], row[2], bool(row[3]), row[4])

    async def count_wallets(self, chat_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM wallets WHERE chat_id=?", (chat_id,)
            ) as cur:
                row = await cur.fetchone()
        return int(row[0])

    async def wallet_subscribers(self, address: str) -> list[Wallet]:
        """All users actively tracking the address (for event fan-out)."""
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT chat_id,address,label,active,added_at FROM wallets
                   WHERE address=? AND active=1""",
                (address,),
            ) as cur:
                rows = await cur.fetchall()
        return [Wallet(r[0], r[1], r[2], bool(r[3]), r[4]) for r in rows]

    async def list_active_subscriptions(self) -> list[Wallet]:
        """Every active (user, wallet) pair — to rebuild routing on startup."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT chat_id,address,label,active,added_at FROM wallets
                   WHERE active=1 ORDER BY added_at"""
            ) as cur:
                rows = await cur.fetchall()
        return [Wallet(r[0], r[1], r[2], bool(r[3]), r[4]) for r in rows]

    async def count_stats(self) -> dict:
        """Aggregate counters for /admin."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                users = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM wallets") as cur:
                wallets = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(DISTINCT address) FROM wallets WHERE active=1"
            ) as cur:
                unique_active = (await cur.fetchone())[0]
        return {"users": users, "wallets": wallets,
                "unique_active_addresses": unique_active}

    # ---------- POSITIONS ----------

    async def open_position(self, p: Position) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """INSERT INTO positions
                       (wallet,coin,side,size,notional,entry_price,leverage,opened_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                (
                    p.wallet.lower(), p.coin, p.side, p.size, p.notional,
                    p.entry_price, p.leverage, p.opened_at,
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def close_position(
        self, wallet: str, coin: str,
        close_price: float, pnl: float, ts: Optional[int] = None,
    ) -> Optional[Position]:
        """Close the open position (wallet, coin) and return the closed row."""
        wallet = wallet.lower()
        ts = ts or _now()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, coin, side, size, notional, entry_price,
                          leverage, opened_at
                   FROM positions
                   WHERE wallet=? AND coin=? AND closed_at IS NULL
                   ORDER BY opened_at DESC LIMIT 1""",
                (wallet, coin),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            await db.execute(
                "UPDATE positions SET closed_at=?, close_price=?, pnl=? WHERE id=?",
                (ts, close_price, pnl, row[0]),
            )
            await db.commit()
        return Position(
            id=row[0], wallet=row[1], coin=row[2], side=row[3],
            size=row[4], notional=row[5], entry_price=row[6],
            leverage=row[7], opened_at=row[8],
            closed_at=ts, close_price=close_price, pnl=pnl,
        )

    async def get_open_position(
        self, wallet: str, coin: str,
    ) -> Optional[Position]:
        wallet = wallet.lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, coin, side, size, notional, entry_price,
                          leverage, opened_at, closed_at, close_price, pnl
                   FROM positions
                   WHERE wallet=? AND coin=? AND closed_at IS NULL
                   ORDER BY opened_at DESC LIMIT 1""",
                (wallet, coin),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return Position(*row)

    async def get_open_positions(self, wallet: str) -> list[Position]:
        wallet = wallet.lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, coin, side, size, notional, entry_price,
                          leverage, opened_at, closed_at, close_price, pnl
                   FROM positions
                   WHERE wallet=? AND closed_at IS NULL""",
                (wallet,),
            ) as cur:
                rows = await cur.fetchall()
        return [Position(*r) for r in rows]

    async def positions_since(
        self, wallet: Optional[str], since_ts: int,
    ) -> list[Position]:
        sql = """SELECT id, wallet, coin, side, size, notional, entry_price,
                        leverage, opened_at, closed_at, close_price, pnl
                 FROM positions
                 WHERE (closed_at >= ? OR opened_at >= ?)"""
        params: list[Any] = [since_ts, since_ts]
        if wallet:
            sql += " AND wallet=?"
            params.append(wallet.lower())
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [Position(*r) for r in rows]

    # ---------- ORDERS ----------

    async def upsert_order(self, o: Order) -> tuple[bool, Optional[Order]]:
        """Insert order if new. Returns (is_new, prev_record)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, oid, coin, type, size, notional,
                          price, status, created_at, closed_at
                   FROM orders WHERE wallet=? AND oid=?""",
                (o.wallet.lower(), o.oid),
            ) as cur:
                row = await cur.fetchone()
            if row:
                return False, Order(*row)
            await db.execute(
                """INSERT INTO orders
                       (wallet,oid,coin,type,size,notional,price,status,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    o.wallet.lower(), o.oid, o.coin, o.type, o.size,
                    o.notional, o.price, o.status, o.created_at,
                ),
            )
            await db.commit()
            return True, None

    async def close_order(
        self, wallet: str, oid: int, status: str, ts: Optional[int] = None,
    ) -> Optional[Order]:
        ts = ts or _now()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, oid, coin, type, size, notional,
                          price, status, created_at, closed_at
                   FROM orders WHERE wallet=? AND oid=?""",
                (wallet.lower(), oid),
            ) as cur:
                row = await cur.fetchone()
            if not row or row[10] is not None:  # already closed or missing
                return None
            await db.execute(
                "UPDATE orders SET status=?, closed_at=? WHERE id=?",
                (status, ts, row[0]),
            )
            await db.commit()
        o = Order(*row)
        o.status = status
        o.closed_at = ts
        return o

    async def get_open_orders(self, wallet: str) -> list[Order]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT id, wallet, oid, coin, type, size, notional,
                          price, status, created_at, closed_at
                   FROM orders WHERE wallet=? AND closed_at IS NULL""",
                (wallet.lower(),),
            ) as cur:
                rows = await cur.fetchall()
        return [Order(*r) for r in rows]

    async def open_orders_oids(self, wallet: str) -> set[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT oid FROM orders WHERE wallet=? AND closed_at IS NULL",
                (wallet.lower(),),
            ) as cur:
                rows = await cur.fetchall()
        return {r[0] for r in rows}

    # ---------- HISTORY ----------

    async def add_history(
        self, wallet: str, event_type: str, coin: Optional[str],
        side: Optional[str], payload: dict,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO history(wallet,event_type,coin,side,payload,ts)
                   VALUES(?,?,?,?,?,?)""",
                (
                    wallet.lower(), event_type, coin, side,
                    json.dumps(payload, ensure_ascii=False), _now(),
                ),
            )
            await db.commit()

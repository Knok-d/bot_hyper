"""Async SQLite storage for wallets, positions, orders, history."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiosqlite


@dataclass
class Wallet:
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

    async def init(self) -> None:
        """Create database file & schema if missing."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            with open(self.schema_path, "r", encoding="utf-8") as f:
                await db.executescript(f.read())
            await db.commit()

    # ---------- WALLETS ----------

    async def add_wallet(self, address: str, label: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO wallets(address,label,active,added_at) VALUES(?,?,1,?)",
                    (address, label, _now()),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_wallet(self, address: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM wallets WHERE address=?", (address,)
            )
            await db.commit()
            return cur.rowcount > 0

    async def rename_wallet(self, address: str, new_label: str) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE wallets SET label=? WHERE address=?",
                (new_label, address),
            )
            await db.commit()
            return cur.rowcount > 0

    async def set_active(self, address: str, active: bool) -> bool:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE wallets SET active=? WHERE address=?",
                (1 if active else 0, address),
            )
            await db.commit()
            return cur.rowcount > 0

    async def list_wallets(self, only_active: bool = False) -> list[Wallet]:
        sql = "SELECT address,label,active,added_at FROM wallets"
        if only_active:
            sql += " WHERE active=1"
        sql += " ORDER BY added_at"
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(sql) as cur:
                rows = await cur.fetchall()
        return [Wallet(r[0], r[1], bool(r[2]), r[3]) for r in rows]

    async def get_wallet(self, address: str) -> Optional[Wallet]:
        address = address.lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT address,label,active,added_at FROM wallets WHERE address=?",
                (address,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return Wallet(row[0], row[1], bool(row[2]), row[3])

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

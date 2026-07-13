"""Anomaly detector — fires when N+ wallets open the same direction within a window."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass
class _Recent:
    wallet: str
    label: str
    notional: float
    ts: int


@dataclass
class AnomalyHit:
    coin: str
    side: str
    wallets: list[tuple[str, str, float]]  # (address, label, notional)
    total_notional: float
    interval_seconds: int


class AnomalyDetector:
    """Sliding-window correlation of position opens.

    Call :meth:`record_open` whenever an OPEN event is observed. If, within
    ``window_sec``, ``min_wallets`` distinct wallets opened the same
    (coin, side), :meth:`record_open` returns an :class:`AnomalyHit`.
    """

    def __init__(self, window_sec: int = 300, min_wallets: int = 2):
        self.window_sec = window_sec
        self.min_wallets = min_wallets
        # key = (coin, side) -> deque of recent opens
        self._buf: dict[tuple[str, str], Deque[_Recent]] = defaultdict(deque)
        # debounce — don't fire twice for the same correlated cluster
        self._last_fired: dict[tuple[str, str], int] = {}
        self._fire_cooldown = window_sec  # seconds

    def record_open(
        self, wallet: str, label: str, coin: str, side: str, notional: float,
    ) -> Optional[AnomalyHit]:
        now = int(time.time())
        key = (coin, side)
        buf = self._buf[key]

        # purge old
        while buf and now - buf[0].ts > self.window_sec:
            buf.popleft()

        # don't double-count same wallet inside window
        for r in buf:
            if r.wallet.lower() == wallet.lower():
                # update notional/timestamp but don't add a new entry
                r.notional = notional
                r.ts = now
                break
        else:
            buf.append(_Recent(wallet=wallet.lower(), label=label,
                               notional=notional, ts=now))

        if len({r.wallet for r in buf}) < self.min_wallets:
            return None

        # cooldown — don't spam
        last = self._last_fired.get(key, 0)
        if now - last < self._fire_cooldown:
            return None
        self._last_fired[key] = now

        wallets = [(r.wallet, r.label, r.notional) for r in buf]
        total = sum(r.notional for r in buf)
        oldest = min(r.ts for r in buf)
        return AnomalyHit(
            coin=coin, side=side, wallets=wallets,
            total_notional=total, interval_seconds=now - oldest,
        )

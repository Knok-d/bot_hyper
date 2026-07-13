"""Hyperliquid REST API client for historical data not available over WS."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

import config

log = logging.getLogger("hl.rest")

_CACHE_TTL = 60  # seconds


@dataclass
class PortfolioPnL:
    """Realized PnL aggregated over standard periods (USD)."""
    day: float = 0.0       # last 24h
    week: float = 0.0      # last 7d
    month: float = 0.0     # last 30d
    all_time: float = 0.0  # all time
    account_value: float = 0.0  # most recent account value


@dataclass
class TwapSliceFill:
    """A single fill that happened as part of a TWAP order execution."""
    coin: str = ""
    side: str = ""            # 'BUY' / 'SELL'
    size: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    fee_token: str = "USDC"
    closed_pnl: float = 0.0
    time: int = 0             # unix seconds
    twap_id: int = 0
    oid: int = 0


class HyperliquidREST:
    """Tiny async client over POST /info with per-wallet response cache."""

    def __init__(self, base_url: str = config.HL_API_URL):
        self.base_url = base_url
        self._cache: dict[str, tuple[float, PortfolioPnL]] = {}
        self._twap_cache: dict[str, tuple[float, list[TwapSliceFill]]] = {}

    async def _post_info(self, payload: dict) -> Optional[object]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{self.base_url}/info", json=payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            log.warning("info %s failed: %s", payload.get("type"), e)
            return None

    async def fetch_portfolio(self, wallet: str) -> Optional[PortfolioPnL]:
        wallet = wallet.lower()
        now = time.time()
        cached = self._cache.get(wallet)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]

        data = await self._post_info({"type": "portfolio", "user": wallet})
        if data is None:
            return cached[1] if cached else None

        result = _parse_portfolio(data)
        self._cache[wallet] = (now, result)
        return result

    async def fetch_twap_slice_fills(
        self, wallet: str, days: int = 7,
    ) -> list[TwapSliceFill]:
        """Return TWAP slice fills for the last N days (cached 60s)."""
        wallet = wallet.lower()
        now = time.time()
        cached = self._twap_cache.get(wallet)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]

        end_ms = int(now * 1000)
        start_ms = end_ms - days * 86400 * 1000
        data = await self._post_info({
            "type": "userTwapSliceFillsByTime",
            "user": wallet,
            "startTime": start_ms,
            "endTime": end_ms,
        })
        if data is None:
            return cached[1] if cached else []

        fills = _parse_twap_fills(data)
        self._twap_cache[wallet] = (now, fills)
        return fills


def _parse_portfolio(data: list) -> PortfolioPnL:
    """Convert API response (list of [period_name, period_data]) into PortfolioPnL."""
    pnl = PortfolioPnL()
    by_period = {item[0]: item[1] for item in data if isinstance(item, list) and len(item) >= 2}

    for period_name, attr in (("day", "day"), ("week", "week"),
                              ("month", "month"), ("allTime", "all_time")):
        period_data = by_period.get(period_name) or {}
        hist = period_data.get("pnlHistory") or []
        if len(hist) >= 2:
            try:
                start = float(hist[0][1])
                end = float(hist[-1][1])
                setattr(pnl, attr, end - start)
            except (ValueError, IndexError, TypeError):
                pass

    av_hist = (by_period.get("allTime") or {}).get("accountValueHistory") or []
    if av_hist:
        try:
            pnl.account_value = float(av_hist[-1][1])
        except (ValueError, IndexError, TypeError):
            pass

    return pnl


def _f(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_twap_fills(data: object) -> list[TwapSliceFill]:
    """Parse userTwapSliceFillsByTime response into TwapSliceFill list.

    Each entry typically looks like::
        {"fill": {"coin","px","sz","side","time","fee","feeToken","closedPnl","oid"},
         "twapId": ...}
    """
    out: list[TwapSliceFill] = []
    if not isinstance(data, list):
        return out
    for entry in data:
        if not isinstance(entry, dict):
            continue
        fill = entry.get("fill") if isinstance(entry.get("fill"), dict) else entry
        side_raw = str(fill.get("side") or "").upper()
        side = "BUY" if side_raw.startswith("B") else "SELL"
        out.append(TwapSliceFill(
            coin=str(fill.get("coin") or ""),
            side=side,
            size=_f(fill.get("sz")),
            price=_f(fill.get("px")),
            fee=_f(fill.get("fee")),
            fee_token=str(fill.get("feeToken") or "USDC"),
            closed_pnl=_f(fill.get("closedPnl")),
            time=int(_f(fill.get("time", 0)) / 1000),
            twap_id=int(_f(entry.get("twapId") or fill.get("twapId") or 0)),
            oid=int(_f(fill.get("oid") or 0)),
        ))
    return out

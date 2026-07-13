"""Tests for hl_monitor.detector — AnomalyDetector sliding-window logic."""
from __future__ import annotations

import time
from unittest.mock import patch

from hl_monitor.detector import AnomalyDetector


WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40
WALLET_C = "0x" + "c" * 40


def test_fires_on_two_wallets_in_window():
    d = AnomalyDetector(window_sec=300, min_wallets=2)
    r1 = d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    assert r1 is None

    r2 = d.record_open(WALLET_B, "Bob", "BTC", "LONG", 20000)
    assert r2 is not None
    assert r2.coin == "BTC"
    assert r2.side == "LONG"
    assert len(r2.wallets) == 2
    assert r2.total_notional == 30000


def test_does_not_fire_same_wallet_twice():
    d = AnomalyDetector(window_sec=300, min_wallets=2)
    d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    r = d.record_open(WALLET_A, "Alice", "BTC", "LONG", 15000)
    assert r is None


def test_does_not_fire_after_window_expires():
    d = AnomalyDetector(window_sec=60, min_wallets=2)
    past = time.time() - 120
    with patch("hl_monitor.detector.time") as mock_time:
        mock_time.time.return_value = past
        d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)

        mock_time.time.return_value = time.time()
        r = d.record_open(WALLET_B, "Bob", "BTC", "LONG", 20000)
        assert r is None


def test_cooldown_prevents_rapid_fire():
    d = AnomalyDetector(window_sec=300, min_wallets=2)

    r1 = d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    assert r1 is None
    r2 = d.record_open(WALLET_B, "Bob", "BTC", "LONG", 20000)
    assert r2 is not None

    r3 = d.record_open(WALLET_C, "Charlie", "BTC", "LONG", 30000)
    assert r3 is None  # cooldown active


def test_different_coins_independent():
    d = AnomalyDetector(window_sec=300, min_wallets=2)
    d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    r = d.record_open(WALLET_B, "Bob", "ETH", "LONG", 20000)
    assert r is None  # different coin


def test_different_sides_independent():
    d = AnomalyDetector(window_sec=300, min_wallets=2)
    d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    r = d.record_open(WALLET_B, "Bob", "BTC", "SHORT", 20000)
    assert r is None  # different side


def test_min_wallets_three():
    d = AnomalyDetector(window_sec=300, min_wallets=3)
    d.record_open(WALLET_A, "Alice", "BTC", "LONG", 10000)
    r1 = d.record_open(WALLET_B, "Bob", "BTC", "LONG", 20000)
    assert r1 is None
    r2 = d.record_open(WALLET_C, "Charlie", "BTC", "LONG", 30000)
    assert r2 is not None
    assert len(r2.wallets) == 3

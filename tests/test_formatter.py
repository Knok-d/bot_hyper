"""Smoke: every screen/notification formatter renders in both languages."""
from __future__ import annotations

import pytest

from bot import formatter as f
from database.storage import User, Wallet
from hl_monitor.detector import AnomalyHit
from hl_monitor.parser import PositionEvent

WALLET = Wallet(chat_id=1, address="0x" + "a" * 40, label="whale",
                active=True, added_at=0)
USER = User(chat_id=1, lang="ru", min_position_usd=10000,
            fill_agg_threshold=50000, created_at=0)

EV = PositionEvent(kind="open", wallet=WALLET.address, coin="BTC",
                   side="LONG", size=1.0, entry_price=60000,
                   notional=60000, leverage=10)

AGG = {
    "wallet": WALLET.address, "coin": "BTC", "side": "BUY",
    "count": 3, "total_size": 1.5, "total_notional": 90000,
    "total_pnl": 120.0, "total_fee": 15.0, "avg_price": 60000,
    "open_fills": 3, "close_fills": 0,
    "open_notional": 90000, "close_notional": 0.0,
    "first_ts": 1_700_000_000, "last_ts": 1_700_000_100,
}

HIT = AnomalyHit(coin="BTC", side="LONG",
                 wallets=[(WALLET.address, "whale", 60000)],
                 total_notional=60000, interval_seconds=120)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_screen_texts_render(lang):
    assert f.main_menu_text(lang)
    assert f.settings_text(lang, USER)
    assert f.help_text(lang)
    assert f.add_wallet_prompt(lang)
    assert f.stats_menu_text(lang)
    assert f.wallets_list_text(lang, [WALLET])
    assert f.wallets_list_text(lang, [])
    assert f.wallet_stats_menu_text(lang, WALLET)
    assert f.rename_prompt_text(lang, WALLET)
    assert f.confirm_remove_text(lang, WALLET)
    assert f.format_wallet_list(lang, [WALLET])
    assert f.wallet_detail_text(lang, WALLET, {}, [])


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_notifications_render(lang):
    assert f.format_position_open(lang, EV, "whale")
    close_ev = PositionEvent(kind="close", wallet=WALLET.address, coin="BTC",
                             side="LONG", size=1.0, entry_price=60000,
                             notional=60000, leverage=10, close_price=61000,
                             pnl=1000.0, holding_seconds=3600)
    assert f.format_position_close(lang, close_ev, "whale")
    assert f.format_position_scaled(lang, EV, "whale", 0.5, 30000)
    assert f.format_fills_aggregated(lang, AGG, "whale")
    assert f.format_anomaly(lang, HIT, {WALLET.address: "whale"})
    assert f.format_active_positions(lang, [("whale", WALLET.address, {})])
    assert f.format_active_orders(lang, [("whale", WALLET.address, [])])
    assert f.format_stats(lang, "whale", [], [], "24h")
    assert f.format_global_stats(lang, [("whale", [], [])], "24h")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_keyboards_render(lang):
    assert f.main_menu_keyboard(lang)
    assert f.settings_keyboard(lang)
    assert f.wallets_list_keyboard(lang, [WALLET])
    assert f.wallet_detail_keyboard(lang, WALLET)
    assert f.stats_period_keyboard(lang)
    assert f.stats_period_keyboard(lang, WALLET.address)
    assert f.confirm_remove_keyboard(lang, WALLET.address)
    assert f.cancel_keyboard(lang)
    assert f.back_to_menu_keyboard(lang)

"""Event fan-out: one wallet event → per-user filters, language, thresholds."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from bot.users import UserService
from database.storage import Storage
from hl_monitor.parser import FillEvent, PositionEvent
from main import Bot

SCHEMA_PATH = str(Path(__file__).resolve().parent.parent / "database" / "schema.sql")

pytestmark = pytest.mark.asyncio

WALLET = "0xaabbccdd00112233445566778899aabbccddeeff"
USER_RU = 111  # ru, min position $10K
USER_EN = 222  # en, min position $20K


@pytest_asyncio.fixture
async def bot(tmp_path):
    b = Bot()
    b.storage = Storage(str(tmp_path / "test.db"), SCHEMA_PATH)
    b.users = UserService(b.storage)
    await b.storage.init()

    await b.storage.upsert_user(USER_RU, lang="ru",
                                min_position_usd=10_000,
                                fill_agg_threshold=20_000)
    await b.storage.upsert_user(USER_EN, lang="en",
                                min_position_usd=20_000,
                                fill_agg_threshold=60_000)
    await b.storage.add_wallet(USER_RU, WALLET, "kit")
    await b.storage.add_wallet(USER_EN, WALLET, "whale")
    for w in await b.storage.list_active_subscriptions():
        b.subscribers.setdefault(w.address, {})[w.chat_id] = w.label
        b.labels[(w.chat_id, w.address)] = w.label

    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    b._send = fake_send
    b.sent = sent
    return b


def _open_event(notional: float) -> PositionEvent:
    return PositionEvent(
        kind="open", wallet=WALLET, coin="BTC", side="LONG",
        size=notional / 60000, entry_price=60000,
        notional=notional, leverage=10,
    )


async def test_open_event_respects_per_user_min_position(bot):
    await bot._on_position_event(_open_event(30_000))
    by_user = {cid: text for cid, text in bot.sent}
    assert USER_RU in by_user and USER_EN in by_user
    assert "ОТКРЫТА ПОЗИЦИЯ" in by_user[USER_RU]
    assert "POSITION OPENED" in by_user[USER_EN]
    assert "kit" in by_user[USER_RU]
    assert "whale" in by_user[USER_EN]


async def test_small_open_filtered_for_stricter_user(bot):
    await bot._on_position_event(_open_event(15_000))
    recipients = [cid for cid, _ in bot.sent]
    assert recipients == [USER_RU]


async def test_unsubscribed_wallet_is_silent(bot):
    ev = _open_event(30_000)
    ev.wallet = "0x0000000000000000000000000000000000000001"
    await bot._on_position_event(ev)
    assert bot.sent == []


async def test_fill_aggregation_per_user_threshold(bot):
    fill = FillEvent(
        wallet=WALLET, coin="ETH", side="BUY",
        size=5.0, price=3000, closed_pnl=0, fee=4.5,
        timestamp=1_700_000_000, oid=1,
    )  # $15K notional
    await bot._on_fill_event(fill)
    # $15K < both thresholds — nothing sent yet
    assert bot.sent == []

    await bot._on_fill_event(fill)
    # $30K total: RU user's $20K threshold crossed, EN user's $60K not
    recipients = [cid for cid, _ in bot.sent]
    assert recipients == [USER_RU]
    # RU buffer flushed, EN buffer keeps accumulating
    assert (USER_RU, WALLET, "ETH", "BUY") not in bot._fill_agg
    assert (USER_EN, WALLET, "ETH", "BUY") in bot._fill_agg


async def test_stale_buffer_is_flushed_below_threshold(bot):
    """A buffer that goes quiet must be delivered even if it never hit the threshold."""
    import time

    import config

    fill = FillEvent(
        wallet=WALLET, coin="ETH", side="BUY",
        size=1.0, price=3000, closed_pnl=0, fee=1.0,
        timestamp=int(time.time()), oid=1,
    )  # $3K — under both users' thresholds
    await bot._on_fill_event(fill)
    assert bot.sent == []
    key_ru = (USER_RU, WALLET, "ETH", "BUY")
    assert key_ru in bot._fill_agg

    # Not stale yet — nothing goes out.
    await bot._flush_stale_aggs()
    assert bot.sent == []

    # Backdate the buffers past the quiet period.
    for agg in bot._fill_agg.values():
        agg["last_ts"] -= config.FILL_AGG_FLUSH_SEC + 1
    await bot._flush_stale_aggs()

    assert sorted(cid for cid, _ in bot.sent) == [USER_RU, USER_EN]
    assert bot._fill_agg == {}


async def test_unsubscribe_refcounts_ws(bot):
    await bot._unsubscribe(USER_RU, WALLET)
    assert WALLET in bot.subscribers  # EN still subscribed
    await bot._unsubscribe(USER_EN, WALLET)
    assert WALLET not in bot.subscribers

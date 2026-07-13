"""Telegram message formatters (HTML parse mode). All texts via i18n."""
from __future__ import annotations

import html
import time
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot.i18n import duration_units, month_name, t
from database.storage import Position, Wallet
from hl_monitor.detector import AnomalyHit
from hl_monitor.parser import OrderEvent, PositionEvent, PositionSnapshot


# ---------------------------------------------------------------------------
#  inline keyboards
# ---------------------------------------------------------------------------

def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.wallets"), callback_data="m:wallets")],
        [InlineKeyboardButton(t(lang, "btn.positions"), callback_data="m:positions"),
         InlineKeyboardButton(t(lang, "btn.orders"), callback_data="m:orders")],
        [InlineKeyboardButton(t(lang, "btn.twap"), callback_data="m:twap"),
         InlineKeyboardButton(t(lang, "btn.stats"), callback_data="m:stats_menu")],
        [InlineKeyboardButton(t(lang, "btn.settings"), callback_data="m:settings"),
         InlineKeyboardButton(t(lang, "btn.help"), callback_data="m:help")],
    ])


def back_to_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.main_menu"), callback_data="m:menu")],
    ])


def wallets_list_keyboard(lang: str, wallets: list) -> InlineKeyboardMarkup:
    rows = []
    for w in wallets:
        em = "🟢" if w.active else "⏸"
        rows.append([InlineKeyboardButton(
            f"{em} {w.label}", callback_data=f"w:{w.address}")])
    rows.append([
        InlineKeyboardButton(t(lang, "btn.add_wallet"), callback_data="m:add"),
    ])
    rows.append([
        InlineKeyboardButton(t(lang, "btn.main_menu"), callback_data="m:menu"),
    ])
    return InlineKeyboardMarkup(rows)


def wallet_detail_keyboard(lang: str, wallet) -> InlineKeyboardMarkup:
    addr = wallet.address
    pause_btn = (
        InlineKeyboardButton(t(lang, "btn.pause"), callback_data=f"pa:{addr}")
        if wallet.active else
        InlineKeyboardButton(t(lang, "btn.resume"), callback_data=f"re:{addr}")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.positions"), callback_data=f"wp:{addr}"),
         InlineKeyboardButton(t(lang, "btn.orders"), callback_data=f"wo:{addr}")],
        [InlineKeyboardButton(t(lang, "btn.twap"), callback_data=f"wt:{addr}"),
         InlineKeyboardButton(t(lang, "btn.stats"), callback_data=f"ws:{addr}")],
        [InlineKeyboardButton(t(lang, "btn.rename"), callback_data=f"rn:{addr}"),
         pause_btn],
        [InlineKeyboardButton(t(lang, "btn.delete"), callback_data=f"rm:{addr}")],
        [InlineKeyboardButton(t(lang, "btn.back_to_list"), callback_data="m:wallets"),
         InlineKeyboardButton(t(lang, "btn.menu"), callback_data="m:menu")],
    ])


def stats_period_keyboard(lang: str, addr: str = "") -> InlineKeyboardMarkup:
    if addr:
        rows = [[
            InlineKeyboardButton(t(lang, "btn.24h"), callback_data=f"sp:{addr}:24h"),
            InlineKeyboardButton(t(lang, "btn.7d"), callback_data=f"sp:{addr}:7d"),
            InlineKeyboardButton(t(lang, "btn.30d"), callback_data=f"sp:{addr}:30d"),
        ], [
            InlineKeyboardButton(t(lang, "btn.back_to_wallet"), callback_data=f"w:{addr}"),
            InlineKeyboardButton(t(lang, "btn.menu"), callback_data="m:menu"),
        ]]
    else:
        rows = [[
            InlineKeyboardButton(t(lang, "btn.24h"), callback_data="sg:24h"),
            InlineKeyboardButton(t(lang, "btn.7d"), callback_data="sg:7d"),
            InlineKeyboardButton(t(lang, "btn.30d"), callback_data="sg:30d"),
        ], [
            InlineKeyboardButton(t(lang, "btn.menu"), callback_data="m:menu"),
        ]]
    return InlineKeyboardMarkup(rows)


def confirm_remove_keyboard(lang: str, addr: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.confirm_delete"), callback_data=f"cr:{addr}"),
         InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=f"w:{addr}")],
    ])


def cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.cancel"), callback_data="m:menu")],
    ])


def settings_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.lang_ru"), callback_data="st:lang:ru"),
         InlineKeyboardButton(t(lang, "btn.lang_en"), callback_data="st:lang:en")],
        [InlineKeyboardButton(t(lang, "btn.min_position"), callback_data="st:minpos"),
         InlineKeyboardButton(t(lang, "btn.agg_threshold"), callback_data="st:aggthr")],
        [InlineKeyboardButton(t(lang, "btn.main_menu"), callback_data="m:menu")],
    ])


# ---------------------------------------------------------------------------
#  menu screen texts
# ---------------------------------------------------------------------------

def main_menu_text(lang: str) -> str:
    return t(lang, "menu.main")


def wallets_list_text(lang: str, wallets: list) -> str:
    if not wallets:
        return t(lang, "wallets.empty")
    active = sum(1 for w in wallets if w.active)
    return t(lang, "wallets.header", total=len(wallets), active=active,
             paused=len(wallets) - active)


def wallet_detail_text(
    lang: str, wallet, positions: dict, orders: list,
    balance: float = 0.0,
    pnl_24h: float = 0.0, pnl_7d: float = 0.0,
    pnl_30d: float = 0.0, pnl_all: float = 0.0,
) -> str:
    status = t(lang, "wallet.status_active" if wallet.active
               else "wallet.status_paused")
    upnl = sum(p.unrealized_pnl for p in positions.values())
    head = (
        f"👤 <a href=\"{hyperdash_link(wallet.address)}\"><b>{esc(wallet.label)}</b></a>\n"
        f"<code>{wallet.address}</code>\n\n"
    )
    return head + t(
        lang, "wallet.detail",
        status=status, balance=fmt_usd(balance),
        positions=len(positions), upnl=fmt_usd_signed(upnl),
        orders=len(orders),
        pnl_24h=fmt_usd_signed(pnl_24h), pnl_7d=fmt_usd_signed(pnl_7d),
        pnl_30d=fmt_usd_signed(pnl_30d), pnl_all=fmt_usd_signed(pnl_all),
    )


def add_wallet_prompt(lang: str) -> str:
    return t(lang, "add.prompt")


def rename_prompt_text(lang: str, wallet) -> str:
    return t(lang, "rename.prompt", label=esc(wallet.label),
             addr=short_addr(wallet.address))


def confirm_remove_text(lang: str, wallet) -> str:
    return t(lang, "remove.confirm", label=esc(wallet.label),
             addr=wallet.address)


def stats_menu_text(lang: str) -> str:
    return t(lang, "stats.menu")


def wallet_stats_menu_text(lang: str, wallet) -> str:
    return t(lang, "stats.wallet_menu", label=esc(wallet.label))


def settings_text(lang: str, user) -> str:
    return t(lang, "settings.screen",
             lang=t(lang, "settings.lang_name"),
             min_pos=fmt_usd(user.min_position_usd),
             agg_thr=fmt_usd(user.fill_agg_threshold))


def help_text(lang: str) -> str:
    return t(lang, "help")


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    """Escape dynamic text for Telegram HTML."""
    return html.escape(str(s), quote=False)


def short_addr(addr: str) -> str:
    addr = addr.lower()
    if not addr.startswith("0x") or len(addr) < 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"


def hyperdash_link(addr: str) -> str:
    return f"{config.HYPERDASH_URL}{addr.lower()}"


def wallet_line(label: str, addr: str) -> str:
    """'👤 <a href=hyperdash>label</a> (<code>0xabc...def</code>)' — used in notifications."""
    return (f'👤 <a href="{hyperdash_link(addr)}">{esc(label)}</a> '
            f'(<code>{short_addr(addr)}</code>)')


_TZ_OFFSET_SEC = config.TZ_OFFSET_HOURS * 3600
_TZ_SUFFIX = (f"GMT+{config.TZ_OFFSET_HOURS}" if config.TZ_OFFSET_HOURS >= 0
              else f"GMT{config.TZ_OFFSET_HOURS}")


def fmt_time_hhmm(ts: int) -> str:
    """Format unix timestamp (seconds) as HH:MM in the configured timezone."""
    return time.strftime("%H:%M", time.gmtime(ts + _TZ_OFFSET_SEC))


def fmt_datetime(ts: int, lang: str = "en") -> str:
    """Format unix timestamp as 'DD mon, HH:MM' in the configured timezone."""
    tm = time.gmtime(ts + _TZ_OFFSET_SEC)
    return (f"{tm.tm_mday} {month_name(lang, tm.tm_mon)}, "
            f"{tm.tm_hour:02d}:{tm.tm_min:02d}")


def fmt_time_range(first_ts: int, last_ts: int) -> str:
    if first_ts == last_ts or (last_ts - first_ts) < 60:
        return fmt_time_hhmm(last_ts)
    return f"{fmt_time_hhmm(first_ts)} – {fmt_time_hhmm(last_ts)}"


def fmt_usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1_000_000:
        return f"{sign}${x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{sign}${x/1_000:.1f}K"
    return f"{sign}${x:,.0f}"


def fmt_usd_signed(x: float) -> str:
    if x > 0:
        return f"+{fmt_usd(x)}"
    if x < 0:
        return f"-{fmt_usd(abs(x))}"
    return "$0"


def fmt_price(x: float) -> str:
    if x == 0:
        return "0"
    if x >= 1000:
        return f"${x:,.2f}"
    if x >= 1:
        return f"${x:,.4f}"
    return f"${x:.6f}"


def fmt_duration(seconds: Optional[int], lang: str = "en") -> str:
    if not seconds:
        return "—"
    uh, um, us = duration_units(lang)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}{uh} {m}{um}"
    if m:
        return f"{m}{um} {s}{us}"
    return f"{s}{us}"


def side_emoji(side: str) -> str:
    return "🟢" if side.upper() == "LONG" else "🔴"


# ---------------------------------------------------------------------------
#  position events
# ---------------------------------------------------------------------------

def format_position_open(lang: str, ev: PositionEvent, label: str) -> str:
    side_word = ev.side.upper()
    em = side_emoji(side_word)
    leverage = f"{ev.leverage:g}x" if ev.leverage else "—"
    return (
        f"{t(lang, 'ev.position_opened')}\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"{t(lang, 'ev.coin')}: <b>{esc(ev.coin)}</b>\n"
        f"{t(lang, 'ev.direction')}: <b>{esc(side_word)}</b> {em}\n"
        f"{t(lang, 'ev.size')}: <b>{fmt_usd(ev.notional)}</b>\n"
        f"{t(lang, 'ev.entry_price')}: {fmt_price(ev.entry_price)}\n"
        f"{t(lang, 'ev.leverage')}: {leverage}"
    )


def format_position_close(lang: str, ev: PositionEvent, label: str) -> str:
    pnl = ev.pnl or 0.0
    pnl_emoji = "✅" if pnl >= 0 else "❌"
    pnl_str = f"{fmt_usd_signed(pnl)} {pnl_emoji}"
    close_px = fmt_price(ev.close_price) if ev.close_price else "—"
    return (
        f"{t(lang, 'ev.position_closed')}\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"{t(lang, 'ev.coin')}: <b>{esc(ev.coin)}</b> ({esc(ev.side)})\n"
        f"{t(lang, 'ev.entry_price')}: {fmt_price(ev.entry_price)}\n"
        f"{t(lang, 'ev.exit_price')}: {close_px}\n"
        f"{t(lang, 'ev.result')}: <b>{pnl_str}</b>\n"
        f"{t(lang, 'ev.holding')}: {fmt_duration(ev.holding_seconds, lang)}"
    )


def format_position_scaled(lang: str, ev: PositionEvent, label: str,
                           prev_size: float, prev_notional: float) -> str:
    title = t(lang, "ev.position_increased" if ev.size > prev_size
              else "ev.position_decreased")
    delta_usd = ev.notional - prev_notional
    lev_line = (f"\n{t(lang, 'ev.leverage')}: {ev.leverage:g}x"
                if ev.leverage else "")
    return (
        f"{title}\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"{t(lang, 'ev.coin')}: <b>{esc(ev.coin)}</b> ({esc(ev.side)})\n"
        f"{t(lang, 'ev.size')}: {fmt_usd(prev_notional)} → <b>{fmt_usd(ev.notional)}</b> "
        f"({fmt_usd_signed(delta_usd)})\n"
        f"{t(lang, 'ev.entry_price')}: {fmt_price(ev.entry_price)}"
        f"{lev_line}"
    )


# ---------------------------------------------------------------------------
#  order events
# ---------------------------------------------------------------------------

def format_order_placed(lang: str, ev: OrderEvent, label: str) -> str:
    cur = ""
    if ev.current_price and ev.price:
        delta_pct = (ev.current_price - ev.price) / ev.price * 100
        sign = "+" if delta_pct >= 0 else ""
        cur = (f"\n{t(lang, 'ev.current_price')}: "
               f"{fmt_price(ev.current_price)} ({sign}{delta_pct:.2f}%)")
    return (
        f"{t(lang, 'ev.order_placed')}\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"{t(lang, 'ev.order_type')}: <b>{esc(ev.type)}</b>\n"
        f"{t(lang, 'ev.coin')}: <b>{esc(ev.coin)}</b>\n"
        f"{t(lang, 'ev.size')}: <b>{fmt_usd(ev.notional)}</b>\n"
        f"{t(lang, 'ev.order_price')}: {fmt_price(ev.price)}"
        f"{cur}"
    )


def format_order_canceled(lang: str, ev: OrderEvent, label: str) -> str:
    return (
        f"{t(lang, 'ev.order_canceled')}\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"{t(lang, 'ev.order_type')}: {esc(ev.type)} • {esc(ev.coin)}\n"
        f"{t(lang, 'ev.size')}: {fmt_usd(ev.notional)} @ {fmt_price(ev.price)}"
    )


def format_order_filled(lang: str, ev: OrderEvent, label: str) -> str:
    return (
        f"{t(lang, 'ev.order_filled')}\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"{t(lang, 'ev.order_type')}: {esc(ev.type)} • {esc(ev.coin)}\n"
        f"{t(lang, 'ev.size')}: {fmt_usd(ev.notional)} @ {fmt_price(ev.price)}"
    )


# ---------------------------------------------------------------------------
#  aggregated fills
# ---------------------------------------------------------------------------

def _agg_action(lang: str, agg: dict) -> tuple[str, str]:
    """Determine (title, emoji) from aggregated fills.

    Logic:
      BUY  + has close fills  → closing SHORT (cover)
      BUY  + no close fills   → opening LONG
      SELL + has close fills  → closing LONG
      SELL + no close fills   → opening SHORT
    """
    side = agg["side"]
    has_close = agg.get("close_fills", 0) > 0
    has_open = agg.get("open_fills", 0) > 0
    is_buy = side == "BUY"

    if has_close and has_open:
        # mixed — show the dominant by notional volume
        if agg.get("close_notional", 0) > agg.get("open_notional", 0):
            has_open = False
        else:
            has_close = False

    if is_buy and has_close:
        return t(lang, "agg.close_short"), "🟢"
    if is_buy:
        return t(lang, "agg.open_long"), "🟢"
    if has_close:
        return t(lang, "agg.close_long"), "🔴"
    return t(lang, "agg.open_short"), "🔴"


def format_fills_aggregated(lang: str, agg: dict, label: str) -> str:
    coin = esc(agg["coin"])
    title, em = _agg_action(lang, agg)
    pnl_line = ""
    if agg.get("total_pnl"):
        pnl_line = f"\nP&amp;L: <b>{fmt_usd_signed(agg['total_pnl'])}</b>"
    fee_line = ""
    if agg.get("total_fee"):
        fee_line = f"\n{t(lang, 'agg.fee')}: {fmt_usd(agg['total_fee'])}"
    time_line = ""
    first_ts = agg.get("first_ts")
    last_ts = agg.get("last_ts")
    if first_ts and last_ts:
        time_line = (f"\n{t(lang, 'agg.trade_time')}: "
                     f"{fmt_time_range(first_ts, last_ts)}")
    pos_line = ""
    pos_entry = agg.get("position_entry_price")
    pos_notional = agg.get("position_notional")
    if pos_entry:
        pos_line = (f"\n<b>{t(lang, 'agg.whole_position')}:</b> "
                    f"{fmt_usd(pos_notional or 0)} @ {fmt_price(pos_entry)}")
    return (
        f"<b>{title}</b> {em}\n"
        f"{wallet_line(label, agg['wallet'])}\n"
        f"{t(lang, 'ev.coin')}: <b>{coin}</b>\n"
        f"{t(lang, 'agg.tx_count')}: <b>{agg['count']}</b>\n"
        f"{t(lang, 'agg.total_volume')}: <b>{fmt_usd(agg['total_notional'])}</b>\n"
        f"{t(lang, 'agg.total_size')}: {agg['total_size']:.4g}\n"
        f"{t(lang, 'agg.avg_price')}: {fmt_price(agg['avg_price'])}"
        f"{pos_line}{pnl_line}{fee_line}{time_line}"
    )


# ---------------------------------------------------------------------------
#  anomaly
# ---------------------------------------------------------------------------

def format_anomaly(lang: str, hit: AnomalyHit,
                   labels: dict[str, str]) -> str:
    lines = [
        t(lang, "anomaly.title"),
        t(lang, "anomaly.body", n=len(hit.wallets),
          side=esc(hit.side), coin=esc(hit.coin)),
        "",
    ]
    for addr, label, notional in hit.wallets:
        nice = labels.get(addr, label) or short_addr(addr)
        lines.append(f"👤 {esc(nice)} — <b>{fmt_usd(notional)}</b>")
    lines.append("")
    lines.append(f"{t(lang, 'anomaly.total')}: <b>{fmt_usd(hit.total_notional)}</b>")
    minutes = max(1, hit.interval_seconds // 60)
    lines.append(t(lang, "anomaly.interval", minutes=minutes))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /positions — active positions + open orders
# ---------------------------------------------------------------------------

def format_active_positions(
    lang: str,
    per_wallet: list[tuple[str, str, dict[str, PositionSnapshot]]],
) -> str:
    """per_wallet: list of (label, address, positions_by_coin)."""
    total_pos = sum(len(pos) for _, _, pos in per_wallet)
    total_pnl = sum(
        snap.unrealized_pnl
        for _, _, positions in per_wallet
        for snap in positions.values()
    )

    if not total_pos:
        return t(lang, "pos.none")

    lines = [t(lang, "pos.header"), ""]

    for label, addr, positions in per_wallet:
        if not positions:
            continue
        lines.append(f"{wallet_line(label, addr)}")
        for coin, snap in positions.items():
            em = side_emoji(snap.side)
            u = snap.unrealized_pnl
            pnl_em = "🟢" if u >= 0 else "🔴"
            lev = f" {snap.leverage:g}x" if snap.leverage else ""
            lines.append(
                f"  {em} <b>{esc(coin)}</b> {esc(snap.side)}{lev} — "
                f"{fmt_usd(snap.notional)} @ {fmt_price(snap.entry_price)} "
                f"({fmt_usd_signed(u)} {pnl_em})"
            )
            # Liquidation price line — only if Hyperliquid actually returned one
            if snap.liquidation_price and snap.entry_price:
                dist_pct = abs(snap.liquidation_price - snap.entry_price) \
                           / snap.entry_price * 100
                warn = "⚠️ " if dist_pct < 5 else ""
                lines.append(t(lang, "pos.liquidation",
                               price=fmt_price(snap.liquidation_price),
                               warn=warn, pct=dist_pct))
            elif snap.liquidation_price == 0 and snap.entry_price:
                lines.append(t(lang, "pos.liq_safe"))
        lines.append("")

    lines.append(t(lang, "pos.total", n=total_pos,
                   pnl=fmt_usd_signed(total_pnl)))
    return "\n".join(lines)


def format_twap_fills(
    lang: str,
    per_wallet: list[tuple[str, str, list]],
    days: int = 7,
) -> str:
    """per_wallet: list of (label, address, list of TwapSliceFill)."""
    total = sum(len(fills) for _, _, fills in per_wallet)
    if not total:
        return t(lang, "twap.none", days=days)

    lines = [t(lang, "twap.header", days=days), ""]
    grand_volume = 0.0
    grand_fee = 0.0
    for label, addr, fills in per_wallet:
        if not fills:
            continue
        # group by (twap_id, coin, side) — one TWAP run per group
        groups: dict[tuple, list] = {}
        for f in fills:
            groups.setdefault((f.twap_id, f.coin, f.side), []).append(f)

        lines.append(wallet_line(label, addr))
        for (twap_id, coin, side), slices in groups.items():
            slices.sort(key=lambda x: x.time)
            total_sz = sum(s.size for s in slices)
            total_notional = sum(s.size * s.price for s in slices)
            avg_px = (total_notional / total_sz) if total_sz else 0
            total_fee = sum(s.fee for s in slices)
            grand_volume += total_notional
            grand_fee += total_fee
            em = "🟢" if side == "BUY" else "🔴"
            first = slices[0].time
            last = slices[-1].time
            when = (fmt_datetime(first, lang) if first == last
                    else f"{fmt_datetime(first, lang)} – {fmt_time_hhmm(last)}")
            lines.append(
                f"  {em} <b>{esc(coin)}</b> {esc(side)} • "
                f"{len(slices)} {t(lang, 'twap.slices')}\n"
                f"     {fmt_usd(total_notional)} @ {fmt_price(avg_px)}, "
                f"{t(lang, 'twap.fee')} {fmt_usd(total_fee)}\n"
                f"     {when} {_TZ_SUFFIX}"
            )
        lines.append("")

    lines.append(t(lang, "twap.total", n=total,
                   volume=fmt_usd(grand_volume), fee=fmt_usd(grand_fee)))
    return "\n".join(lines)


def format_active_orders(
    lang: str,
    per_wallet: list[tuple[str, str, list[dict]]],
) -> str:
    """per_wallet: list of (label, address, raw_open_orders)."""
    total_ord = sum(len(ords) for _, _, ords in per_wallet)
    if not total_ord:
        return t(lang, "ord.none")

    lines = [t(lang, "ord.header"), ""]
    total_notional = 0.0
    for label, addr, orders in per_wallet:
        if not orders:
            continue
        lines.append(f"{wallet_line(label, addr)}")
        for o in orders:
            sz = float(o.get("sz") or 0)
            px = float(o.get("limitPx") or 0)
            notional = sz * px
            total_notional += notional
            side = "BUY" if str(o.get("side", "")).upper().startswith("B") else "SELL"
            em = "🟢" if side == "BUY" else "🔴"
            lines.append(
                f"  {em} <b>{esc(o.get('coin', ''))}</b> LIMIT {side} — "
                f"{fmt_usd(notional)} @ {fmt_price(px)}"
            )
        lines.append("")

    lines.append(t(lang, "ord.total", n=total_ord,
                   notional=fmt_usd(total_notional)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /list
# ---------------------------------------------------------------------------

def format_wallet_list(lang: str, wallets: list[Wallet]) -> str:
    if not wallets:
        return t(lang, "list.empty")
    active = [w for w in wallets if w.active]
    paused = [w for w in wallets if not w.active]

    lines = [t(lang, "list.header", n=len(wallets)), ""]
    for w in active:
        lines.append(f"🟢 <b>{esc(w.label)}</b> — <code>{short_addr(w.address)}</code>")
    for w in paused:
        lines.append(f"⏸ {esc(w.label)} — <code>{short_addr(w.address)}</code>")
    lines.append("")
    lines.append(t(lang, "list.footer", active=len(active), paused=len(paused)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /stats
# ---------------------------------------------------------------------------

def format_stats(
    lang: str,
    label: str,
    closed: list[Position],
    open_positions: list[Position],
    period_label: str = "24h",
    unrealized: dict[str, float] | None = None,
) -> str:
    n = len(closed)
    profitable = [p for p in closed if (p.pnl or 0) > 0]
    win_rate = (len(profitable) / n * 100) if n else 0
    pnl_total = sum((p.pnl or 0) for p in closed)
    unrealized = unrealized or {}

    best = max(closed, key=lambda p: (p.pnl or 0)) if closed else None
    worst = min(closed, key=lambda p: (p.pnl or 0)) if closed else None

    lines = [f"📊 <b>{esc(label)}</b> — {esc(period_label)}", ""]
    lines.append(t(lang, "stats.trades", n=n))
    if n:
        lines.append(t(lang, "stats.profitable", n=len(profitable),
                       rate=win_rate))
    lines.append("")
    lines.append(f"💰 P&L: <b>{fmt_usd_signed(pnl_total)}</b>")
    if best and (best.pnl or 0) > 0:
        lines.append(t(lang, "stats.best", pnl=fmt_usd_signed(best.pnl or 0),
                       coin=esc(best.coin), side=best.side.lower()))
    if worst and (worst.pnl or 0) < 0:
        lines.append(t(lang, "stats.worst", pnl=fmt_usd_signed(worst.pnl or 0),
                       coin=esc(worst.coin), side=worst.side.lower()))

    if open_positions:
        lines.append("")
        lines.append(t(lang, "stats.open_positions"))
        for p in open_positions:
            upnl = unrealized.get(p.coin, p.pnl or 0)
            em = "🟢" if upnl >= 0 else "🔴"
            lines.append(
                f"• {esc(p.coin)} {esc(p.side)} {fmt_usd(p.notional)} "
                f"({fmt_usd_signed(upnl)} {em})"
            )
    return "\n".join(lines)


def format_global_stats(
    lang: str,
    per_wallet: list[tuple[str, list[Position], list[Position]]],
    period_label: str = "24h",
) -> str:
    lines = [t(lang, "stats.global_header", period=esc(period_label)), ""]
    total_trades = 0
    total_profitable = 0
    total_pnl = 0.0
    open_count = 0
    for label, closed, opens in per_wallet:
        total_trades += len(closed)
        total_profitable += sum(1 for p in closed if (p.pnl or 0) > 0)
        total_pnl += sum((p.pnl or 0) for p in closed)
        open_count += len(opens)

    win_rate = (total_profitable / total_trades * 100) if total_trades else 0
    lines.append(t(lang, "stats.wallets_count", n=len(per_wallet)))
    lines.append(t(lang, "stats.trades", n=total_trades))
    if total_trades:
        lines.append(t(lang, "stats.profitable", n=total_profitable,
                       rate=win_rate))
    lines.append(t(lang, "stats.total_pnl", pnl=fmt_usd_signed(total_pnl)))
    lines.append(t(lang, "stats.open_count", n=open_count))

    if per_wallet:
        lines.append("")
        lines.append(t(lang, "stats.by_wallet"))
        for label, closed, opens in per_wallet:
            wp = sum((p.pnl or 0) for p in closed)
            lines.append(t(lang, "stats.wallet_line", label=esc(label),
                           trades=len(closed), pnl=fmt_usd_signed(wp),
                           open=len(opens)))
    return "\n".join(lines)

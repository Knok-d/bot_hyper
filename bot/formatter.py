"""Telegram message formatters (HTML parse mode)."""
from __future__ import annotations

import html
import time
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database.storage import Order, Position, Wallet
from hl_monitor.detector import AnomalyHit
from hl_monitor.parser import OrderEvent, PositionEvent, PositionSnapshot


# ---------------------------------------------------------------------------
#  inline keyboard
# ---------------------------------------------------------------------------

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Кошельки", callback_data="m:wallets")],
        [InlineKeyboardButton("📈 Позиции", callback_data="m:positions"),
         InlineKeyboardButton("🎯 Ордера", callback_data="m:orders")],
        [InlineKeyboardButton("📊 TWAP", callback_data="m:twap"),
         InlineKeyboardButton("📊 Статистика", callback_data="m:stats_menu")],
        [InlineKeyboardButton("❓ Помощь", callback_data="m:help")],
    ])


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="m:menu")],
    ])


def wallets_list_keyboard(wallets: list) -> InlineKeyboardMarkup:
    rows = []
    for w in wallets:
        em = "🟢" if w.active else "⏸"
        rows.append([InlineKeyboardButton(
            f"{em} {w.label}", callback_data=f"w:{w.address}")])
    rows.append([
        InlineKeyboardButton("➕ Добавить кошелёк", callback_data="m:add"),
    ])
    rows.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="m:menu"),
    ])
    return InlineKeyboardMarkup(rows)


def wallet_detail_keyboard(wallet) -> InlineKeyboardMarkup:
    addr = wallet.address
    pause_btn = (
        InlineKeyboardButton("⏸ Пауза", callback_data=f"pa:{addr}")
        if wallet.active else
        InlineKeyboardButton("▶️ Возобновить", callback_data=f"re:{addr}")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Позиции", callback_data=f"wp:{addr}"),
         InlineKeyboardButton("🎯 Ордера", callback_data=f"wo:{addr}")],
        [InlineKeyboardButton("📊 TWAP", callback_data=f"wt:{addr}"),
         InlineKeyboardButton("📊 Статистика", callback_data=f"ws:{addr}")],
        [InlineKeyboardButton("✏️ Переименовать", callback_data=f"rn:{addr}"),
         pause_btn],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"rm:{addr}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data="m:wallets"),
         InlineKeyboardButton("🏠 Меню", callback_data="m:menu")],
    ])


def stats_period_keyboard(addr: str = "") -> InlineKeyboardMarkup:
    if addr:
        rows = [[
            InlineKeyboardButton("24ч", callback_data=f"sp:{addr}:24h"),
            InlineKeyboardButton("7д", callback_data=f"sp:{addr}:7d"),
            InlineKeyboardButton("30д", callback_data=f"sp:{addr}:30d"),
        ], [
            InlineKeyboardButton("⬅️ К кошельку", callback_data=f"w:{addr}"),
            InlineKeyboardButton("🏠 Меню", callback_data="m:menu"),
        ]]
    else:
        rows = [[
            InlineKeyboardButton("24ч", callback_data="sg:24h"),
            InlineKeyboardButton("7д", callback_data="sg:7d"),
            InlineKeyboardButton("30д", callback_data="sg:30d"),
        ], [
            InlineKeyboardButton("🏠 Меню", callback_data="m:menu"),
        ]]
    return InlineKeyboardMarkup(rows)


def confirm_remove_keyboard(addr: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"cr:{addr}"),
         InlineKeyboardButton("❌ Отмена", callback_data=f"w:{addr}")],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="m:menu")],
    ])


# ---------------------------------------------------------------------------
#  menu screen texts
# ---------------------------------------------------------------------------

MAIN_MENU_TEXT = (
    "🤖 <b>Hyperliquid Wallet Tracker</b>\n\n"
    "Выберите действие в меню ниже."
)


def wallets_list_text(wallets: list) -> str:
    if not wallets:
        return ("📋 <b>Кошельки</b>\n\n"
                "Список пуст. Нажмите <b>➕ Добавить</b>, чтобы начать.")
    active = sum(1 for w in wallets if w.active)
    paused = len(wallets) - active
    return (
        f"📋 <b>Кошельки</b>\n\n"
        f"Всего: <b>{len(wallets)}</b> | "
        f"Активных: <b>{active}</b> | "
        f"На паузе: <b>{paused}</b>\n\n"
        f"Выберите кошелёк для управления:"
    )


def wallet_detail_text(
    wallet, positions: dict, orders: list,
    balance: float = 0.0,
    pnl_24h: float = 0.0, pnl_7d: float = 0.0,
    pnl_30d: float = 0.0, pnl_all: float = 0.0,
) -> str:
    status = "🟢 Активен" if wallet.active else "⏸ На паузе"
    upnl = sum(p.unrealized_pnl for p in positions.values())
    return (
        f"👤 <a href=\"{hyperdash_link(wallet.address)}\"><b>{esc(wallet.label)}</b></a>\n"
        f"<code>{wallet.address}</code>\n\n"
        f"Статус: {status}\n"
        f"💼 Баланс: <b>{fmt_usd(balance)}</b>\n\n"
        f"📂 Позиций: <b>{len(positions)}</b>\n"
        f"📈 Unrealized PnL: <b>{fmt_usd_signed(upnl)}</b>\n"
        f"🎯 Ордеров: <b>{len(orders)}</b>\n\n"
        f"<b>Realized PnL:</b>\n"
        f"  24ч:    {fmt_usd_signed(pnl_24h)}\n"
        f"  7д:     {fmt_usd_signed(pnl_7d)}\n"
        f"  30д:    {fmt_usd_signed(pnl_30d)}\n"
        f"  Весь:   {fmt_usd_signed(pnl_all)}"
    )


ADD_WALLET_PROMPT = (
    "➕ <b>Добавление кошелька</b>\n\n"
    "Отправьте сообщение в формате:\n"
    "<code>0x... [метка]</code>\n\n"
    "Пример:\n"
    "<code>0x84b36f07a6547b1d6a2414240db69d9bbd0ee01f Whale1</code>\n\n"
    "Метка — необязательна."
)


def rename_prompt_text(wallet) -> str:
    return (
        f"✏️ <b>Переименование кошелька</b>\n\n"
        f"Текущая метка: <b>{esc(wallet.label)}</b>\n"
        f"Адрес: <code>{short_addr(wallet.address)}</code>\n\n"
        f"Отправьте новое имя сообщением."
    )


def confirm_remove_text(wallet) -> str:
    return (
        f"🗑 <b>Удалить кошелёк?</b>\n\n"
        f"Метка: <b>{esc(wallet.label)}</b>\n"
        f"Адрес: <code>{wallet.address}</code>\n\n"
        f"История транзакций сохранится."
    )


STATS_MENU_TEXT = (
    "📊 <b>Статистика</b>\n\n"
    "Выберите период (по всем активным кошелькам):"
)


def wallet_stats_menu_text(wallet) -> str:
    return (
        f"📊 <b>Статистика — {esc(wallet.label)}</b>\n\n"
        f"Выберите период:"
    )


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

_RU_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
              "июл", "авг", "сен", "окт", "ноя", "дек"]


def fmt_time_hhmm(ts: int) -> str:
    """Format unix timestamp (seconds) as HH:MM in the configured timezone."""
    return time.strftime("%H:%M", time.gmtime(ts + _TZ_OFFSET_SEC))


def fmt_datetime(ts: int) -> str:
    """Format unix timestamp as 'DD мес, HH:MM' in the configured timezone."""
    tm = time.gmtime(ts + _TZ_OFFSET_SEC)
    return f"{tm.tm_mday} {_RU_MONTHS[tm.tm_mon - 1]}, {tm.tm_hour:02d}:{tm.tm_min:02d}"


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


def fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m}мин"
    if m:
        return f"{m}мин {s}с"
    return f"{s}с"


def side_emoji(side: str) -> str:
    return "🟢" if side.upper() == "LONG" else "🔴"


# ---------------------------------------------------------------------------
#  position events
# ---------------------------------------------------------------------------

def format_position_open(ev: PositionEvent, label: str) -> str:
    side_word = ev.side.upper()
    em = side_emoji(side_word)
    leverage = f"{ev.leverage:g}x" if ev.leverage else "—"
    return (
        f"📈 <b>ОТКРЫТА ПОЗИЦИЯ</b>\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"Монета: <b>{esc(ev.coin)}</b>\n"
        f"Направление: <b>{esc(side_word)}</b> {em}\n"
        f"Размер: <b>{fmt_usd(ev.notional)}</b>\n"
        f"Цена входа: {fmt_price(ev.entry_price)}\n"
        f"Плечо: {leverage}"
    )


def format_position_close(ev: PositionEvent, label: str) -> str:
    pnl = ev.pnl or 0.0
    pnl_emoji = "✅" if pnl >= 0 else "❌"
    pnl_str = f"{fmt_usd_signed(pnl)} {pnl_emoji}"
    close_px = fmt_price(ev.close_price) if ev.close_price else "—"
    return (
        f"📉 <b>ЗАКРЫТА ПОЗИЦИЯ</b>\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"Монета: <b>{esc(ev.coin)}</b> ({esc(ev.side)})\n"
        f"Цена входа: {fmt_price(ev.entry_price)}\n"
        f"Цена выхода: {close_px}\n"
        f"Результат: <b>{pnl_str}</b>\n"
        f"Удержание: {fmt_duration(ev.holding_seconds)}"
    )


def format_position_scaled(ev: PositionEvent, label: str,
                           prev_size: float, prev_notional: float) -> str:
    direction = "увеличена" if ev.size > prev_size else "уменьшена"
    delta_usd = ev.notional - prev_notional
    lev_line = f"\nПлечо: {ev.leverage:g}x" if ev.leverage else ""
    return (
        f"📐 <b>ПОЗИЦИЯ {esc(direction.upper())}</b>\n"
        f"{wallet_line(label, ev.wallet)}\n"
        f"Монета: <b>{esc(ev.coin)}</b> ({esc(ev.side)})\n"
        f"Размер: {fmt_usd(prev_notional)} → <b>{fmt_usd(ev.notional)}</b> "
        f"({fmt_usd_signed(delta_usd)})\n"
        f"Цена входа: {fmt_price(ev.entry_price)}"
        f"{lev_line}"
    )


# ---------------------------------------------------------------------------
#  order events
# ---------------------------------------------------------------------------

def format_order_placed(ev: OrderEvent, label: str) -> str:
    cur = ""
    if ev.current_price and ev.price:
        delta_pct = (ev.current_price - ev.price) / ev.price * 100
        sign = "+" if delta_pct >= 0 else ""
        cur = f"\nТекущая цена: {fmt_price(ev.current_price)} ({sign}{delta_pct:.2f}%)"
    return (
        f"🎯 <b>ВЫСТАВЛЕН ОРДЕР</b>\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"Тип: <b>{esc(ev.type)}</b>\n"
        f"Монета: <b>{esc(ev.coin)}</b>\n"
        f"Размер: <b>{fmt_usd(ev.notional)}</b>\n"
        f"Цена ордера: {fmt_price(ev.price)}"
        f"{cur}"
    )


def format_order_canceled(ev: OrderEvent, label: str) -> str:
    return (
        f"🚫 <b>ОТМЕНЁН ОРДЕР</b>\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"Тип: {esc(ev.type)} • {esc(ev.coin)}\n"
        f"Размер: {fmt_usd(ev.notional)} @ {fmt_price(ev.price)}"
    )


def format_order_filled(ev: OrderEvent, label: str) -> str:
    return (
        f"✅ <b>ИСПОЛНЕН ОРДЕР</b>\n"
        f"👤 {esc(label)} (<code>{short_addr(ev.wallet)}</code>)\n"
        f"Тип: {esc(ev.type)} • {esc(ev.coin)}\n"
        f"Размер: {fmt_usd(ev.notional)} @ {fmt_price(ev.price)}"
    )


# ---------------------------------------------------------------------------
#  aggregated fills
# ---------------------------------------------------------------------------

def _agg_action(agg: dict) -> tuple[str, str, str]:
    """Determine (title, emoji, direction) from aggregated fills.

    Logic:
      BUY  + has close fills  → 'Закрытие SHORT' (cover)
      BUY  + no close fills   → 'Открытие LONG'
      SELL + has close fills  → 'Закрытие LONG'
      SELL + no close fills   → 'Открытие SHORT'
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
        return "📈 ЗАКРЫТИЕ SHORT", "🟢", "SHORT"
    if is_buy:
        return "📈 ОТКРЫТИЕ LONG", "🟢", "LONG"
    if has_close:
        return "📉 ЗАКРЫТИЕ LONG", "🔴", "LONG"
    return "📉 ОТКРЫТИЕ SHORT", "🔴", "SHORT"


def format_fills_aggregated(agg: dict, label: str) -> str:
    coin = esc(agg["coin"])
    title, em, _ = _agg_action(agg)
    pnl_line = ""
    if agg.get("total_pnl"):
        pnl_line = f"\nP&amp;L: <b>{fmt_usd_signed(agg['total_pnl'])}</b>"
    fee_line = ""
    if agg.get("total_fee"):
        fee_line = f"\nКомиссия: {fmt_usd(agg['total_fee'])}"
    time_line = ""
    first_ts = agg.get("first_ts")
    last_ts = agg.get("last_ts")
    if first_ts and last_ts:
        time_line = f"\nВремя сделок: {fmt_time_range(first_ts, last_ts)}"
    pos_line = ""
    pos_entry = agg.get("position_entry_price")
    pos_notional = agg.get("position_notional")
    if pos_entry:
        pos_line = (f"\n<b>Позиция целиком:</b> "
                    f"{fmt_usd(pos_notional or 0)} @ {fmt_price(pos_entry)}")
    return (
        f"<b>{title}</b> {em}\n"
        f"{wallet_line(label, agg['wallet'])}\n"
        f"Монета: <b>{coin}</b>\n"
        f"Транзакций: <b>{agg['count']}</b>\n"
        f"Общий объём: <b>{fmt_usd(agg['total_notional'])}</b>\n"
        f"Суммарный размер: {agg['total_size']:.4g}\n"
        f"Средняя цена сделок: {fmt_price(agg['avg_price'])}"
        f"{pos_line}{pnl_line}{fee_line}{time_line}"
    )


# ---------------------------------------------------------------------------
#  anomaly
# ---------------------------------------------------------------------------

def format_anomaly(hit: AnomalyHit, labels: dict[str, str]) -> str:
    lines = [
        "⚡️ <b>СОВПАДЕНИЕ!</b>",
        f"{len(hit.wallets)} твоих кита открыли <b>{esc(hit.side)}</b> "
        f"на <b>{esc(hit.coin)}</b> одновременно",
        "",
    ]
    for addr, label, notional in hit.wallets:
        nice = labels.get(addr, label) or short_addr(addr)
        lines.append(f"👤 {esc(nice)} — <b>{fmt_usd(notional)}</b>")
    lines.append("")
    lines.append(f"Суммарно: <b>{fmt_usd(hit.total_notional)}</b>")
    minutes = max(1, hit.interval_seconds // 60)
    lines.append(f"Интервал: {minutes} мин")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /positions — active positions + open orders
# ---------------------------------------------------------------------------

def format_active_positions(
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
        return "📈 Нет активных позиций."

    lines = ["📈 <b>АКТИВНЫЕ ПОЗИЦИИ</b>", ""]

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
                lines.append(
                    f"     💀 Ликвидация: {fmt_price(snap.liquidation_price)} "
                    f"({warn}{dist_pct:.1f}% от входа)"
                )
            elif snap.liquidation_price == 0 and snap.entry_price:
                lines.append("     💀 Ликвидация: — (вне риска)")
        lines.append("")

    lines.append(f"Всего позиций: <b>{total_pos}</b> "
                 f"({fmt_usd_signed(total_pnl)})")
    return "\n".join(lines)


def format_twap_fills(
    per_wallet: list[tuple[str, str, list]],
    days: int = 7,
) -> str:
    """per_wallet: list of (label, address, list of TwapSliceFill)."""
    total = sum(len(fills) for _, _, fills in per_wallet)
    if not total:
        return (f"📊 TWAP-сделки за последние {days} дней не найдены.\n\n"
                f"Бот видит только исполнения слайсов от TWAP-ордеров. "
                f"Если ни один TWAP не запускался — список будет пуст.")

    lines = [f"📊 <b>TWAP — последние {days} дней</b>", ""]
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
            when = (fmt_datetime(first) if first == last
                    else f"{fmt_datetime(first)} – {fmt_time_hhmm(last)}")
            lines.append(
                f"  {em} <b>{esc(coin)}</b> {esc(side)} • "
                f"{len(slices)} слайсов\n"
                f"     {fmt_usd(total_notional)} @ {fmt_price(avg_px)}, "
                f"комиссия {fmt_usd(total_fee)}\n"
                f"     {when} {_TZ_SUFFIX}"
            )
        lines.append("")

    lines.append(f"Всего слайсов: <b>{total}</b> • "
                 f"Объём: <b>{fmt_usd(grand_volume)}</b> • "
                 f"Комиссии: {fmt_usd(grand_fee)}")
    return "\n".join(lines)


def format_active_orders(
    per_wallet: list[tuple[str, str, list[dict]]],
) -> str:
    """per_wallet: list of (label, address, raw_open_orders)."""
    total_ord = sum(len(ords) for _, _, ords in per_wallet)
    if not total_ord:
        return "🎯 Нет активных ордеров."

    lines = ["🎯 <b>АКТИВНЫЕ ОРДЕРА</b>", ""]
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

    lines.append(f"Всего ордеров: <b>{total_ord}</b> "
                 f"на {fmt_usd(total_notional)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /list
# ---------------------------------------------------------------------------

def format_wallet_list(wallets: list[Wallet]) -> str:
    if not wallets:
        return ("📋 <b>ОТСЛЕЖИВАЕМЫЕ КОШЕЛЬКИ (0)</b>\n\n"
                "Список пуст. Добавь кошелёк командой:\n"
                "<code>/add 0x... [метка]</code>")
    active = [w for w in wallets if w.active]
    paused = [w for w in wallets if not w.active]

    lines = [f"📋 <b>ОТСЛЕЖИВАЕМЫЕ КОШЕЛЬКИ ({len(wallets)})</b>", ""]
    for w in active:
        lines.append(f"🟢 <b>{esc(w.label)}</b> — <code>{short_addr(w.address)}</code>")
    for w in paused:
        lines.append(f"⏸ {esc(w.label)} — <code>{short_addr(w.address)}</code>")
    lines.append("")
    lines.append(f"Активных: {len(active)} | На паузе: {len(paused)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  /stats
# ---------------------------------------------------------------------------

def format_stats(
    label: str,
    closed: list[Position],
    open_positions: list[Position],
    period_label: str = "24ч",
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
    lines.append(f"Сделок: <b>{n}</b>")
    if n:
        lines.append(f"Прибыльных: <b>{len(profitable)}</b> ({win_rate:.0f}%)")
    lines.append("")
    lines.append(f"💰 P&L: <b>{fmt_usd_signed(pnl_total)}</b>")
    if best and (best.pnl or 0) > 0:
        lines.append(f"📈 Лучшая: {fmt_usd_signed(best.pnl or 0)} "
                     f"({esc(best.coin)} {best.side.lower()})")
    if worst and (worst.pnl or 0) < 0:
        lines.append(f"📉 Худшая: {fmt_usd_signed(worst.pnl or 0)} "
                     f"({esc(worst.coin)} {worst.side.lower()})")

    if open_positions:
        lines.append("")
        lines.append("Текущие открытые позиции:")
        for p in open_positions:
            upnl = unrealized.get(p.coin, p.pnl or 0)
            em = "🟢" if upnl >= 0 else "🔴"
            lines.append(
                f"• {esc(p.coin)} {esc(p.side)} {fmt_usd(p.notional)} "
                f"({fmt_usd_signed(upnl)} {em})"
            )
    return "\n".join(lines)


def format_global_stats(
    per_wallet: list[tuple[str, list[Position], list[Position]]],
    period_label: str = "24ч",
) -> str:
    lines = [f"📊 <b>ОБЩАЯ СТАТИСТИКА</b> — {esc(period_label)}", ""]
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
    lines.append(f"Кошельков: <b>{len(per_wallet)}</b>")
    lines.append(f"Сделок: <b>{total_trades}</b>")
    if total_trades:
        lines.append(f"Прибыльных: <b>{total_profitable}</b> ({win_rate:.0f}%)")
    lines.append(f"💰 Суммарный P&L: <b>{fmt_usd_signed(total_pnl)}</b>")
    lines.append(f"📂 Открытых позиций: <b>{open_count}</b>")

    if per_wallet:
        lines.append("")
        lines.append("<b>По кошелькам:</b>")
        for label, closed, opens in per_wallet:
            wp = sum((p.pnl or 0) for p in closed)
            lines.append(
                f"• {esc(label)}: {len(closed)} сделок, "
                f"P&L {fmt_usd_signed(wp)}, открыто {len(opens)}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
#  help
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "<b>Hyperliquid Wallet Tracker</b>\n\n"
    "<b>Команды:</b>\n"
    "<code>/add 0x... [метка]</code> — добавить кошелёк\n"
    "<code>/remove 0x...</code> — удалить кошелёк\n"
    "<code>/list</code> — список отслеживаемых кошельков\n"
    "<code>/positions</code> — активные позиции и ордера\n"
    "<code>/rename 0x... Новое имя</code> — переименовать метку\n"
    "<code>/pause 0x...</code> — приостановить слежку\n"
    "<code>/resume 0x...</code> — возобновить слежку\n"
    "<code>/stats [24h|7d|30d]</code> — статистика по всем\n"
    "<code>/stats 0x... [24h|7d|30d]</code> — статистика по конкретному\n"
    "<code>/menu</code> — открыть меню с кнопками\n"
    "<code>/help</code> — эта справка"
)

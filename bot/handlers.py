"""Telegram command + inline-button handlers."""
from __future__ import annotations

import logging
import re
import time
from functools import wraps

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from bot.formatter import (
    ADD_WALLET_PROMPT,
    HELP_TEXT,
    MAIN_MENU_TEXT,
    STATS_MENU_TEXT,
    back_to_menu_keyboard,
    cancel_keyboard,
    confirm_remove_keyboard,
    confirm_remove_text,
    esc,
    format_active_orders,
    format_active_positions,
    format_global_stats,
    format_stats,
    format_twap_fills,
    format_wallet_list,
    main_menu_keyboard,
    rename_prompt_text,
    short_addr,
    stats_period_keyboard,
    wallet_detail_keyboard,
    wallet_detail_text,
    wallet_stats_menu_text,
    wallets_list_keyboard,
    wallets_list_text,
)
from database.storage import Storage

log = logging.getLogger("bot.handlers")

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PERIOD_RE = re.compile(r"^(\d+)(h|d)$", re.IGNORECASE)

_PERIOD_MAP = {
    "24h": (24 * 3600, "24ч"),
    "7d": (7 * 24 * 3600, "7д"),
    "30d": (30 * 24 * 3600, "30д"),
}


def _is_period(s: str) -> bool:
    return s.lower() in _PERIOD_MAP or bool(PERIOD_RE.match(s))


def _parse_period(args: list[str]) -> tuple[int, str]:
    for a in args:
        low = a.lower()
        if low in _PERIOD_MAP:
            return _PERIOD_MAP[low]
        m = PERIOD_RE.match(low)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            secs = n * 3600 if unit == "h" else n * 86400
            label = f"{n}{'ч' if unit == 'h' else 'д'}"
            return secs, label
    return 24 * 3600, "24ч"


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------

def _is_authorized(update: Update) -> bool:
    if not update.effective_chat:
        return False
    return update.effective_chat.id == config.MY_CHAT_ID


def auth_only(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        update = next((a for a in args if isinstance(a, Update)), None)
        if not update or not _is_authorized(update):
            if update:
                log.warning("Unauthorized access from %s",
                            update.effective_chat and update.effective_chat.id)
            return
        return await fn(*args, **kwargs)
    return wrapped


async def _reply(update: Update, text: str, reply_markup=None) -> None:
    target = update.message or (update.callback_query and update.callback_query.message)
    if target:
        await target.reply_text(text, parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                                reply_markup=reply_markup)


async def _edit_or_reply(update: Update, text: str, reply_markup=None) -> None:
    """Edit the inline-keyboard message in place (if callback) or reply."""
    q = update.callback_query
    if q and q.message:
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
    await _reply(update, text, reply_markup=reply_markup)


def _normalize_address(addr: str) -> str | None:
    addr = addr.strip().lower()
    if ADDRESS_RE.match(addr):
        return addr
    return None


# ---------------------------------------------------------------------------
#  Handlers class
# ---------------------------------------------------------------------------

class Handlers:
    """Bundles state needed by every handler."""

    def __init__(self, storage: Storage, ws_subscribe, ws_unsubscribe,
                 labels: dict[str, str]):
        self.storage = storage
        self.ws_subscribe = ws_subscribe
        self.ws_unsubscribe = ws_unsubscribe
        self.labels = labels
        # pending text-input flows: chat_id -> {"action": "add"|"rename", "addr"?: str}
        self._pending: dict[int, dict] = {}

    # =====================================================================
    #  Commands (kept for compat)
    # =====================================================================

    @auth_only
    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply(update, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())

    @auth_only
    async def help_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply(update, HELP_TEXT, reply_markup=back_to_menu_keyboard())

    @auth_only
    async def menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply(update, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())

    @auth_only
    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        self._pending.pop(chat_id, None)
        await _reply(update, "Действие отменено.", reply_markup=main_menu_keyboard())

    @auth_only
    async def add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, "Использование: <code>/add 0x... [метка]</code>")
            return
        await self._do_add(update, args[0], " ".join(args[1:]).strip())

    @auth_only
    async def remove(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, "Использование: <code>/remove 0x...</code>")
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, "❌ Невалидный адрес.")
            return
        await self._do_remove(update, addr)

    @auth_only
    async def list_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        wallets = await self.storage.list_wallets()
        await _reply(update, format_wallet_list(wallets),
                     reply_markup=back_to_menu_keyboard())

    @auth_only
    async def rename(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        if len(args) < 2:
            await _reply(update, "Использование: <code>/rename 0x... Новое имя</code>")
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, "❌ Невалидный адрес.")
            return
        new_label = " ".join(args[1:]).strip()
        await self._do_rename(update, addr, new_label)

    @auth_only
    async def pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, "Использование: <code>/pause 0x...</code>")
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, "❌ Невалидный адрес.")
            return
        await self._do_set_active(update, addr, False)

    @auth_only
    async def resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, "Использование: <code>/resume 0x...</code>")
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, "❌ Невалидный адрес.")
            return
        await self._do_set_active(update, addr, True)

    @auth_only
    async def stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args or []
        period_sec, period_label = _parse_period(args)
        args = [a for a in args if not _is_period(a)]

        if args:
            addr = _normalize_address(args[0])
            if not addr:
                await _reply(update, "❌ Невалидный адрес.")
                return
            await self._render_wallet_stats(update, addr, period_sec, period_label)
            return
        await self._render_global_stats(update, period_sec, period_label)

    @auth_only
    async def positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._render_all_positions(update)

    # =====================================================================
    #  Inline button callbacks
    # =====================================================================

    @auth_only
    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not q:
            return
        await q.answer()
        # Any button press cancels a pending text flow
        chat_id = update.effective_chat.id if update.effective_chat else 0
        self._pending.pop(chat_id, None)

        data = q.data or ""

        if data == "m:menu":
            await _edit_or_reply(update, MAIN_MENU_TEXT,
                                 reply_markup=main_menu_keyboard())
        elif data == "m:wallets":
            await self._render_wallets_list(update)
        elif data == "m:positions":
            await self._render_all_positions(update)
        elif data == "m:orders":
            await self._render_all_orders(update)
        elif data == "m:twap":
            await self._render_all_twap(update)
        elif data == "m:stats_menu":
            await _edit_or_reply(update, STATS_MENU_TEXT,
                                 reply_markup=stats_period_keyboard())
        elif data == "m:help":
            await _edit_or_reply(update, HELP_TEXT,
                                 reply_markup=back_to_menu_keyboard())
        elif data == "m:add":
            self._pending[chat_id] = {"action": "add"}
            await _edit_or_reply(update, ADD_WALLET_PROMPT,
                                 reply_markup=cancel_keyboard())
        elif data.startswith("w:"):
            await self._render_wallet_detail(update, data[2:])
        elif data.startswith("wp:"):
            await self._render_wallet_positions(update, data[3:])
        elif data.startswith("wo:"):
            await self._render_wallet_orders(update, data[3:])
        elif data.startswith("wt:"):
            await self._render_wallet_twap(update, data[3:])
        elif data.startswith("ws:"):
            await self._render_wallet_stats_menu(update, data[3:])
        elif data.startswith("sg:"):
            await self._handle_global_stats_period(update, data[3:])
        elif data.startswith("sp:"):
            rest = data[3:]
            addr, _, period = rest.rpartition(":")
            await self._handle_wallet_stats_period(update, addr, period)
        elif data.startswith("pa:"):
            await self._do_set_active(update, data[3:], False, from_button=True)
        elif data.startswith("re:"):
            await self._do_set_active(update, data[3:], True, from_button=True)
        elif data.startswith("rn:"):
            wallet = await self.storage.get_wallet(data[3:])
            if not wallet:
                await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                     reply_markup=back_to_menu_keyboard())
                return
            self._pending[chat_id] = {"action": "rename", "addr": wallet.address}
            await _edit_or_reply(update, rename_prompt_text(wallet),
                                 reply_markup=cancel_keyboard())
        elif data.startswith("rm:"):
            wallet = await self.storage.get_wallet(data[3:])
            if not wallet:
                await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                     reply_markup=back_to_menu_keyboard())
                return
            await _edit_or_reply(update, confirm_remove_text(wallet),
                                 reply_markup=confirm_remove_keyboard(wallet.address))
        elif data.startswith("cr:"):
            await self._do_remove(update, data[3:], from_button=True)

    # =====================================================================
    #  Text input handler (for add/rename pending flows)
    # =====================================================================

    @auth_only
    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        text = update.message.text.strip()
        if text.startswith("/"):
            return
        chat_id = update.effective_chat.id if update.effective_chat else 0
        state = self._pending.pop(chat_id, None)
        if not state:
            await _reply(update, "Используйте меню или команды.",
                         reply_markup=main_menu_keyboard())
            return

        action = state.get("action")
        if action == "add":
            parts = text.split()
            addr_raw = parts[0] if parts else ""
            label = " ".join(parts[1:]).strip()
            await self._do_add(update, addr_raw, label)
        elif action == "rename":
            await self._do_rename(update, state["addr"], text)

    # =====================================================================
    #  Render helpers (use _edit_or_reply so it works for both / and buttons)
    # =====================================================================

    async def _render_wallets_list(self, update: Update) -> None:
        wallets = await self.storage.list_wallets()
        await _edit_or_reply(update, wallets_list_text(wallets),
                             reply_markup=wallets_list_keyboard(wallets))

    async def _wallet_detail_payload(self, wallet) -> dict:
        ws = getattr(self, "_ws_ref", None)
        rest = getattr(self, "_rest_ref", None)
        addr = wallet.address
        positions = ws.get_positions(addr) if ws else {}
        orders = ws.get_open_orders(addr) if ws else []

        balance = 0.0
        pnl_24h = pnl_7d = pnl_30d = pnl_all = 0.0
        if rest:
            portfolio = await rest.fetch_portfolio(addr)
            if portfolio:
                balance = portfolio.account_value  # full equity (spot+perp)
                pnl_24h = portfolio.day
                pnl_7d = portfolio.week
                pnl_30d = portfolio.month
                pnl_all = portfolio.all_time

        # Fallback: WS only sees the perp account
        if not balance and ws:
            balance = ws.get_account_state(addr).account_value

        return {
            "positions": positions, "orders": orders, "balance": balance,
            "pnl_24h": pnl_24h, "pnl_7d": pnl_7d,
            "pnl_30d": pnl_30d, "pnl_all": pnl_all,
        }

    async def _render_wallet_detail(self, update: Update, addr: str) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        payload = await self._wallet_detail_payload(wallet)
        await _edit_or_reply(
            update,
            wallet_detail_text(wallet, **payload),
            reply_markup=wallet_detail_keyboard(wallet),
        )

    async def _render_all_positions(self, update: Update) -> None:
        wallets = await self.storage.list_wallets(only_active=True)
        if not wallets:
            await _edit_or_reply(update, "Список кошельков пуст.",
                                 reply_markup=back_to_menu_keyboard())
            return
        ws = getattr(self, "_ws_ref", None)
        per_wallet = [
            (w.label, w.address, ws.get_positions(w.address) if ws else {})
            for w in wallets
        ]
        await _edit_or_reply(update, format_active_positions(per_wallet),
                             reply_markup=back_to_menu_keyboard())

    async def _render_all_orders(self, update: Update) -> None:
        wallets = await self.storage.list_wallets(only_active=True)
        if not wallets:
            await _edit_or_reply(update, "Список кошельков пуст.",
                                 reply_markup=back_to_menu_keyboard())
            return
        ws = getattr(self, "_ws_ref", None)
        per_wallet = [
            (w.label, w.address, ws.get_open_orders(w.address) if ws else [])
            for w in wallets
        ]
        await _edit_or_reply(update, format_active_orders(per_wallet),
                             reply_markup=back_to_menu_keyboard())

    def _wallet_back_keyboard(self, addr: str):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ К кошельку", callback_data=f"w:{addr}"),
            InlineKeyboardButton("🏠 Меню", callback_data="m:menu"),
        ]])

    async def _render_wallet_positions(self, update: Update, addr: str) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        ws = getattr(self, "_ws_ref", None)
        positions = ws.get_positions(addr) if ws else {}
        await _edit_or_reply(
            update,
            format_active_positions([(wallet.label, wallet.address, positions)]),
            reply_markup=self._wallet_back_keyboard(addr),
        )

    async def _render_wallet_orders(self, update: Update, addr: str) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        ws = getattr(self, "_ws_ref", None)
        orders = ws.get_open_orders(addr) if ws else []
        await _edit_or_reply(
            update,
            format_active_orders([(wallet.label, wallet.address, orders)]),
            reply_markup=self._wallet_back_keyboard(addr),
        )

    async def _render_all_twap(self, update: Update) -> None:
        wallets = await self.storage.list_wallets(only_active=True)
        if not wallets:
            await _edit_or_reply(update, "Список кошельков пуст.",
                                 reply_markup=back_to_menu_keyboard())
            return
        rest = getattr(self, "_rest_ref", None)
        per_wallet = []
        for w in wallets:
            fills = await rest.fetch_twap_slice_fills(w.address) if rest else []
            per_wallet.append((w.label, w.address, fills))
        await _edit_or_reply(update, format_twap_fills(per_wallet),
                             reply_markup=back_to_menu_keyboard())

    async def _render_wallet_twap(self, update: Update, addr: str) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        rest = getattr(self, "_rest_ref", None)
        fills = await rest.fetch_twap_slice_fills(addr) if rest else []
        await _edit_or_reply(
            update,
            format_twap_fills([(wallet.label, wallet.address, fills)]),
            reply_markup=self._wallet_back_keyboard(addr),
        )

    async def _render_wallet_stats_menu(self, update: Update, addr: str) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        await _edit_or_reply(update, wallet_stats_menu_text(wallet),
                             reply_markup=stats_period_keyboard(addr))

    async def _handle_global_stats_period(self, update: Update, period: str) -> None:
        secs, label = _PERIOD_MAP.get(period, (24 * 3600, "24ч"))
        await self._render_global_stats(update, secs, label)

    async def _handle_wallet_stats_period(
        self, update: Update, addr: str, period: str,
    ) -> None:
        secs, label = _PERIOD_MAP.get(period, (24 * 3600, "24ч"))
        await self._render_wallet_stats(update, addr, secs, label)

    async def _render_global_stats(
        self, update: Update, period_sec: int, period_label: str,
    ) -> None:
        since_ts = int(time.time()) - period_sec
        wallets = await self.storage.list_wallets()
        if not wallets:
            await _edit_or_reply(update, "Список кошельков пуст.",
                                 reply_markup=back_to_menu_keyboard())
            return
        per_wallet = []
        for w in wallets:
            closed = [p for p in await self.storage.positions_since(w.address, since_ts)
                      if p.closed_at]
            opens = await self.storage.get_open_positions(w.address)
            per_wallet.append((w.label, closed, opens))
        await _edit_or_reply(
            update,
            format_global_stats(per_wallet, period_label),
            reply_markup=stats_period_keyboard(),
        )

    async def _render_wallet_stats(
        self, update: Update, addr: str, period_sec: int, period_label: str,
    ) -> None:
        wallet = await self.storage.get_wallet(addr)
        if not wallet:
            await _edit_or_reply(update, "ℹ️ Кошелёк не найден.",
                                 reply_markup=back_to_menu_keyboard())
            return
        since_ts = int(time.time()) - period_sec
        closed = [p for p in await self.storage.positions_since(addr, since_ts)
                  if p.closed_at]
        opens = await self.storage.get_open_positions(addr)
        upnl = self._get_unrealized(addr)
        await _edit_or_reply(
            update,
            format_stats(wallet.label, closed, opens, period_label, upnl),
            reply_markup=stats_period_keyboard(addr),
        )

    # =====================================================================
    #  Action helpers (shared by command + button paths)
    # =====================================================================

    async def _do_add(self, update: Update, addr_raw: str, label: str) -> None:
        addr = _normalize_address(addr_raw)
        if not addr:
            await _reply(update,
                         "❌ Невалидный адрес. Жду 0x... (42 символа).",
                         reply_markup=main_menu_keyboard())
            return
        label = label.strip() or short_addr(addr)
        ok = await self.storage.add_wallet(addr, label)
        if not ok:
            await _reply(update, "ℹ️ Этот кошелёк уже отслеживается.",
                         reply_markup=main_menu_keyboard())
            return
        self.labels[addr] = label
        await self.ws_subscribe(addr, label)
        wallets = await self.storage.list_wallets()
        await _reply(
            update,
            "✅ <b>Кошелёк добавлен!</b>\n"
            f"Адрес: <code>{addr}</code>\n"
            f"Метка: \"{esc(label)}\"\n"
            f"Всего отслеживается: <b>{len(wallets)}</b>",
            reply_markup=main_menu_keyboard(),
        )

    async def _do_remove(self, update: Update, addr: str,
                         from_button: bool = False) -> None:
        addr_n = _normalize_address(addr) or addr
        ok = await self.storage.remove_wallet(addr_n)
        if not ok:
            msg = "ℹ️ Такого кошелька в списке нет."
        else:
            self.labels.pop(addr_n, None)
            await self.ws_unsubscribe(addr_n)
            msg = f"🗑 Кошелёк <code>{short_addr(addr_n)}</code> удалён."
        if from_button:
            wallets = await self.storage.list_wallets()
            await _edit_or_reply(update, msg + "\n\n" + wallets_list_text(wallets),
                                 reply_markup=wallets_list_keyboard(wallets))
        else:
            await _reply(update, msg, reply_markup=main_menu_keyboard())

    async def _do_rename(self, update: Update, addr: str, new_label: str) -> None:
        addr_n = _normalize_address(addr) or addr
        new_label = new_label.strip()
        if not new_label:
            await _reply(update, "❌ Метка не может быть пустой.",
                         reply_markup=main_menu_keyboard())
            return
        ok = await self.storage.rename_wallet(addr_n, new_label)
        if not ok:
            await _reply(update, "ℹ️ Такого кошелька нет.",
                         reply_markup=main_menu_keyboard())
            return
        self.labels[addr_n] = new_label
        wallet = await self.storage.get_wallet(addr_n)
        payload = await self._wallet_detail_payload(wallet)
        await _reply(
            update,
            f"✏️ Метка обновлена: \"{esc(new_label)}\"\n\n"
            + wallet_detail_text(wallet, **payload),
            reply_markup=wallet_detail_keyboard(wallet),
        )

    async def _do_set_active(self, update: Update, addr: str, active: bool,
                             from_button: bool = False) -> None:
        addr_n = _normalize_address(addr) or addr
        ok = await self.storage.set_active(addr_n, active)
        if not ok:
            await _reply(update, "ℹ️ Такого кошелька нет.")
            return
        if active:
            label = self.labels.get(addr_n) or short_addr(addr_n)
            await self.ws_subscribe(addr_n, label)
        else:
            await self.ws_unsubscribe(addr_n)
        if from_button:
            await self._render_wallet_detail(update, addr_n)
        else:
            verb = "возобновлена" if active else "приостановлена"
            em = "▶️" if active else "⏸"
            await _reply(update, f"{em} Слежка {verb}: <code>{short_addr(addr_n)}</code>",
                         reply_markup=main_menu_keyboard())

    def _get_unrealized(self, wallet: str) -> dict[str, float]:
        ws = getattr(self, "_ws_ref", None)
        if ws:
            return ws.get_unrealized_pnl(wallet)
        return {}

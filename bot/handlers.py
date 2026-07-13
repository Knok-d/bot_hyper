"""Telegram command + inline-button handlers (multi-user)."""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from functools import wraps

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from bot.formatter import (
    add_wallet_prompt,
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
    fmt_usd,
    help_text,
    main_menu_keyboard,
    main_menu_text,
    rename_prompt_text,
    settings_keyboard,
    settings_text,
    short_addr,
    stats_menu_text,
    stats_period_keyboard,
    wallet_detail_keyboard,
    wallet_detail_text,
    wallet_stats_menu_text,
    wallets_list_keyboard,
    wallets_list_text,
)
from bot.i18n import t
from bot.users import UserService
from database.storage import Storage, User

log = logging.getLogger("bot.handlers")

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PERIOD_RE = re.compile(r"^(\d+)(h|d)$", re.IGNORECASE)

_PERIOD_MAP = {
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
}


def _is_period(s: str) -> bool:
    return s.lower() in _PERIOD_MAP or bool(PERIOD_RE.match(s))


def _parse_period(args: list[str], lang: str) -> tuple[int, str]:
    for a in args:
        low = a.lower()
        if low in _PERIOD_MAP:
            return _PERIOD_MAP[low], t(lang, f"period.{low}")
        m = PERIOD_RE.match(low)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            secs = n * 3600 if unit == "h" else n * 86400
            if lang == "ru":
                label = f"{n}{'ч' if unit == 'h' else 'д'}"
            else:
                label = f"{n}{unit}"
            return secs, label
    return _PERIOD_MAP["24h"], t(lang, "period.24h")


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------

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


def with_user(fn):
    """Auto-register the user on first contact, rate-limit, pass User in."""
    @wraps(fn)
    async def wrapped(self, update: Update,
                      ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if not chat:
            return
        if not self._rate_ok(chat.id):
            user = await self.users.get(chat.id)
            if user and self._rate_warn(chat.id):
                await _reply(update, t(user.lang, "reply.rate_limited"))
            return
        tg_lang = update.effective_user.language_code if update.effective_user else None
        user = await self.users.ensure(chat.id, tg_lang)
        return await fn(self, update, ctx, user)
    return wrapped


# ---------------------------------------------------------------------------
#  Handlers class
# ---------------------------------------------------------------------------

class Handlers:
    """Bundles state needed by every handler."""

    def __init__(self, storage: Storage, users: UserService,
                 ws_subscribe, ws_unsubscribe,
                 labels: dict[tuple[int, str], str]):
        self.storage = storage
        self.users = users
        self.ws_subscribe = ws_subscribe      # (chat_id, addr, label)
        self.ws_unsubscribe = ws_unsubscribe  # (chat_id, addr)
        self.labels = labels                  # (chat_id, addr) -> label
        # pending text-input flows: chat_id -> {"action": ..., "addr"?: str}
        self._pending: dict[int, dict] = {}
        # rate limiting: chat_id -> deque of command timestamps
        self._rate: dict[int, deque] = {}
        self._rate_warned: dict[int, int] = {}

    # ------------------------------------------------------------------
    #  rate limit
    # ------------------------------------------------------------------

    def _rate_ok(self, chat_id: int) -> bool:
        now = time.monotonic()
        dq = self._rate.setdefault(chat_id, deque())
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= config.USER_RATE_LIMIT_PER_MIN:
            return False
        dq.append(now)
        return True

    def _rate_warn(self, chat_id: int) -> bool:
        """Only warn once per rate-limit window."""
        now = int(time.monotonic())
        if now - self._rate_warned.get(chat_id, 0) > 60:
            self._rate_warned[chat_id] = now
            return True
        return False

    # =====================================================================
    #  Commands
    # =====================================================================

    @with_user
    async def start(self, update: Update, ctx, user: User) -> None:
        await _reply(update, main_menu_text(user.lang),
                     reply_markup=main_menu_keyboard(user.lang))

    @with_user
    async def help_cmd(self, update: Update, ctx, user: User) -> None:
        await _reply(update, help_text(user.lang),
                     reply_markup=back_to_menu_keyboard(user.lang))

    @with_user
    async def menu(self, update: Update, ctx, user: User) -> None:
        await _reply(update, main_menu_text(user.lang),
                     reply_markup=main_menu_keyboard(user.lang))

    @with_user
    async def settings(self, update: Update, ctx, user: User) -> None:
        await _reply(update, settings_text(user.lang, user),
                     reply_markup=settings_keyboard(user.lang))

    @with_user
    async def cancel(self, update: Update, ctx, user: User) -> None:
        self._pending.pop(user.chat_id, None)
        await _reply(update, t(user.lang, "reply.canceled"),
                     reply_markup=main_menu_keyboard(user.lang))

    @with_user
    async def add(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, t(user.lang, "usage.add"))
            return
        await self._do_add(update, user, args[0], " ".join(args[1:]).strip())

    @with_user
    async def remove(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, t(user.lang, "usage.remove"))
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, t(user.lang, "reply.bad_address"))
            return
        await self._do_remove(update, user, addr)

    @with_user
    async def list_cmd(self, update: Update, ctx, user: User) -> None:
        wallets = await self.storage.list_wallets(user.chat_id)
        await _reply(update, format_wallet_list(user.lang, wallets),
                     reply_markup=back_to_menu_keyboard(user.lang))

    @with_user
    async def rename(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        if len(args) < 2:
            await _reply(update, t(user.lang, "usage.rename"))
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, t(user.lang, "reply.bad_address"))
            return
        new_label = " ".join(args[1:]).strip()
        await self._do_rename(update, user, addr, new_label)

    @with_user
    async def pause(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, t(user.lang, "usage.pause"))
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, t(user.lang, "reply.bad_address"))
            return
        await self._do_set_active(update, user, addr, False)

    @with_user
    async def resume(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        if not args:
            await _reply(update, t(user.lang, "usage.resume"))
            return
        addr = _normalize_address(args[0])
        if not addr:
            await _reply(update, t(user.lang, "reply.bad_address"))
            return
        await self._do_set_active(update, user, addr, True)

    @with_user
    async def stats(self, update: Update, ctx, user: User) -> None:
        args = ctx.args or []
        period_sec, period_label = _parse_period(args, user.lang)
        args = [a for a in args if not _is_period(a)]

        if args:
            addr = _normalize_address(args[0])
            if not addr:
                await _reply(update, t(user.lang, "reply.bad_address"))
                return
            await self._render_wallet_stats(update, user, addr,
                                            period_sec, period_label)
            return
        await self._render_global_stats(update, user, period_sec, period_label)

    @with_user
    async def positions(self, update: Update, ctx, user: User) -> None:
        await self._render_all_positions(update, user)

    @with_user
    async def admin(self, update: Update, ctx, user: User) -> None:
        if user.chat_id != config.ADMIN_CHAT_ID:
            return
        stats = await self.storage.count_stats()
        subs = stats["unique_active_addresses"] * 3
        await _reply(
            update,
            "🛠 <b>Admin</b>\n"
            f"Users: <b>{stats['users']}</b>\n"
            f"Wallet subscriptions: <b>{stats['wallets']}</b>\n"
            f"Unique active addresses: <b>{stats['unique_active_addresses']}</b>\n"
            f"≈ WS subscriptions: <b>{subs}</b> / 1000",
        )

    # =====================================================================
    #  Inline button callbacks
    # =====================================================================

    @with_user
    async def on_callback(self, update: Update, ctx, user: User) -> None:
        q = update.callback_query
        if not q:
            return
        await q.answer()
        # Any button press cancels a pending text flow
        self._pending.pop(user.chat_id, None)

        data = q.data or ""
        lang = user.lang

        if data == "m:menu":
            await _edit_or_reply(update, main_menu_text(lang),
                                 reply_markup=main_menu_keyboard(lang))
        elif data == "m:wallets":
            await self._render_wallets_list(update, user)
        elif data == "m:positions":
            await self._render_all_positions(update, user)
        elif data == "m:orders":
            await self._render_all_orders(update, user)
        elif data == "m:twap":
            await self._render_all_twap(update, user)
        elif data == "m:stats_menu":
            await _edit_or_reply(update, stats_menu_text(lang),
                                 reply_markup=stats_period_keyboard(lang))
        elif data == "m:settings":
            await _edit_or_reply(update, settings_text(lang, user),
                                 reply_markup=settings_keyboard(lang))
        elif data == "m:help":
            await _edit_or_reply(update, help_text(lang),
                                 reply_markup=back_to_menu_keyboard(lang))
        elif data == "m:add":
            self._pending[user.chat_id] = {"action": "add"}
            await _edit_or_reply(update, add_wallet_prompt(lang),
                                 reply_markup=cancel_keyboard(lang))
        elif data.startswith("st:lang:"):
            new_lang = data.rsplit(":", 1)[-1]
            if new_lang in ("ru", "en"):
                await self.users.set_setting(user.chat_id, "lang", new_lang)
                user = await self.users.get(user.chat_id) or user
                await _edit_or_reply(update, settings_text(new_lang, user),
                                     reply_markup=settings_keyboard(new_lang))
        elif data == "st:minpos":
            self._pending[user.chat_id] = {"action": "minpos"}
            await _edit_or_reply(update, t(lang, "settings.min_pos_prompt"),
                                 reply_markup=cancel_keyboard(lang))
        elif data == "st:aggthr":
            self._pending[user.chat_id] = {"action": "aggthr"}
            await _edit_or_reply(update, t(lang, "settings.agg_thr_prompt"),
                                 reply_markup=cancel_keyboard(lang))
        elif data.startswith("w:"):
            await self._render_wallet_detail(update, user, data[2:])
        elif data.startswith("wp:"):
            await self._render_wallet_positions(update, user, data[3:])
        elif data.startswith("wo:"):
            await self._render_wallet_orders(update, user, data[3:])
        elif data.startswith("wt:"):
            await self._render_wallet_twap(update, user, data[3:])
        elif data.startswith("ws:"):
            await self._render_wallet_stats_menu(update, user, data[3:])
        elif data.startswith("sg:"):
            await self._handle_global_stats_period(update, user, data[3:])
        elif data.startswith("sp:"):
            rest = data[3:]
            addr, _, period = rest.rpartition(":")
            await self._handle_wallet_stats_period(update, user, addr, period)
        elif data.startswith("pa:"):
            await self._do_set_active(update, user, data[3:], False,
                                      from_button=True)
        elif data.startswith("re:"):
            await self._do_set_active(update, user, data[3:], True,
                                      from_button=True)
        elif data.startswith("rn:"):
            wallet = await self.storage.get_wallet(user.chat_id, data[3:])
            if not wallet:
                await _edit_or_reply(update, t(lang, "reply.wallet_not_found"),
                                     reply_markup=back_to_menu_keyboard(lang))
                return
            self._pending[user.chat_id] = {"action": "rename",
                                           "addr": wallet.address}
            await _edit_or_reply(update, rename_prompt_text(lang, wallet),
                                 reply_markup=cancel_keyboard(lang))
        elif data.startswith("rm:"):
            wallet = await self.storage.get_wallet(user.chat_id, data[3:])
            if not wallet:
                await _edit_or_reply(update, t(lang, "reply.wallet_not_found"),
                                     reply_markup=back_to_menu_keyboard(lang))
                return
            await _edit_or_reply(update, confirm_remove_text(lang, wallet),
                                 reply_markup=confirm_remove_keyboard(
                                     lang, wallet.address))
        elif data.startswith("cr:"):
            await self._do_remove(update, user, data[3:], from_button=True)

    # =====================================================================
    #  Text input handler (for pending flows)
    # =====================================================================

    @with_user
    async def on_message(self, update: Update, ctx, user: User) -> None:
        if not update.message or not update.message.text:
            return
        text = update.message.text.strip()
        if text.startswith("/"):
            return
        state = self._pending.pop(user.chat_id, None)
        if not state:
            await _reply(update, t(user.lang, "reply.use_menu"),
                         reply_markup=main_menu_keyboard(user.lang))
            return

        action = state.get("action")
        if action == "add":
            parts = text.split()
            addr_raw = parts[0] if parts else ""
            label = " ".join(parts[1:]).strip()
            await self._do_add(update, user, addr_raw, label)
        elif action == "rename":
            await self._do_rename(update, user, state["addr"], text)
        elif action in ("minpos", "aggthr"):
            await self._do_set_threshold(update, user, action, text)

    async def _do_set_threshold(self, update: Update, user: User,
                                action: str, text: str) -> None:
        try:
            value = float(text.replace(",", ".").replace(" ", "")
                          .replace("$", "").replace("k", "000")
                          .replace("K", "000"))
            if value < 0:
                raise ValueError
        except ValueError:
            self._pending[user.chat_id] = {"action": action}
            await _reply(update, t(user.lang, "settings.bad_number"),
                         reply_markup=cancel_keyboard(user.lang))
            return
        field = ("min_position_usd" if action == "minpos"
                 else "fill_agg_threshold")
        await self.users.set_setting(user.chat_id, field, value)
        user = await self.users.get(user.chat_id) or user
        await _reply(
            update,
            t(user.lang, "settings.saved") + "\n\n"
            + settings_text(user.lang, user),
            reply_markup=settings_keyboard(user.lang),
        )

    # =====================================================================
    #  Render helpers (use _edit_or_reply so it works for both / and buttons)
    # =====================================================================

    async def _render_wallets_list(self, update: Update, user: User) -> None:
        wallets = await self.storage.list_wallets(user.chat_id)
        await _edit_or_reply(update, wallets_list_text(user.lang, wallets),
                             reply_markup=wallets_list_keyboard(user.lang,
                                                                wallets))

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

    async def _render_wallet_detail(self, update: Update, user: User,
                                    addr: str) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        payload = await self._wallet_detail_payload(wallet)
        await _edit_or_reply(
            update,
            wallet_detail_text(user.lang, wallet, **payload),
            reply_markup=wallet_detail_keyboard(user.lang, wallet),
        )

    async def _render_all_positions(self, update: Update, user: User) -> None:
        wallets = await self.storage.list_wallets(user.chat_id,
                                                  only_active=True)
        if not wallets:
            await _edit_or_reply(update, wallets_list_text(user.lang, []),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        ws = getattr(self, "_ws_ref", None)
        per_wallet = [
            (w.label, w.address, ws.get_positions(w.address) if ws else {})
            for w in wallets
        ]
        await _edit_or_reply(update,
                             format_active_positions(user.lang, per_wallet),
                             reply_markup=back_to_menu_keyboard(user.lang))

    async def _render_all_orders(self, update: Update, user: User) -> None:
        wallets = await self.storage.list_wallets(user.chat_id,
                                                  only_active=True)
        if not wallets:
            await _edit_or_reply(update, wallets_list_text(user.lang, []),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        ws = getattr(self, "_ws_ref", None)
        per_wallet = [
            (w.label, w.address, ws.get_open_orders(w.address) if ws else [])
            for w in wallets
        ]
        await _edit_or_reply(update,
                             format_active_orders(user.lang, per_wallet),
                             reply_markup=back_to_menu_keyboard(user.lang))

    def _wallet_back_keyboard(self, lang: str, addr: str):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, "btn.back_to_wallet"),
                                 callback_data=f"w:{addr}"),
            InlineKeyboardButton(t(lang, "btn.menu"), callback_data="m:menu"),
        ]])

    async def _render_wallet_positions(self, update: Update, user: User,
                                       addr: str) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        ws = getattr(self, "_ws_ref", None)
        positions = ws.get_positions(addr) if ws else {}
        await _edit_or_reply(
            update,
            format_active_positions(
                user.lang, [(wallet.label, wallet.address, positions)]),
            reply_markup=self._wallet_back_keyboard(user.lang, addr),
        )

    async def _render_wallet_orders(self, update: Update, user: User,
                                    addr: str) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        ws = getattr(self, "_ws_ref", None)
        orders = ws.get_open_orders(addr) if ws else []
        await _edit_or_reply(
            update,
            format_active_orders(
                user.lang, [(wallet.label, wallet.address, orders)]),
            reply_markup=self._wallet_back_keyboard(user.lang, addr),
        )

    async def _render_all_twap(self, update: Update, user: User) -> None:
        wallets = await self.storage.list_wallets(user.chat_id,
                                                  only_active=True)
        if not wallets:
            await _edit_or_reply(update, wallets_list_text(user.lang, []),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        rest = getattr(self, "_rest_ref", None)
        per_wallet = []
        for w in wallets:
            fills = await rest.fetch_twap_slice_fills(w.address) if rest else []
            per_wallet.append((w.label, w.address, fills))
        await _edit_or_reply(update, format_twap_fills(user.lang, per_wallet),
                             reply_markup=back_to_menu_keyboard(user.lang))

    async def _render_wallet_twap(self, update: Update, user: User,
                                  addr: str) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        rest = getattr(self, "_rest_ref", None)
        fills = await rest.fetch_twap_slice_fills(addr) if rest else []
        await _edit_or_reply(
            update,
            format_twap_fills(user.lang,
                              [(wallet.label, wallet.address, fills)]),
            reply_markup=self._wallet_back_keyboard(user.lang, addr),
        )

    async def _render_wallet_stats_menu(self, update: Update, user: User,
                                        addr: str) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        await _edit_or_reply(update, wallet_stats_menu_text(user.lang, wallet),
                             reply_markup=stats_period_keyboard(user.lang,
                                                                addr))

    async def _handle_global_stats_period(self, update: Update, user: User,
                                          period: str) -> None:
        secs = _PERIOD_MAP.get(period, _PERIOD_MAP["24h"])
        label = t(user.lang, f"period.{period}" if period in _PERIOD_MAP
                  else "period.24h")
        await self._render_global_stats(update, user, secs, label)

    async def _handle_wallet_stats_period(
        self, update: Update, user: User, addr: str, period: str,
    ) -> None:
        secs = _PERIOD_MAP.get(period, _PERIOD_MAP["24h"])
        label = t(user.lang, f"period.{period}" if period in _PERIOD_MAP
                  else "period.24h")
        await self._render_wallet_stats(update, user, addr, secs, label)

    async def _render_global_stats(
        self, update: Update, user: User,
        period_sec: int, period_label: str,
    ) -> None:
        since_ts = int(time.time()) - period_sec
        wallets = await self.storage.list_wallets(user.chat_id)
        if not wallets:
            await _edit_or_reply(update, wallets_list_text(user.lang, []),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        per_wallet = []
        for w in wallets:
            closed = [p for p in await self.storage.positions_since(
                          w.address, since_ts)
                      if p.closed_at]
            opens = await self.storage.get_open_positions(w.address)
            per_wallet.append((w.label, closed, opens))
        await _edit_or_reply(
            update,
            format_global_stats(user.lang, per_wallet, period_label),
            reply_markup=stats_period_keyboard(user.lang),
        )

    async def _render_wallet_stats(
        self, update: Update, user: User, addr: str,
        period_sec: int, period_label: str,
    ) -> None:
        wallet = await self.storage.get_wallet(user.chat_id, addr)
        if not wallet:
            await _edit_or_reply(update, t(user.lang, "reply.wallet_not_found"),
                                 reply_markup=back_to_menu_keyboard(user.lang))
            return
        since_ts = int(time.time()) - period_sec
        closed = [p for p in await self.storage.positions_since(addr, since_ts)
                  if p.closed_at]
        opens = await self.storage.get_open_positions(addr)
        upnl = self._get_unrealized(addr)
        await _edit_or_reply(
            update,
            format_stats(user.lang, wallet.label, closed, opens,
                         period_label, upnl),
            reply_markup=stats_period_keyboard(user.lang, addr),
        )

    # =====================================================================
    #  Action helpers (shared by command + button paths)
    # =====================================================================

    async def _do_add(self, update: Update, user: User,
                      addr_raw: str, label: str) -> None:
        addr = _normalize_address(addr_raw)
        if not addr:
            await _reply(update, t(user.lang, "reply.bad_address"),
                         reply_markup=main_menu_keyboard(user.lang))
            return
        count = await self.storage.count_wallets(user.chat_id)
        if count >= config.MAX_WALLETS_PER_USER:
            await _reply(update,
                         t(user.lang, "reply.limit_reached",
                           limit=config.MAX_WALLETS_PER_USER),
                         reply_markup=main_menu_keyboard(user.lang))
            return
        label = label.strip() or short_addr(addr)
        ok = await self.storage.add_wallet(user.chat_id, addr, label)
        if not ok:
            await _reply(update, t(user.lang, "reply.already_tracked"),
                         reply_markup=main_menu_keyboard(user.lang))
            return
        self.labels[(user.chat_id, addr)] = label
        await self.ws_subscribe(user.chat_id, addr, label)
        total = await self.storage.count_wallets(user.chat_id)
        await _reply(
            update,
            t(user.lang, "reply.wallet_added",
              addr=addr, label=esc(label), total=total),
            reply_markup=main_menu_keyboard(user.lang),
        )

    async def _do_remove(self, update: Update, user: User, addr: str,
                         from_button: bool = False) -> None:
        addr_n = _normalize_address(addr) or addr
        ok = await self.storage.remove_wallet(user.chat_id, addr_n)
        if not ok:
            msg = t(user.lang, "reply.not_in_list")
        else:
            self.labels.pop((user.chat_id, addr_n), None)
            await self.ws_unsubscribe(user.chat_id, addr_n)
            msg = t(user.lang, "reply.wallet_removed",
                    addr=short_addr(addr_n))
        if from_button:
            wallets = await self.storage.list_wallets(user.chat_id)
            await _edit_or_reply(
                update, msg + "\n\n" + wallets_list_text(user.lang, wallets),
                reply_markup=wallets_list_keyboard(user.lang, wallets))
        else:
            await _reply(update, msg,
                         reply_markup=main_menu_keyboard(user.lang))

    async def _do_rename(self, update: Update, user: User, addr: str,
                         new_label: str) -> None:
        addr_n = _normalize_address(addr) or addr
        new_label = new_label.strip()
        if not new_label:
            await _reply(update, t(user.lang, "reply.label_empty"),
                         reply_markup=main_menu_keyboard(user.lang))
            return
        ok = await self.storage.rename_wallet(user.chat_id, addr_n, new_label)
        if not ok:
            await _reply(update, t(user.lang, "reply.not_in_list"),
                         reply_markup=main_menu_keyboard(user.lang))
            return
        self.labels[(user.chat_id, addr_n)] = new_label
        wallet = await self.storage.get_wallet(user.chat_id, addr_n)
        payload = await self._wallet_detail_payload(wallet)
        await _reply(
            update,
            t(user.lang, "reply.label_renamed", label=esc(new_label))
            + "\n\n" + wallet_detail_text(user.lang, wallet, **payload),
            reply_markup=wallet_detail_keyboard(user.lang, wallet),
        )

    async def _do_set_active(self, update: Update, user: User, addr: str,
                             active: bool, from_button: bool = False) -> None:
        addr_n = _normalize_address(addr) or addr
        ok = await self.storage.set_active(user.chat_id, addr_n, active)
        if not ok:
            await _reply(update, t(user.lang, "reply.not_in_list"))
            return
        if active:
            label = self.labels.get((user.chat_id, addr_n)) or short_addr(addr_n)
            await self.ws_subscribe(user.chat_id, addr_n, label)
        else:
            await self.ws_unsubscribe(user.chat_id, addr_n)
        if from_button:
            await self._render_wallet_detail(update, user, addr_n)
        else:
            key = ("reply.tracking_resumed" if active
                   else "reply.tracking_paused")
            await _reply(update, t(user.lang, key, addr=short_addr(addr_n)),
                         reply_markup=main_menu_keyboard(user.lang))

    def _get_unrealized(self, wallet: str) -> dict[str, float]:
        ws = getattr(self, "_ws_ref", None)
        if ws:
            return ws.get_unrealized_pnl(wallet)
        return {}

"""RU/EN string catalog for all user-facing texts."""
from __future__ import annotations

LANGS = ("ru", "en")
DEFAULT_LANG = "en"

CATALOG: dict[str, dict[str, str]] = {
    # --- menu / buttons ---
    "btn.wallets": {"ru": "📋 Кошельки", "en": "📋 Wallets"},
    "btn.positions": {"ru": "📈 Позиции", "en": "📈 Positions"},
    "btn.orders": {"ru": "🎯 Ордера", "en": "🎯 Orders"},
    "btn.twap": {"ru": "📊 TWAP", "en": "📊 TWAP"},
    "btn.stats": {"ru": "📊 Статистика", "en": "📊 Stats"},
    "btn.settings": {"ru": "⚙️ Настройки", "en": "⚙️ Settings"},
    "btn.help": {"ru": "❓ Помощь", "en": "❓ Help"},
    "btn.main_menu": {"ru": "🏠 Главное меню", "en": "🏠 Main menu"},
    "btn.menu": {"ru": "🏠 Меню", "en": "🏠 Menu"},
    "btn.add_wallet": {"ru": "➕ Добавить кошелёк", "en": "➕ Add wallet"},
    "btn.pause": {"ru": "⏸ Пауза", "en": "⏸ Pause"},
    "btn.resume": {"ru": "▶️ Возобновить", "en": "▶️ Resume"},
    "btn.rename": {"ru": "✏️ Переименовать", "en": "✏️ Rename"},
    "btn.delete": {"ru": "🗑 Удалить", "en": "🗑 Delete"},
    "btn.back_to_list": {"ru": "⬅️ К списку", "en": "⬅️ Back to list"},
    "btn.back_to_wallet": {"ru": "⬅️ К кошельку", "en": "⬅️ Back to wallet"},
    "btn.confirm_delete": {"ru": "✅ Да, удалить", "en": "✅ Yes, delete"},
    "btn.cancel": {"ru": "❌ Отмена", "en": "❌ Cancel"},
    "btn.24h": {"ru": "24ч", "en": "24h"},
    "btn.7d": {"ru": "7д", "en": "7d"},
    "btn.30d": {"ru": "30д", "en": "30d"},
    "btn.lang_ru": {"ru": "🇷🇺 Русский", "en": "🇷🇺 Russian"},
    "btn.lang_en": {"ru": "🇬🇧 English", "en": "🇬🇧 English"},
    "btn.min_position": {"ru": "💵 Мин. позиция", "en": "💵 Min position"},
    "btn.agg_threshold": {"ru": "📦 Порог агрегации", "en": "📦 Agg threshold"},

    # --- period labels ---
    "period.24h": {"ru": "24ч", "en": "24h"},
    "period.7d": {"ru": "7д", "en": "7d"},
    "period.30d": {"ru": "30д", "en": "30d"},

    # --- screens ---
    "menu.main": {
        "ru": "🤖 <b>Hyperliquid Wallet Tracker</b>\n\nВыберите действие в меню ниже.",
        "en": "🤖 <b>Hyperliquid Wallet Tracker</b>\n\nPick an action from the menu below.",
    },
    "wallets.empty": {
        "ru": "📋 <b>Кошельки</b>\n\nСписок пуст. Нажмите <b>➕ Добавить</b>, чтобы начать.",
        "en": "📋 <b>Wallets</b>\n\nThe list is empty. Tap <b>➕ Add wallet</b> to get started.",
    },
    "wallets.header": {
        "ru": ("📋 <b>Кошельки</b>\n\nВсего: <b>{total}</b> | "
               "Активных: <b>{active}</b> | На паузе: <b>{paused}</b>\n\n"
               "Выберите кошелёк для управления:"),
        "en": ("📋 <b>Wallets</b>\n\nTotal: <b>{total}</b> | "
               "Active: <b>{active}</b> | Paused: <b>{paused}</b>\n\n"
               "Pick a wallet to manage:"),
    },
    "wallet.status_active": {"ru": "🟢 Активен", "en": "🟢 Active"},
    "wallet.status_paused": {"ru": "⏸ На паузе", "en": "⏸ Paused"},
    "wallet.detail": {
        "ru": ("Статус: {status}\n💼 Баланс: <b>{balance}</b>\n\n"
               "📂 Позиций: <b>{positions}</b>\n"
               "📈 Unrealized PnL: <b>{upnl}</b>\n"
               "🎯 Ордеров: <b>{orders}</b>\n\n"
               "<b>Realized PnL:</b>\n"
               "  24ч:    {pnl_24h}\n  7д:     {pnl_7d}\n"
               "  30д:    {pnl_30d}\n  Весь:   {pnl_all}"),
        "en": ("Status: {status}\n💼 Balance: <b>{balance}</b>\n\n"
               "📂 Positions: <b>{positions}</b>\n"
               "📈 Unrealized PnL: <b>{upnl}</b>\n"
               "🎯 Orders: <b>{orders}</b>\n\n"
               "<b>Realized PnL:</b>\n"
               "  24h:    {pnl_24h}\n  7d:     {pnl_7d}\n"
               "  30d:    {pnl_30d}\n  All:    {pnl_all}"),
    },
    "add.prompt": {
        "ru": ("➕ <b>Добавление кошелька</b>\n\n"
               "Отправьте сообщение в формате:\n<code>0x... [метка]</code>\n\n"
               "Пример:\n<code>0x84b36f07a6547b1d6a2414240db69d9bbd0ee01f Whale1</code>\n\n"
               "Метка — необязательна."),
        "en": ("➕ <b>Add a wallet</b>\n\n"
               "Send a message in the format:\n<code>0x... [label]</code>\n\n"
               "Example:\n<code>0x84b36f07a6547b1d6a2414240db69d9bbd0ee01f Whale1</code>\n\n"
               "The label is optional."),
    },
    "rename.prompt": {
        "ru": ("✏️ <b>Переименование кошелька</b>\n\n"
               "Текущая метка: <b>{label}</b>\nАдрес: <code>{addr}</code>\n\n"
               "Отправьте новое имя сообщением."),
        "en": ("✏️ <b>Rename wallet</b>\n\n"
               "Current label: <b>{label}</b>\nAddress: <code>{addr}</code>\n\n"
               "Send the new name as a message."),
    },
    "remove.confirm": {
        "ru": ("🗑 <b>Удалить кошелёк?</b>\n\nМетка: <b>{label}</b>\n"
               "Адрес: <code>{addr}</code>\n\nИстория транзакций сохранится."),
        "en": ("🗑 <b>Delete this wallet?</b>\n\nLabel: <b>{label}</b>\n"
               "Address: <code>{addr}</code>\n\nTransaction history will be kept."),
    },
    "stats.menu": {
        "ru": "📊 <b>Статистика</b>\n\nВыберите период (по всем активным кошелькам):",
        "en": "📊 <b>Stats</b>\n\nPick a period (across all your active wallets):",
    },
    "stats.wallet_menu": {
        "ru": "📊 <b>Статистика — {label}</b>\n\nВыберите период:",
        "en": "📊 <b>Stats — {label}</b>\n\nPick a period:",
    },

    # --- settings ---
    "settings.screen": {
        "ru": ("⚙️ <b>Настройки</b>\n\n"
               "🌐 Язык: <b>{lang}</b>\n"
               "💵 Мин. размер позиции для уведомлений: <b>{min_pos}</b>\n"
               "📦 Порог агрегации сделок: <b>{agg_thr}</b>\n\n"
               "Уведомления приходят только по позициям крупнее минимального "
               "размера. Мелкие сделки копятся и шлются одним сообщением при "
               "достижении порога агрегации."),
        "en": ("⚙️ <b>Settings</b>\n\n"
               "🌐 Language: <b>{lang}</b>\n"
               "💵 Min position size for alerts: <b>{min_pos}</b>\n"
               "📦 Fill aggregation threshold: <b>{agg_thr}</b>\n\n"
               "You only get alerts for positions above the minimum size. "
               "Small fills are buffered and sent as one message once the "
               "aggregation threshold is reached."),
    },
    "settings.lang_name": {"ru": "Русский", "en": "English"},
    "settings.min_pos_prompt": {
        "ru": ("💵 <b>Минимальный размер позиции</b>\n\n"
               "Отправьте число в USD (например <code>10000</code>).\n"
               "0 — уведомлять обо всех позициях."),
        "en": ("💵 <b>Minimum position size</b>\n\n"
               "Send a number in USD (e.g. <code>10000</code>).\n"
               "0 — get alerts for every position."),
    },
    "settings.agg_thr_prompt": {
        "ru": ("📦 <b>Порог агрегации сделок</b>\n\n"
               "Отправьте число в USD (например <code>50000</code>).\n"
               "Мелкие сделки будут копиться и приходить одним сообщением "
               "при достижении этой суммы."),
        "en": ("📦 <b>Fill aggregation threshold</b>\n\n"
               "Send a number in USD (e.g. <code>50000</code>).\n"
               "Small fills are buffered and delivered as one message once "
               "they add up to this amount."),
    },
    "settings.saved": {"ru": "✅ Сохранено.", "en": "✅ Saved."},
    "settings.bad_number": {
        "ru": "❌ Не понял число. Отправьте, например: <code>50000</code>",
        "en": "❌ Couldn't parse the number. Send e.g. <code>50000</code>",
    },

    # --- generic replies ---
    "reply.canceled": {"ru": "Действие отменено.", "en": "Action canceled."},
    "reply.use_menu": {
        "ru": "Используйте меню или команды.",
        "en": "Use the menu or commands.",
    },
    "reply.bad_address": {
        "ru": "❌ Невалидный адрес. Жду 0x... (42 символа).",
        "en": "❌ Invalid address. Expecting 0x... (42 characters).",
    },
    "reply.wallet_not_found": {
        "ru": "ℹ️ Кошелёк не найден.",
        "en": "ℹ️ Wallet not found.",
    },
    "reply.already_tracked": {
        "ru": "ℹ️ Этот кошелёк уже отслеживается.",
        "en": "ℹ️ You're already tracking this wallet.",
    },
    "reply.limit_reached": {
        "ru": ("🚫 Достигнут лимит: <b>{limit}</b> кошельков на пользователя.\n"
               "Удалите один из существующих, чтобы добавить новый."),
        "en": ("🚫 Limit reached: <b>{limit}</b> wallets per user.\n"
               "Remove one of your wallets to add a new one."),
    },
    "reply.wallet_added": {
        "ru": ("✅ <b>Кошелёк добавлен!</b>\nАдрес: <code>{addr}</code>\n"
               "Метка: \"{label}\"\nВсего отслеживается: <b>{total}</b>"),
        "en": ("✅ <b>Wallet added!</b>\nAddress: <code>{addr}</code>\n"
               "Label: \"{label}\"\nNow tracking: <b>{total}</b>"),
    },
    "reply.wallet_removed": {
        "ru": "🗑 Кошелёк <code>{addr}</code> удалён.",
        "en": "🗑 Wallet <code>{addr}</code> removed.",
    },
    "reply.not_in_list": {
        "ru": "ℹ️ Такого кошелька в списке нет.",
        "en": "ℹ️ That wallet isn't in your list.",
    },
    "reply.label_renamed": {
        "ru": "✏️ Метка обновлена: \"{label}\"",
        "en": "✏️ Label updated: \"{label}\"",
    },
    "reply.label_empty": {
        "ru": "❌ Метка не может быть пустой.",
        "en": "❌ The label can't be empty.",
    },
    "reply.tracking_resumed": {
        "ru": "▶️ Слежка возобновлена: <code>{addr}</code>",
        "en": "▶️ Tracking resumed: <code>{addr}</code>",
    },
    "reply.tracking_paused": {
        "ru": "⏸ Слежка приостановлена: <code>{addr}</code>",
        "en": "⏸ Tracking paused: <code>{addr}</code>",
    },
    "reply.rate_limited": {
        "ru": "⏳ Слишком много команд, подождите минуту.",
        "en": "⏳ Too many commands, give it a minute.",
    },
    "usage.add": {
        "ru": "Использование: <code>/add 0x... [метка]</code>",
        "en": "Usage: <code>/add 0x... [label]</code>",
    },
    "usage.remove": {
        "ru": "Использование: <code>/remove 0x...</code>",
        "en": "Usage: <code>/remove 0x...</code>",
    },
    "usage.rename": {
        "ru": "Использование: <code>/rename 0x... Новое имя</code>",
        "en": "Usage: <code>/rename 0x... New name</code>",
    },
    "usage.pause": {
        "ru": "Использование: <code>/pause 0x...</code>",
        "en": "Usage: <code>/pause 0x...</code>",
    },
    "usage.resume": {
        "ru": "Использование: <code>/resume 0x...</code>",
        "en": "Usage: <code>/resume 0x...</code>",
    },

    # --- notifications: positions ---
    "ev.position_opened": {"ru": "📈 <b>ОТКРЫТА ПОЗИЦИЯ</b>", "en": "📈 <b>POSITION OPENED</b>"},
    "ev.position_closed": {"ru": "📉 <b>ЗАКРЫТА ПОЗИЦИЯ</b>", "en": "📉 <b>POSITION CLOSED</b>"},
    "ev.position_increased": {"ru": "📐 <b>ПОЗИЦИЯ УВЕЛИЧЕНА</b>", "en": "📐 <b>POSITION INCREASED</b>"},
    "ev.position_decreased": {"ru": "📐 <b>ПОЗИЦИЯ УМЕНЬШЕНА</b>", "en": "📐 <b>POSITION DECREASED</b>"},
    "ev.coin": {"ru": "Монета", "en": "Coin"},
    "ev.direction": {"ru": "Направление", "en": "Direction"},
    "ev.size": {"ru": "Размер", "en": "Size"},
    "ev.entry_price": {"ru": "Цена входа", "en": "Entry price"},
    "ev.exit_price": {"ru": "Цена выхода", "en": "Exit price"},
    "ev.leverage": {"ru": "Плечо", "en": "Leverage"},
    "ev.result": {"ru": "Результат", "en": "Result"},
    "ev.holding": {"ru": "Удержание", "en": "Held for"},

    # --- notifications: orders ---
    "ev.order_placed": {"ru": "🎯 <b>ВЫСТАВЛЕН ОРДЕР</b>", "en": "🎯 <b>ORDER PLACED</b>"},
    "ev.order_canceled": {"ru": "🚫 <b>ОТМЕНЁН ОРДЕР</b>", "en": "🚫 <b>ORDER CANCELED</b>"},
    "ev.order_filled": {"ru": "✅ <b>ИСПОЛНЕН ОРДЕР</b>", "en": "✅ <b>ORDER FILLED</b>"},
    "ev.order_type": {"ru": "Тип", "en": "Type"},
    "ev.order_price": {"ru": "Цена ордера", "en": "Order price"},
    "ev.current_price": {"ru": "Текущая цена", "en": "Current price"},

    # --- notifications: aggregated fills ---
    "agg.close_short": {"ru": "📈 ЗАКРЫТИЕ SHORT", "en": "📈 CLOSING SHORT"},
    "agg.open_long": {"ru": "📈 ОТКРЫТИЕ LONG", "en": "📈 OPENING LONG"},
    "agg.close_long": {"ru": "📉 ЗАКРЫТИЕ LONG", "en": "📉 CLOSING LONG"},
    "agg.open_short": {"ru": "📉 ОТКРЫТИЕ SHORT", "en": "📉 OPENING SHORT"},
    "agg.tx_count": {"ru": "Транзакций", "en": "Fills"},
    "agg.total_volume": {"ru": "Общий объём", "en": "Total volume"},
    "agg.total_size": {"ru": "Суммарный размер", "en": "Total size"},
    "agg.avg_price": {"ru": "Средняя цена сделок", "en": "Avg fill price"},
    "agg.whole_position": {"ru": "Позиция целиком", "en": "Whole position"},
    "agg.fee": {"ru": "Комиссия", "en": "Fee"},
    "agg.trade_time": {"ru": "Время сделок", "en": "Fill time"},

    # --- notifications: anomaly ---
    "anomaly.title": {"ru": "⚡️ <b>СОВПАДЕНИЕ!</b>", "en": "⚡️ <b>CORRELATED MOVE!</b>"},
    "anomaly.body": {
        "ru": "{n} твоих кита открыли <b>{side}</b> на <b>{coin}</b> одновременно",
        "en": "{n} of your whales opened <b>{side}</b> on <b>{coin}</b> at the same time",
    },
    "anomaly.total": {"ru": "Суммарно", "en": "Combined"},
    "anomaly.interval": {"ru": "Интервал: {minutes} мин", "en": "Window: {minutes} min"},

    # --- active positions / orders ---
    "pos.none": {"ru": "📈 Нет активных позиций.", "en": "📈 No open positions."},
    "pos.header": {"ru": "📈 <b>АКТИВНЫЕ ПОЗИЦИИ</b>", "en": "📈 <b>OPEN POSITIONS</b>"},
    "pos.liquidation": {
        "ru": "     💀 Ликвидация: {price} ({warn}{pct:.1f}% от входа)",
        "en": "     💀 Liquidation: {price} ({warn}{pct:.1f}% from entry)",
    },
    "pos.liq_safe": {
        "ru": "     💀 Ликвидация: — (вне риска)",
        "en": "     💀 Liquidation: — (not at risk)",
    },
    "pos.total": {
        "ru": "Всего позиций: <b>{n}</b> ({pnl})",
        "en": "Total positions: <b>{n}</b> ({pnl})",
    },
    "ord.none": {"ru": "🎯 Нет активных ордеров.", "en": "🎯 No open orders."},
    "ord.header": {"ru": "🎯 <b>АКТИВНЫЕ ОРДЕРА</b>", "en": "🎯 <b>OPEN ORDERS</b>"},
    "ord.total": {
        "ru": "Всего ордеров: <b>{n}</b> на {notional}",
        "en": "Total orders: <b>{n}</b> worth {notional}",
    },

    # --- twap ---
    "twap.none": {
        "ru": ("📊 TWAP-сделки за последние {days} дней не найдены.\n\n"
               "Бот видит только исполнения слайсов от TWAP-ордеров. "
               "Если ни один TWAP не запускался — список будет пуст."),
        "en": ("📊 No TWAP fills found in the last {days} days.\n\n"
               "The bot only sees executed TWAP slices. If no TWAP was run, "
               "the list will be empty."),
    },
    "twap.header": {
        "ru": "📊 <b>TWAP — последние {days} дней</b>",
        "en": "📊 <b>TWAP — last {days} days</b>",
    },
    "twap.slices": {"ru": "слайсов", "en": "slices"},
    "twap.fee": {"ru": "комиссия", "en": "fee"},
    "twap.total": {
        "ru": ("Всего слайсов: <b>{n}</b> • Объём: <b>{volume}</b> • "
               "Комиссии: {fee}"),
        "en": ("Total slices: <b>{n}</b> • Volume: <b>{volume}</b> • "
               "Fees: {fee}"),
    },

    # --- /list ---
    "list.empty": {
        "ru": ("📋 <b>ОТСЛЕЖИВАЕМЫЕ КОШЕЛЬКИ (0)</b>\n\n"
               "Список пуст. Добавь кошелёк командой:\n<code>/add 0x... [метка]</code>"),
        "en": ("📋 <b>TRACKED WALLETS (0)</b>\n\n"
               "The list is empty. Add a wallet with:\n<code>/add 0x... [label]</code>"),
    },
    "list.header": {
        "ru": "📋 <b>ОТСЛЕЖИВАЕМЫЕ КОШЕЛЬКИ ({n})</b>",
        "en": "📋 <b>TRACKED WALLETS ({n})</b>",
    },
    "list.footer": {
        "ru": "Активных: {active} | На паузе: {paused}",
        "en": "Active: {active} | Paused: {paused}",
    },

    # --- stats ---
    "stats.trades": {"ru": "Сделок: <b>{n}</b>", "en": "Trades: <b>{n}</b>"},
    "stats.profitable": {
        "ru": "Прибыльных: <b>{n}</b> ({rate:.0f}%)",
        "en": "Profitable: <b>{n}</b> ({rate:.0f}%)",
    },
    "stats.best": {
        "ru": "📈 Лучшая: {pnl} ({coin} {side})",
        "en": "📈 Best: {pnl} ({coin} {side})",
    },
    "stats.worst": {
        "ru": "📉 Худшая: {pnl} ({coin} {side})",
        "en": "📉 Worst: {pnl} ({coin} {side})",
    },
    "stats.open_positions": {
        "ru": "Текущие открытые позиции:",
        "en": "Currently open positions:",
    },
    "stats.global_header": {
        "ru": "📊 <b>ОБЩАЯ СТАТИСТИКА</b> — {period}",
        "en": "📊 <b>OVERALL STATS</b> — {period}",
    },
    "stats.wallets_count": {"ru": "Кошельков: <b>{n}</b>", "en": "Wallets: <b>{n}</b>"},
    "stats.total_pnl": {
        "ru": "💰 Суммарный P&L: <b>{pnl}</b>",
        "en": "💰 Total P&L: <b>{pnl}</b>",
    },
    "stats.open_count": {
        "ru": "📂 Открытых позиций: <b>{n}</b>",
        "en": "📂 Open positions: <b>{n}</b>",
    },
    "stats.by_wallet": {"ru": "<b>По кошелькам:</b>", "en": "<b>By wallet:</b>"},
    "stats.wallet_line": {
        "ru": "• {label}: {trades} сделок, P&L {pnl}, открыто {open}",
        "en": "• {label}: {trades} trades, P&L {pnl}, {open} open",
    },

    # --- help ---
    "help": {
        "ru": ("<b>Hyperliquid Wallet Tracker</b>\n\n"
               "Бот следит за кошельками на Hyperliquid и присылает "
               "уведомления об открытии/закрытии позиций, ордерах и крупных "
               "сделках.\n\n"
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
               "<code>/settings</code> — язык и пороги уведомлений\n"
               "<code>/menu</code> — открыть меню с кнопками\n"
               "<code>/help</code> — эта справка"),
        "en": ("<b>Hyperliquid Wallet Tracker</b>\n\n"
               "The bot watches Hyperliquid wallets and sends alerts on "
               "position opens/closes, orders and large fills.\n\n"
               "<b>Commands:</b>\n"
               "<code>/add 0x... [label]</code> — add a wallet\n"
               "<code>/remove 0x...</code> — remove a wallet\n"
               "<code>/list</code> — your tracked wallets\n"
               "<code>/positions</code> — open positions and orders\n"
               "<code>/rename 0x... New name</code> — rename a label\n"
               "<code>/pause 0x...</code> — pause tracking\n"
               "<code>/resume 0x...</code> — resume tracking\n"
               "<code>/stats [24h|7d|30d]</code> — stats across all wallets\n"
               "<code>/stats 0x... [24h|7d|30d]</code> — stats for one wallet\n"
               "<code>/settings</code> — language and alert thresholds\n"
               "<code>/menu</code> — open the button menu\n"
               "<code>/help</code> — this help"),
    },
}

_MONTHS = {
    "ru": ["янв", "фев", "мар", "апр", "май", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

_DURATION_UNITS = {
    "ru": ("ч", "мин", "с"),
    "en": ("h", "m", "s"),
}


def norm_lang(code: str | None) -> str:
    """Map a Telegram language_code to a supported bot language."""
    if code and code.lower().startswith("ru"):
        return "ru"
    return "en"


def t(lang: str, key: str, **kwargs) -> str:
    entry = CATALOG[key]
    s = entry.get(lang) or entry[DEFAULT_LANG]
    return s.format(**kwargs) if kwargs else s


def month_name(lang: str, month_1based: int) -> str:
    months = _MONTHS.get(lang) or _MONTHS[DEFAULT_LANG]
    return months[month_1based - 1]


def duration_units(lang: str) -> tuple[str, str, str]:
    return _DURATION_UNITS.get(lang) or _DURATION_UNITS[DEFAULT_LANG]

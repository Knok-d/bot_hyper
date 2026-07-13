# Hyperliquid Wallet Tracker Bot

Многопользовательский Telegram-бот для отслеживания активности кошельков на
[Hyperliquid](https://hyperliquid.xyz) DEX в реальном времени.

## Возможности

- **Мульти-юзер**: любой пользователь пишет боту `/start` и получает свой
  изолированный список кошельков и настройки
- Подписка на кошельки через Telegram-команды и inline-меню
  (лимит — 10 кошельков на пользователя)
- Уведомления об **открытии / закрытии позиций** (с PnL и временем удержания)
- **Агрегация мелких сделок** — fills копятся и приходят одним сообщением
  при накоплении порога (по умолчанию $50K, настраивается в `/settings`)
- **Детектор аномалий** — алерт, когда 2+ твоих кита открывают
  одинаковое направление в окне 5 минут (у каждого юзера свой набор китов)
- **`/settings`** — язык (RU/EN), минимальный размер позиции, порог агрегации
- **Двуязычный интерфейс** RU/EN (автоопределение по языку Telegram)
- Команда `/stats` — статистика по всем кошелькам или конкретному за период
- Хранение истории в локальной SQLite (`data.db`); одинаковые кошельки у
  разных юзеров дедуплицируются (одна WS-подписка на адрес)
- Автопереподключение WebSocket с экспоненциальным backoff
- Логи в `bot.log` + ротация (5MB × 3 файла)
- Rate-limit: не более 20 команд в минуту на пользователя
- `/admin` (только для `ADMIN_CHAT_ID`) — счётчики юзеров/кошельков/подписок

## Структура

```
bot_hyper/
├── main.py                 # точка входа, fan-out событий по подписчикам
├── config.py               # конфигурация (через .env)
├── requirements.txt
├── .env.example
├── hl_monitor/             # Hyperliquid слой (WS, парсер, детектор)
│   ├── client.py           # WebSocket подключение (одно на все кошельки)
│   ├── parser.py           # парсинг webData2 / orderUpdates / userFills
│   ├── rest.py             # REST /info (portfolio PnL, TWAP fills)
│   └── detector.py         # детектор аномалий (sliding window)
├── bot/                    # Telegram-слой
│   ├── handlers.py         # команды и inline-кнопки (per-user scoping)
│   ├── formatter.py        # форматирование сообщений
│   ├── i18n.py             # каталог строк RU/EN
│   └── users.py            # реестр юзеров с кэшем настроек
└── database/
    ├── storage.py          # async SQLite (+ авто-миграция v1 → v2)
    └── schema.sql          # users / wallets / positions / orders / history
```

> Папка с Hyperliquid-логикой называется `hl_monitor`, а не `hyperliquid`,
> чтобы не конфликтовать с пакетом `hyperliquid-python-sdk` (он импортируется
> как `hyperliquid`).

## Установка

Требуется Python 3.11+.

```bash
git clone <this-repo> bot_hyper
cd bot_hyper

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка

1. Создайте бота у [@BotFather](https://t.me/BotFather) и получите токен.
2. Узнайте свой числовой `chat_id` — например, отправьте боту
   [@userinfobot](https://t.me/userinfobot) команду `/start`.
3. Скопируйте конфигурацию:
   ```bash
   cp .env.example .env
   ```
4. Откройте `.env` и пропишите:
   ```
   TELEGRAM_TOKEN=<ваш токен от BotFather>
   ADMIN_CHAT_ID=<ваш числовой chat_id>
   ```

`MIN_POSITION_USD` и `FILL_AGG_THRESHOLD` — дефолты для новых юзеров,
каждый может поменять их у себя в `/settings`. Остальные переменные
(`DB_PATH`, `LOG_PATH`, `MAX_WALLETS_PER_USER`) — опциональны.

### Миграция со старой (single-user) версии

Ничего делать не нужно: при первом запуске бот сам мигрирует `data.db`
на новую схему (создаётся резервная копия `data.db.bak-<дата>`), а все
существующие кошельки приписываются `ADMIN_CHAT_ID`. Старое имя переменной
`MY_CHAT_ID` в `.env` продолжает работать.

## Запуск

```bash
python main.py
```

Пользователи находят бота в Telegram и отправляют `/start` — регистрация
автоматическая, язык подхватывается из настроек Telegram.

| Команда | Описание |
|---|---|
| `/add 0x... [метка]` | Добавить кошелёк |
| `/remove 0x...` | Удалить кошелёк |
| `/list` | Список с активными / на паузе |
| `/positions` | Активные позиции и ордера |
| `/rename 0x... Новое имя` | Переименовать метку |
| `/pause 0x...` | Приостановить слежку |
| `/resume 0x...` | Возобновить слежку |
| `/stats [24h\|7d\|30d]` | Общая статистика (по умолчанию 24ч) |
| `/stats 0x... [24h\|7d\|30d]` | Статистика по конкретному адресу |
| `/settings` | Язык и пороги уведомлений |
| `/menu` | Меню с кнопками |
| `/help` | Подсказка |
| `/admin` | Счётчики (только админ) |

## Запуск как systemd-сервис (Linux, опционально)

`/etc/systemd/system/hl-tracker.service`:

```ini
[Unit]
Description=Hyperliquid Wallet Tracker Bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/bot_hyper
ExecStart=/opt/bot_hyper/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
User=botuser
EnvironmentFile=/opt/bot_hyper/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hl-tracker
sudo journalctl -u hl-tracker -f
```

## Как это работает

- При старте бот подключается к `wss://api.hyperliquid.xyz/ws` одним
  WebSocket-соединением и подписывается на `webData2`, `orderUpdates` и
  `userFills` для каждого уникального активного адреса из БД (если несколько
  юзеров следят за одним адресом — подписка одна, refcount).
- `webData2` — это снапшот состояния аккаунта (позиции, ордера, балансы).
  Бот сравнивает каждый новый снапшот с предыдущим и детектирует
  открытие/закрытие позиций.
- Каждое событие раздаётся всем подписчикам адреса; для каждого применяются
  его личные фильтры (мин. размер позиции, порог агрегации) и его язык.
- `AnomalyDetector` — по экземпляру на юзера: хранит скользящее окно
  последних открытий по ключу `(монета, направление)` и срабатывает, когда
  в окне ≥ N разных кошельков этого юзера.
- При обрыве WebSocket бот автоматически переподключается с задержкой
  5 → 10 → 20 → … → 60 секунд (далее по 60).

## Тесты

```bash
source .venv/bin/activate
pytest tests/ -v
```

Smoke-test без живого WebSocket:
```bash
python scripts/dry_run.py
```

## Troubleshooting

### Бот не отвечает на команды

1. Проверьте, что `TELEGRAM_TOKEN` корректен и бот не заблокирован.
2. Посмотрите логи: `tail -f bot.log`
3. Если слали много команд подряд — сработал rate-limit (20/мин),
   подождите минуту.

### Приходят дубли уведомлений

Скорее всего запущено больше одного экземпляра бота. Убедитесь, что
запущен ровно один процесс:
```bash
ps aux | grep main.py
```

### «Фантомные» уведомления при старте

При добавлении нового кошелька первый снапшот сохраняется без эмиссии
событий (priming). Если дубли всё же появляются — проверьте, что
запущена актуальная версия кода.

### Где лежат логи

- `bot.log` в корне проекта (ротация 5MB × 3 файла).
- Для подробного дебага поменяйте уровень в `main.py`:
  ```python
  logging.basicConfig(level=logging.DEBUG, ...)
  ```

### WebSocket отключается

Бот автоматически переподключается с экспоненциальным backoff
(5 → 10 → 20 → … → 60 секунд). В логах будет `WebSocket dropped`
и `Reconnecting in Ns...`. Если соединение не восстанавливается —
проверьте доступность `wss://api.hyperliquid.xyz/ws`.

## Замечания

- Бот работает только в режиме *read-only* — он ничего не торгует и не
  перемещает средства.
- PnL для закрытий берётся из `userFills` (точный `closedPnl`), с
  fallback на `unrealizedPnl` из `webData2`.
- Лимит на размер сообщений Telegram — 4096 символов; форматтеры это
  учитывают.
- Лимит Hyperliquid ≈1000 WS-подписок с одного IP; каждый уникальный
  адрес = 3 подписки. `/admin` показывает текущее приближение к лимиту.

# Hyperliquid Wallet Tracker Bot

Personal Telegram-бот для отслеживания активности кошельков на
[Hyperliquid](https://hyperliquid.xyz) DEX в реальном времени.

## Возможности

- Подписка на любое количество адресов через Telegram-команды
- Уведомления об **открытии / закрытии позиций** (с PnL и временем удержания)
- Уведомления о **выставлении / отмене / исполнении лимит-ордеров**
- **Детектор аномалий** — алерт, когда 2+ ваших кита открывают
  одинаковое направление в окне 5 минут
- Команда `/stats` — общая статистика и по конкретному кошельку за 24ч
- Хранение истории в локальной SQLite (`data.db`)
- Автопереподключение WebSocket с экспоненциальным backoff
- Логи в `bot.log` + ротация (5MB × 3 файла)
- Команды принимаются **только** от заданного `MY_CHAT_ID`

## Структура

```
bot_hyper/
├── main.py                 # точка входа
├── config.py               # конфигурация (через .env)
├── requirements.txt
├── .env.example
├── hl_monitor/             # Hyperliquid слой (WS, парсер, детектор)
│   ├── client.py           # WebSocket подключение
│   ├── parser.py           # парсинг webData2 / orderUpdates
│   └── detector.py         # детектор аномалий (sliding window)
├── bot/                    # Telegram-слой
│   ├── handlers.py         # все команды /add /remove /list /stats ...
│   └── formatter.py        # форматирование сообщений
└── database/
    ├── storage.py          # async SQLite
    └── schema.sql          # wallets / positions / orders / history
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
   MY_CHAT_ID=<ваш числовой chat_id>
   MIN_POSITION_USD=0
   ```

Любая другая переменная (`DB_PATH`, `LOG_PATH`) — опциональна.

## Запуск

```bash
python main.py
```

В первом сообщении боту отправьте `/start` — увидите справку.
Дальше пользуйтесь командами:

| Команда | Описание |
|---|---|
| `/add 0x... [метка]` | Добавить кошелёк |
| `/remove 0x...` | Удалить кошелёк |
| `/list` | Список с активными / на паузе |
| `/rename 0x... Новое имя` | Переименовать метку |
| `/pause 0x...` | Приостановить слежку |
| `/resume 0x...` | Возобновить слежку |
| `/stats [24h\|7d\|30d]` | Общая статистика (по умолчанию 24ч) |
| `/stats 0x... [24h\|7d\|30d]` | Статистика по конкретному адресу |
| `/help` | Подсказка |

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
  WebSocket-соединением и подписывается на `webData2` и `orderUpdates`
  для каждого активного кошелька из БД.
- `webData2` — это снапшот состояния аккаунта (позиции, ордера, балансы).
  Бот сравнивает каждый новый снапшот с предыдущим и детектирует
  открытие/закрытие позиций.
- `orderUpdates` — инкрементальные события по лимит-ордерам.
- `AnomalyDetector` хранит скользящее окно последних открытий по ключу
  `(монета, направление)` и срабатывает, когда в окне ≥ N разных кошельков.
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

1. Убедитесь, что `MY_CHAT_ID` в `.env` совпадает с вашим числовым chat_id.
   Узнать свой chat_id можно у [@userinfobot](https://t.me/userinfobot).
2. Проверьте, что `TELEGRAM_TOKEN` корректен и бот не заблокирован.
3. Посмотрите логи: `tail -f bot.log`

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

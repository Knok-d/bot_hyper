# Деплой на VPS (Hetzner / DigitalOcean / Vultr)

Бот будет работать 24/7 как systemd-сервис с авто-рестартом при падении или перезагрузке.

## 1. Арендовать VPS

Минимальная конфигурация: **1 vCPU, 1 GB RAM, 10 GB SSD** — этого хватит с запасом.

Рекомендую **Hetzner Cloud**:
- Тариф `CX22` — €3.79/мес (~$4)
- Регион: `Falkenstein (DE)` или `Helsinki (FI)`
- Образ: **Ubuntu 24.04**
- При создании добавь свой SSH-ключ

Альтернативы: DigitalOcean (от $4/мес), Vultr ($3.50), Contabo (€3.99 за 4 GB RAM).

## 2. Подготовка локально

С твоего Mac:

```bash
cd ~/projects   # каталог, где лежит bot_hyper
# Замени HOST на IP сервера
scp -r bot_hyper root@HOST:/tmp/
```

## 3. Установка на сервере

Подключись и запусти установщик:

```bash
ssh root@HOST
cd /tmp/bot_hyper
bash deploy/install.sh
```

Скрипт сам:
- создаст системного пользователя `bot`
- поставит Python 3, venv, зависимости
- скопирует код в `/opt/bot_hyper`
- настроит systemd-сервис с авто-рестартом
- запустит бота

## 4. Проверка

```bash
# Статус
systemctl status bot_hyper

# Live-логи (Ctrl+C для выхода)
journalctl -u bot_hyper -f

# Последние 100 строк лога
journalctl -u bot_hyper -n 100 --no-pager
```

Должно быть видно:
```
WebSocket connected: wss://api.hyperliquid.xyz/ws
Bot started. Listening for ... chat_id only.
```

## 5. Управление

```bash
sudo systemctl stop    bot_hyper       # остановить
sudo systemctl start   bot_hyper       # запустить
sudo systemctl restart bot_hyper       # перезапустить
sudo systemctl disable bot_hyper       # выключить авто-старт
```

Бот **автоматически перезапустится**, если:
- упадёт с ошибкой → через 5 секунд
- сервер перезагрузится → при старте системы
- пропадёт интернет → переподключится сам (есть exponential backoff в коде)

## 6. Обновление кода

С локального Mac:

```bash
scp -r ./bot_hyper root@HOST:/tmp/
ssh root@HOST 'bash /tmp/bot_hyper/deploy/install.sh && systemctl restart bot_hyper'
```

## 7. Остановить бота на Mac

Чтобы не было конфликта `getUpdates` между сервером и локальной копией:

```bash
pkill -f "python.*main.py"
```

## Что ещё стоит знать

- **БД `data.db`** живёт в `/opt/bot_hyper/data.db`. Бэкап:
  `scp root@HOST:/opt/bot_hyper/data.db ./backup.db`
- **`.env`** содержит токен и chat_id — права 600, только пользователь `bot` читает.
- **Файервол**: бот не слушает входящие порты, открывать ничего не надо. Достаточно
  пускать только SSH (`ufw allow 22; ufw enable`).
- **fail2ban**: рекомендую `apt install -y fail2ban` для защиты SSH.

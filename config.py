"""Configuration for the Hyperliquid wallet tracker bot."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# === Telegram ===
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "YOUR_TOKEN")
# Админ бота (расширенные команды /admin). MY_CHAT_ID — legacy-имя, поддержано
# для обратной совместимости старых .env; также используется при миграции БД
# как владелец существующих кошельков.
ADMIN_CHAT_ID: int = int(
    os.getenv("ADMIN_CHAT_ID", os.getenv("MY_CHAT_ID", "0"))
)

# === Hyperliquid ===
HL_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
HL_API_URL: str = "https://api.hyperliquid.xyz"

# === Пер-юзерные дефолты (каждый юзер может переопределить в /settings) ===
# Минимальный размер позиции (USD), при котором отправляется уведомление.
DEFAULT_MIN_POSITION_USD: float = float(os.getenv("MIN_POSITION_USD", "10000"))
# Порог агрегации сделок: мелкие fills копятся и шлются одним сообщением.
DEFAULT_FILL_AGG_THRESHOLD: float = float(
    os.getenv("FILL_AGG_THRESHOLD", "50000")
)

# === Лимиты ===
# Максимум кошельков на одного юзера (каждый уникальный адрес = 4 WS-подписки,
# у Hyperliquid лимит подписок на IP).
MAX_WALLETS_PER_USER: int = int(os.getenv("MAX_WALLETS_PER_USER", "10"))
# Команд в минуту от одного юзера
USER_RATE_LIMIT_PER_MIN: int = 20

# === Аномалии ===
ANOMALY_TIME_WINDOW: int = 300  # 5 минут — окно для детекции совпадений
ANOMALY_MIN_WALLETS: int = 2     # минимум кошельков для срабатывания

# === Пути ===
BASE_DIR = Path(__file__).resolve().parent
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data.db"))
SCHEMA_PATH: str = str(BASE_DIR / "database" / "schema.sql")
LOG_PATH: str = os.getenv("LOG_PATH", str(BASE_DIR / "bot.log"))

# === WebSocket ===
WS_RECONNECT_DELAY: int = 5         # секунд между попытками переподключения
WS_PING_INTERVAL: int = 30          # heartbeat
WS_MAX_RECONNECT_DELAY: int = 60    # максимум при exponential backoff

# === Агрегация сделок ===
# Принудительный сброс буфера агрегации, если новых fills нет N секунд
FILL_AGG_FLUSH_SEC: int = int(os.getenv("FILL_AGG_FLUSH_SEC", "900"))  # 15 минут

# === Hyperdash ===
HYPERDASH_URL: str = "https://hyperdash.com/address/"

# === Таймзона ===
# Смещение от UTC в часах для отображаемых дат/времени (GMT+4 → Asia/Dubai).
TZ_OFFSET_HOURS: int = int(os.getenv("TZ_OFFSET_HOURS", "4"))

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
# Бот будет принимать команды только от этого chat_id
MY_CHAT_ID: int = int(os.getenv("MY_CHAT_ID", "0"))

# === Hyperliquid ===
HL_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
HL_API_URL: str = "https://api.hyperliquid.xyz"

# Минимальный размер позиции (USD), при котором отправляется уведомление.
# Поставьте 0, чтобы отслеживать все.
MIN_POSITION_USD: float = float(os.getenv("MIN_POSITION_USD", "10000"))

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
FILL_AGG_THRESHOLD: float = float(os.getenv("FILL_AGG_THRESHOLD", "50000"))
# Принудительный сброс буфера агрегации, если новых fills нет N секунд
FILL_AGG_FLUSH_SEC: int = int(os.getenv("FILL_AGG_FLUSH_SEC", "900"))  # 15 минут

# === Hyperdash ===
HYPERDASH_URL: str = "https://hyperdash.com/address/"

# === Таймзона ===
# Смещение от UTC в часах для отображаемых дат/времени (GMT+4 → Asia/Dubai).
TZ_OFFSET_HOURS: int = int(os.getenv("TZ_OFFSET_HOURS", "4"))

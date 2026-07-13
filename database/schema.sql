-- Hyperliquid wallet tracker — SQLite schema (v2, multi-user)

CREATE TABLE IF NOT EXISTS users (
    chat_id             INTEGER PRIMARY KEY,          -- Telegram chat id
    lang                TEXT NOT NULL DEFAULT 'en',   -- 'ru' / 'en'
    min_position_usd    REAL NOT NULL DEFAULT 10000,
    fill_agg_threshold  REAL NOT NULL DEFAULT 50000,
    created_at          INTEGER NOT NULL              -- unix timestamp (sec)
);

CREATE TABLE IF NOT EXISTS wallets (
    chat_id     INTEGER NOT NULL,
    address     TEXT NOT NULL,               -- 0x... lowercase
    label       TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,  -- 1 = слежка вкл., 0 = пауза
    added_at    INTEGER NOT NULL,            -- unix timestamp (sec)
    PRIMARY KEY (chat_id, address)
);

CREATE INDEX IF NOT EXISTS idx_wallets_address
    ON wallets(address);

-- positions / orders / history — глобальные факты об адресе,
-- дедуплицируются между юзерами, подписанными на один и тот же кошелёк.

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet          TEXT NOT NULL,
    coin            TEXT NOT NULL,
    side            TEXT NOT NULL,           -- 'LONG' / 'SHORT'
    size            REAL NOT NULL,           -- абсолютное значение в монете
    notional        REAL NOT NULL,           -- USD
    entry_price     REAL NOT NULL,
    leverage        REAL,
    opened_at       INTEGER NOT NULL,
    closed_at       INTEGER,
    close_price     REAL,
    pnl             REAL
);

CREATE INDEX IF NOT EXISTS idx_positions_wallet
    ON positions(wallet);
CREATE INDEX IF NOT EXISTS idx_positions_open
    ON positions(wallet, coin) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet      TEXT NOT NULL,
    oid         INTEGER NOT NULL,            -- order id from Hyperliquid
    coin        TEXT NOT NULL,
    type        TEXT NOT NULL,               -- 'LIMIT_BUY','LIMIT_SELL','TRIGGER',...
    size        REAL NOT NULL,
    notional    REAL NOT NULL,
    price       REAL NOT NULL,
    status      TEXT NOT NULL,               -- 'open','filled','canceled'
    created_at  INTEGER NOT NULL,
    closed_at   INTEGER,
    UNIQUE(wallet, oid)
);

CREATE INDEX IF NOT EXISTS idx_orders_wallet
    ON orders(wallet);

-- История сырых событий (на всякий случай — для дебага и stats)
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet      TEXT NOT NULL,
    event_type  TEXT NOT NULL,               -- open/close/order_open/order_cancel/order_fill
    coin        TEXT,
    side        TEXT,
    payload     TEXT NOT NULL,               -- JSON
    ts          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_wallet_ts
    ON history(wallet, ts);

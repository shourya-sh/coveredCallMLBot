-- Production-grade candle storage schema for Twelve Data ingestion.
-- Optimized for fast time-series queries, idempotent upserts, and quota-aware ingestion.

CREATE TABLE IF NOT EXISTS symbols (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(16) NOT NULL UNIQUE,
    name TEXT,
    exchange VARCHAR(64),
    asset_type VARCHAR(32),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority SMALLINT NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_symbols_ticker ON symbols (ticker);
CREATE INDEX IF NOT EXISTS idx_symbols_active_priority ON symbols (is_active, priority, ticker);

CREATE TABLE IF NOT EXISTS candles (
    id BIGSERIAL PRIMARY KEY,
    symbol_id BIGINT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    datetime TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 8) NOT NULL,
    high NUMERIC(18, 8) NOT NULL,
    low NUMERIC(18, 8) NOT NULL,
    close NUMERIC(18, 8) NOT NULL,
    volume BIGINT,
    interval VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol_id, datetime, interval)
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_interval_datetime_desc
    ON candles (symbol_id, interval, datetime DESC);

CREATE INDEX IF NOT EXISTS idx_candles_interval_datetime
    ON candles (interval, datetime DESC);

CREATE TABLE IF NOT EXISTS indicators (
    id BIGSERIAL PRIMARY KEY,
    symbol_id BIGINT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    datetime TIMESTAMPTZ NOT NULL,
    interval VARCHAR(16) NOT NULL,
    rsi NUMERIC(12, 6),
    macd NUMERIC(12, 6),
    sma_20 NUMERIC(18, 8),
    sma_50 NUMERIC(18, 8),
    ema_20 NUMERIC(18, 8),
    ema_50 NUMERIC(18, 8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol_id, datetime, interval)
);

CREATE INDEX IF NOT EXISTS idx_indicators_symbol_interval_datetime_desc
    ON indicators (symbol_id, interval, datetime DESC);

CREATE TABLE IF NOT EXISTS ingestion_logs (
    id BIGSERIAL PRIMARY KEY,
    symbol_id BIGINT REFERENCES symbols(id) ON DELETE CASCADE,
    interval VARCHAR(16) NOT NULL,
    last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_candle_time TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL,
    error_message TEXT,
    request_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_logs_symbol_interval_fetched
    ON ingestion_logs (symbol_id, interval, last_fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_logs_status_fetched
    ON ingestion_logs (status, last_fetched_at DESC);

-- Tracks daily API usage for strict quota control (8/min, 800/day).
CREATE TABLE IF NOT EXISTS api_usage_daily (
    usage_date DATE PRIMARY KEY,
    request_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tracks temporary symbol/interval cooldown after repeated failures.
CREATE TABLE IF NOT EXISTS ingestion_state (
    symbol_id BIGINT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    interval VARCHAR(16) NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol_id, interval)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_state_cooldown
    ON ingestion_state (cooldown_until);

-- ════════════════════════════════════════════════════════════════════════════
-- AlphaSync ZeroLoss Strategy — Database Migration
-- Run against PostgreSQL (or SQLite for dev)
-- ════════════════════════════════════════════════════════════════════════════
-- Table 1: zeroloss_signals
-- Stores every signal produced by the ZeroLoss engine (LONG, SHORT, NO_TRADE)
CREATE TABLE IF NOT EXISTS zeroloss_signals (
    id SERIAL PRIMARY KEY,
    user_id UUID NULL,
    symbol VARCHAR(30) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confidence_score FLOAT NOT NULL DEFAULT 0,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('LONG', 'SHORT', 'NO_TRADE')),
    entry_price FLOAT NULL,
    stop_loss FLOAT NULL,
    target FLOAT NULL,
    status VARCHAR(15) NOT NULL DEFAULT 'WAITING' CHECK (
        status IN (
            'WAITING',
            'ACTIVE',
            'PROFIT',
            'BREAKEVEN',
            'STOPLOSS'
        )
    ),
    pnl FLOAT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_zeroloss_signals_symbol ON zeroloss_signals (symbol);

CREATE INDEX IF NOT EXISTS idx_zeroloss_signals_user ON zeroloss_signals (user_id);

CREATE INDEX IF NOT EXISTS idx_zeroloss_signals_status ON zeroloss_signals (status);

CREATE INDEX IF NOT EXISTS idx_zeroloss_signals_ts ON zeroloss_signals (timestamp DESC);

-- Table 2: zeroloss_performance
-- Daily aggregated performance — one row per trading day
CREATE TABLE IF NOT EXISTS zeroloss_performance (
    id SERIAL PRIMARY KEY,
    user_id UUID NULL,
    date DATE NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    profit_trades INTEGER NOT NULL DEFAULT 0,
    breakeven_trades INTEGER NOT NULL DEFAULT 0,
    loss_trades INTEGER NOT NULL DEFAULT 0,
    net_pnl FLOAT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_zeroloss_perf_date ON zeroloss_performance (date DESC);
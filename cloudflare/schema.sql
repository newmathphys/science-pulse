-- Cloudflare D1: состояние Science Pulse на edge.
-- Применение: wrangler d1 execute science-pulse --file=cloudflare/schema.sql
--
-- Группы таблиц:
--   1) edge-данные: knowledge_nodes, saga_transactions, bandit_arms;
--   2) реплика состояния локального SQLite (posts/publications/metrics/sources/kv/seen),
--      принимается через POST /api/state (Bearer INGEST_SECRET).

CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    hook TEXT,
    body TEXT NOT NULL,
    formula_latex TEXT,
    js_arrow_fn TEXT,
    merkle_hash TEXT,
    pagerank REAL DEFAULT 0.05,
    poincare_x REAL DEFAULT 0.0,
    poincare_y REAL DEFAULT 0.0,
    card_r2_url TEXT,
    source_url TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- === 2. Реплика состояния локального SQLite (/api/state) ===

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    hook TEXT,
    body TEXT,
    formula_latex TEXT,
    formula_plain TEXT,
    code TEXT,
    source_name TEXT,
    source_url TEXT,
    tier TEXT,
    quality REAL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL,
    scheduled_for TEXT,
    published_at TEXT,
    card_path TEXT,
    card_file_id TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_status_domain ON posts(status, domain, created_at);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT,
    url TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, platform)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_post_platform ON metrics(post_id, platform);

CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    last_ok TEXT,
    last_error TEXT,
    failures INTEGER DEFAULT 0,
    open_until REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS state_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner TEXT NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS seen (
    hash TEXT PRIMARY KEY,
    post_id TEXT,
    simhash TEXT,
    title_norm TEXT,
    body_norm TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saga_transactions (
    tx_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    tg_message_id INTEGER,
    threads_post_id TEXT,
    status TEXT DEFAULT 'PENDING',
    last_error TEXT,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS bandit_arms (
    arm_name TEXT PRIMARY KEY,
    alpha REAL DEFAULT 1.0,
    beta REAL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_nodes_domain ON knowledge_nodes(domain, created_at);

PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 10000;

CREATE TABLE IF NOT EXISTS user_data (
    user_id TEXT PRIMARY KEY,
    flag TEXT,
    stream_url TEXT,
    elo INTEGER NOT NULL DEFAULT 1200
);

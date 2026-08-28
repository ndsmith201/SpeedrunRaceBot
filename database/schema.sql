PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 10000;

CREATE TABLE IF NOT EXISTS user_data (
    user_id TEXT PRIMARY KEY,
    flag TEXT,
    stream_url TEXT,
    elo INTEGER NOT NULL DEFAULT 1200
);

CREATE TABLE IF NOT EXISTS races (
    interaction_id INTEGER PRIMARY KEY,
    start_time TEXT,
    end_time TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS race_players (
    race_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (race_id, user_id),
    FOREIGN KEY (race_id) REFERENCES races(interaction_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user_data(user_id) ON DELETE CASCADE
);

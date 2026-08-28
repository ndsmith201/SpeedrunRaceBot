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
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    voice_channel_id INTEGER,
    host_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    category TEXT NOT NULL,
    annotation TEXT,
    status TEXT NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    countdown_in_progress INTEGER NOT NULL DEFAULT 0,
    countdown_value INTEGER,
    countdown_starter_id INTEGER,
    show_go_emoji INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    status_message_id INTEGER,
    seed_filename TEXT,
    seed_url TEXT,
    seed_generation_in_progress INTEGER NOT NULL DEFAULT 0,
    seed_generation_error INTEGER NOT NULL DEFAULT 0,
    start_options TEXT NOT NULL DEFAULT '{}',
    elo_processed INTEGER NOT NULL DEFAULT 0,
    elo_api_synced INTEGER NOT NULL DEFAULT 0,
    api_race_finished INTEGER NOT NULL DEFAULT 0,
    async_closes_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS races_active_channel
ON races(channel_id)
WHERE active = 1;

CREATE TABLE IF NOT EXISTS racers (
    race_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_order INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    api_name TEXT,
    is_ready INTEGER NOT NULL DEFAULT 0,
    finish_time TEXT,
    finish_position INTEGER,
    forfeited INTEGER NOT NULL DEFAULT 0,
    api_result_synced INTEGER NOT NULL DEFAULT 0,
    replay_url TEXT,
    elo_change INTEGER,
    PRIMARY KEY (race_id, user_id),
    FOREIGN KEY (race_id) REFERENCES races(interaction_id) ON DELETE CASCADE
);

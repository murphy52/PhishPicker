CREATE TABLE IF NOT EXISTS live_show (
    show_id TEXT PRIMARY KEY,          -- client-generated uuid
    show_date TEXT NOT NULL,
    venue_id INTEGER,
    started_at TEXT NOT NULL,
    current_set TEXT NOT NULL DEFAULT '1',   -- '1','2','3','E'
    reconciled_at TEXT
);

CREATE TABLE IF NOT EXISTS live_songs (
    show_id TEXT NOT NULL REFERENCES live_show(show_id) ON DELETE CASCADE,
    entered_order INTEGER NOT NULL,
    song_id INTEGER NOT NULL,
    set_number TEXT NOT NULL,
    trans_mark TEXT NOT NULL DEFAULT ',',
    entered_at TEXT NOT NULL,
    PRIMARY KEY (show_id, entered_order)
);

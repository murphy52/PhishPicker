-- Schema version tracker
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');

CREATE TABLE IF NOT EXISTS songs (
    song_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    original_artist TEXT,
    debut_date TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_songs_name ON songs(name);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    state TEXT,
    country TEXT
);

CREATE TABLE IF NOT EXISTS tours (
    tour_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT
);

CREATE TABLE IF NOT EXISTS shows (
    show_id INTEGER PRIMARY KEY,
    show_date TEXT NOT NULL,                  -- ISO YYYY-MM-DD
    venue_id INTEGER REFERENCES venues(venue_id),
    tour_id INTEGER REFERENCES tours(tour_id),
    run_position INTEGER,                     -- nth show of a same-venue consecutive run
    run_length INTEGER,                       -- total shows in that run
    tour_position INTEGER,                    -- nth show in tour
    fetched_at TEXT NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_shows_date ON shows(show_date);
CREATE INDEX IF NOT EXISTS idx_shows_venue ON shows(venue_id);

CREATE TABLE IF NOT EXISTS setlist_songs (
    show_id INTEGER NOT NULL REFERENCES shows(show_id),
    -- No CHECK constraint: phish.net uses '1'..'4', 'E' (encore), plus
    -- occasional 'E2'/'E3' (double/triple encore) and 'S' (soundcheck).
    -- Rather than enumerate every corner, we trust the ingest to normalize
    -- (lowercase→uppercase) and accept whatever comes in. Downstream code
    -- matches known labels via equality; unknown labels fall through as
    -- generic "some set" which is fine for feature extraction.
    set_number TEXT NOT NULL,
    position INTEGER NOT NULL,
    song_id INTEGER NOT NULL REFERENCES songs(song_id),
    trans_mark TEXT NOT NULL DEFAULT ',',     -- ',', '>', '->'
    PRIMARY KEY (show_id, set_number, position)
);
CREATE INDEX IF NOT EXISTS idx_setlist_song ON setlist_songs(song_id);
CREATE INDEX IF NOT EXISTS idx_setlist_show ON setlist_songs(show_id);

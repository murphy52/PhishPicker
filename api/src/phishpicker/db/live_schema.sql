CREATE TABLE IF NOT EXISTS live_show (
    show_id TEXT PRIMARY KEY,          -- client-generated uuid
    show_date TEXT NOT NULL,
    venue_id INTEGER,
    started_at TEXT NOT NULL,
    current_set TEXT NOT NULL DEFAULT '1' CHECK (current_set IN ('1','2','3','4','E','E2','E3')),
    reconciled_at TEXT
);

CREATE TABLE IF NOT EXISTS live_songs (
    show_id TEXT NOT NULL REFERENCES live_show(show_id) ON DELETE CASCADE,
    entered_order INTEGER NOT NULL,
    song_id INTEGER NOT NULL,
    set_number TEXT NOT NULL CHECK (set_number IN ('1','2','3','4','E','E2','E3')),
    trans_mark TEXT NOT NULL DEFAULT ',',
    entered_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    superseded_by INTEGER,
    PRIMARY KEY (show_id, entered_order)
);

CREATE TABLE IF NOT EXISTS live_show_meta (
    show_id TEXT PRIMARY KEY REFERENCES live_show(show_id) ON DELETE CASCADE,
    sync_enabled INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT,
    last_error TEXT,
    set1_size INTEGER NOT NULL DEFAULT 9,
    set2_size INTEGER NOT NULL DEFAULT 7,
    encore_size INTEGER NOT NULL DEFAULT 2
);

-- Scoring-game state: one row per live show. frozen_bracket is the pre-show
-- predicted setlist (locked before the first song); snapshots appends the
-- full remaining-setlist prediction each time an entry changes it. Scoring
-- is a pure recompute over this JSON + live_songs — the model is never
-- re-run for scoring (capture-don't-recompute).
CREATE TABLE IF NOT EXISTS live_score_state (
    show_id        TEXT PRIMARY KEY REFERENCES live_show(show_id) ON DELETE CASCADE,
    model_sha      TEXT,
    frozen_bracket TEXT,   -- JSON: [{"set_number","position","song_id"}]
    snapshots      TEXT NOT NULL DEFAULT '[]',
                           -- JSON: [{"after_count":N, "remaining":[{"set_number","position","song_id"}]}]
    updated_at     TEXT
);

-- Finalized post-show scorecards, one per show — the cross-show "best yet?"
-- history. payload holds the full ScoreResult JSON for the recap page.
CREATE TABLE IF NOT EXISTS scorecards (
    show_id        TEXT PRIMARY KEY REFERENCES live_show(show_id) ON DELETE CASCADE,
    show_date      TEXT NOT NULL,
    finalized_at   TEXT NOT NULL,
    combined       REAL NOT NULL,
    foresight_total REAL NOT NULL,
    live_total     REAL NOT NULL,
    ppps           REAL NOT NULL,
    max_streak     INTEGER NOT NULL,
    payload        TEXT NOT NULL
);

-- Web Push subscriptions. endpoint is the full https URL returned by the
-- browser's pushManager.subscribe(); its opaque tail identifies the device.
-- p256dh + auth are the ECDH public key and auth secret the push service
-- needs to encrypt payloads.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    subscribed_at TEXT NOT NULL
);

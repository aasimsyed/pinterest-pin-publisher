-- Pin publishing queue for Cloudflare D1.
-- Rows are inserted by scripts/push_to_d1.py (from generate_pinterest_csv.py
-- output) and consumed by the Worker's cron handler in src/worker.js.

CREATE TABLE IF NOT EXISTS pin_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    media_url       TEXT NOT NULL,        -- public image URL (Cloudflare Pages hosted)
    board_id        TEXT NOT NULL,        -- Pinterest board ID, not the display name
    description     TEXT,
    link            TEXT,                 -- destination URL, filled in manually per your workflow
    keywords        TEXT,                 -- comma-separated, stored for reference/reporting only --
                                           -- Pinterest's v5 API has no keywords field on the pin itself
    publish_at      TEXT NOT NULL,        -- ISO-8601 datetime, e.g. 2026-07-22T09:00:00Z
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | published | failed
    pinterest_pin_id TEXT,                -- set after a successful publish
    error_message   TEXT,                 -- set if a publish attempt fails
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    published_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_pin_queue_due
    ON pin_queue (status, publish_at);

-- Caches the current Pinterest access token so the Worker doesn't have to
-- refresh it on every single cron tick (access tokens are short-lived;
-- refresh tokens are long-lived and stored as a Worker secret, not here).
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id           INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    access_token TEXT NOT NULL,
    expires_at   TEXT NOT NULL                        -- ISO-8601 datetime
);


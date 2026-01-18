-- 0001_instrument_definitions.sql
--
-- MXM V1 Marketdata SQLite schema:
-- Instrument definition persistence (Databento-sourced) as an append-only event log,
-- with per-feed watermarks and a materialised current view.

PRAGMA foreign_keys = ON;

-- A) Append-only event log (authoritative)
CREATE TABLE IF NOT EXISTS instrument_definition_events (
    event_uid TEXT PRIMARY KEY,

    -- Provenance / ingestion scope identity (vendor-scoped feed key)
    feed TEXT NOT NULL,

    publisher_id INTEGER NOT NULL,
    instrument_id INTEGER NOT NULL,

    ts_event TEXT NOT NULL,   -- ISO8601 UTC with Z (lexicographically sortable)
    ts_recv  TEXT NOT NULL,   -- ISO8601 UTC with Z (lexicographically sortable); extracted from index

    security_update_action TEXT NOT NULL,

    rtype INTEGER,            -- optional; uint8 in source frame

    payload_json TEXT NOT NULL, -- canonicalised JSON payload

    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Feed-scoped ordering index (critical for incremental ingestion/debug)
CREATE INDEX IF NOT EXISTS idx_idevents_feed_ordering
ON instrument_definition_events (feed, ts_recv, ts_event, publisher_id, instrument_id);

-- Key lookup index (optional but useful)
CREATE INDEX IF NOT EXISTS idx_idevents_key
ON instrument_definition_events (publisher_id, instrument_id);

-- Optional: key lookup constrained by feed (useful for audits)
CREATE INDEX IF NOT EXISTS idx_idevents_feed_key
ON instrument_definition_events (feed, publisher_id, instrument_id);

-- B) Ingestion watermarks (one row per feed)
CREATE TABLE IF NOT EXISTS instrument_definition_watermarks (
    feed TEXT PRIMARY KEY,
    ts_recv_last TEXT NOT NULL, -- ISO8601 UTC with Z
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- C) Materialised current view (one row per (publisher_id, instrument_id))
CREATE TABLE IF NOT EXISTS instrument_definition_current (
    publisher_id INTEGER NOT NULL,
    instrument_id INTEGER NOT NULL,

    -- Provenance: which feed last updated this instrument state
    feed TEXT NOT NULL,

    ts_event TEXT NOT NULL,
    ts_recv  TEXT NOT NULL,

    security_update_action TEXT NOT NULL,

    rtype INTEGER,

    payload_json TEXT NOT NULL,
    event_uid TEXT NOT NULL,

    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    PRIMARY KEY (publisher_id, instrument_id)
);

CREATE INDEX IF NOT EXISTS idx_idcurrent_feed_ordering
ON instrument_definition_current (feed, ts_recv, ts_event, publisher_id, instrument_id);

CREATE INDEX IF NOT EXISTS idx_idcurrent_ordering
ON instrument_definition_current (ts_recv, ts_event, publisher_id, instrument_id);

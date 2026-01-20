-- 0002_instrument_definition_mappings.sql
--
-- MXM V1 Marketdata SQLite schema:
-- Instrument identity mapping layer (MXM FuturesContract ↔ Databento instrument definitions).
--
-- Purpose:
--   Persist a deterministic, explainable mapping from MXM monthly outright futures contracts
--   (product_id, contract_year, contract_month) to Databento (publisher_id, instrument_id),
--   derived from instrument_definition_current.
--
-- Design:
--   * Append-only (no silent mutation).
--   * Idempotent inserts via deterministic mapping_uid (computed by builder).
--   * Stores denormalised maturity/lifecycle fields for explainability and fast resolution.
--
-- Notes:
--   * Bars live in Parquet for MVP; no bar payload tables are introduced here.
--   * Mapping builder filters to outrights: security_type='FUT' and instrument_class='F'.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instrument_definition_mappings (
    -- Deterministic primary key; computed by mapping builder (e.g., sha256 of identity fields)
    mapping_uid TEXT PRIMARY KEY,

    -- Ingestion/creation timestamp (system time)
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    -- MXM contract key (MVP: monthly contracts only)
    product_id     TEXT    NOT NULL,
    contract_year  INTEGER NOT NULL,
    contract_month INTEGER NOT NULL,

    -- Databento provenance / identity
    feed          TEXT    NOT NULL,   -- definition feed used as source for mapping
    dataset       TEXT    NOT NULL,   -- e.g. 'GLBX.MDP3'
    publisher_id  INTEGER NOT NULL,
    instrument_id INTEGER NOT NULL,

    -- Denormalised payload fields (for explainability / debugging / fast reads)
    raw_symbol       TEXT    NOT NULL,
    security_type    TEXT    NOT NULL,   -- expect 'FUT'
    instrument_class TEXT    NOT NULL,   -- expect 'F' for outright futures
    maturity_year    INTEGER NOT NULL,
    maturity_month   INTEGER NOT NULL,
    activation       TEXT,               -- vendor lifecycle start (UTC ISO8601)
    expiration       TEXT,               -- vendor lifecycle end (UTC ISO8601)

    -- Validity window for mapping resolution (time-aware lookups)
    valid_from TEXT NOT NULL,            -- typically activation; else ts_event fallback
    valid_to   TEXT,                     -- typically expiration; nullable

    -- Provenance of the specific definition snapshot used for mapping
    definition_event_uid TEXT NOT NULL,  -- event_uid from instrument_definition_events/current
    mapping_reason       TEXT NOT NULL   -- e.g. 'exact_maturity_match.instrument_class_F'
);

-- MXM lookup: (product_id, year, month) -> instrument_id
CREATE INDEX IF NOT EXISTS idx_idmap_mxm_key
ON instrument_definition_mappings (product_id, contract_year, contract_month);

-- Vendor lookup: instrument_id -> MXM contract(s)
CREATE INDEX IF NOT EXISTS idx_idmap_vendor_key
ON instrument_definition_mappings (publisher_id, instrument_id);

-- Time-aware resolution (choose mapping valid at a given as_of date)
CREATE INDEX IF NOT EXISTS idx_idmap_validity
ON instrument_definition_mappings (product_id, valid_from, valid_to);

-- Audits/debugging by feed
CREATE INDEX IF NOT EXISTS idx_idmap_feed
ON instrument_definition_mappings (feed);

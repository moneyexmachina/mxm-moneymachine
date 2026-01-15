# Databento Notes (Week 1 — Session 2)

**Session:** MVP Session 2 — Databento exploration  
**Date:** 2025-01-12  
**Timebox:** 13:00–15:00  
**Objective:** Build a concrete mental model of Databento’s futures data model and how MXM can consume daily OHLCV safely and economically.

---

## 1. Scope and Non-Goals

### 1.1 Scope
- Futures market data exploration
- Daily OHLCV bars retrieval
- Instrument discovery (exchange → product → contract)
- Identifier semantics and stability assessment
- Request mechanics and response inspection
- Basic cost/limits sanity check

### 1.2 Explicit Non-Goals
- No persistence or caching
- No idempotency logic
- No ingestion pipeline
- No abstractions/wrappers
- No broad backfills (only tiny test pulls)
- No final mapping commitments beyond exploratory notes

---

## 2. Databento Surface Overview

### 2.1 Key Concepts (Vendor World)
- **Datasets:**  
- **Schemas / record types:**  
- **Symbology / identifiers:**  
- **Exchanges / venues:**  
- **Instruments vs contracts vs continuous series:**  

### 2.2 Account and Access

[Databento documentation](https://databento.com/docs/)
[The terms of use](https://databento.com/legal/terms-of-use)
[End user agreement](https://databento.com/legal/databento-user-agreement)

Account creation — debit card acceptance issue
so failed on the initial step...
I have contacted databento support... and am waiting for their confirmation.


## Access Notes

- Databento account creation initially failed because the payment processor requires a **true credit card**; debit and prepaid cards are not accepted (confirmed by Databento support).
- Several alternative approaches were considered (other vendors, company-based payment), but these were intentionally avoided to keep the MVP scoped to **personal trading under CGT**.
- Access was ultimately unblocked by successfully obtaining a **UK personal credit card** via a consumer credit product that supports non-employment income categories.
- Payment-based identity verification then succeeded, and full Databento dashboard access was obtained.


- Account status: Now Live!
- API key storage method (`mxm-secrets`):
- Environment (machine, venv, python version):
- Libraries used (python client version, etc.):

Databento API key is stored at mxm/dev/databento/api-key and retrievable via both the mxm_secrets CLI and get_secret() in Python.


## 3. Datasets and Coverage

```python
================================================================================
MXM V1 — Databento Proof 1: Dataset + schema sanity
================================================================================
Timestamp (UTC): 2026-01-13T11:58:33.662805Z
Auth:            mxm_secrets.get_secret('mxm/dev/databento/api-key')
Dataset:         GLBX.MDP3
Target schema:   ohlcv-1d
Fields encoding: csv
--------------------------------------------------------------------------------
Schemas available for dataset (excerpt):
[
  "bbo-1m",
  "bbo-1s",
  "definition",
  "mbo",
  "mbp-1",
  "mbp-10",
  "ohlcv-1d",
  "ohlcv-1h",
  "ohlcv-1m",
  "ohlcv-1s",
  "statistics",
  "status",
  "tbbo",
  "trades"
]
Target schema present? True
--------------------------------------------------------------------------------
Entitled dataset range (metadata.get_dataset_range):
{
  "end": "2026-01-13T03:58:33.117285000Z",
  "schema": {
    "bbo-1m": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "bbo-1s": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "definition": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "mbo": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2017-05-21T00:00:00.000000000Z"
    },
    "mbp-1": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "mbp-10": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "ohlcv-1d": {
      "end": "2026-01-13T00:00:00.000000000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "ohlcv-1h": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "ohlcv-1m": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "ohlcv-1s": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "statistics": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "status": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "tbbo": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    },
    "trades": {
      "end": "2026-01-13T03:58:33.117285000Z",
      "start": "2010-06-06T00:00:00.000000000Z"
    }
  },
  "start": "2010-06-06T00:00:00.000000000Z"
}
--------------------------------------------------------------------------------
Fields for schema=ohlcv-1d encoding=csv (metadata.list_fields):
[
  {
    "name": "ts_event",
    "type": "int"
  },
  {
    "name": "rtype",
    "type": "int"
  },
  {
    "name": "publisher_id",
    "type": "int"
  },
  {
    "name": "instrument_id",
    "type": "int"
  },
  {
    "name": "open",
    "type": "int"
  },
  {
    "name": "high",
    "type": "int"
  },
  {
    "name": "low",
    "type": "int"
  },
  {
    "name": "close",
    "type": "int"
  },
  {
    "name": "volume",
    "type": "int"
  }
]
--------------------------------------------------------------------------------
Publishers filtered for dataset match (metadata.list_publishers):
[
  {
    "dataset": "GLBX.MDP3",
    "description": "CME Globex MDP 3.0",
    "publisher_id": 1,
    "venue": "GLBX"
  }
]
================================================================================
```

Dataset: GLBX.MDP3 (publisher_id 1, venue GLBX, “CME Globex MDP 3.0”)

Available schemas: definition, status, statistics, trades, tbbo, mbp-1, mbp-10, mbo, and derived bar schemas ohlcv-1s/1m/1h/1d, plus bbo-1s/1m

Entitled history start: 2010-06-06 for most schemas (MBO starts 2017-05-21)

Daily bars end: ohlcv-1d available through 2026-01-13T00:00:00Z (day boundary)

OHLCV-1d fields via list_fields(..., encoding="csv"):

ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume

Notably no symbol and no ts_recv in the CSV field list (important implication below)


### Proof 3 — Cost gate for daily OHLCV (`ohlcv-1d`)

**Dataset:** `GLBX.MDP3` (CME Globex MDP 3.0)  
**Schema:** `ohlcv-1d`  
**Symbology:** `stype_in = raw_symbol`  
**Window:** `2026-01-03 → 2026-01-13` (10 days, clamped to dataset entitlement end)

Cost estimates via `metadata.get_cost`:

| Symbol | Cost (USD) | Notes |
|------|-----------:|-------|
| `ESZ5` | `0.0` | Fully covered by plan / minimum billable size |
| `ESH6` | `7.93e-05` | Non-zero but negligible |
| `CLG6` | `7.93e-05` | Non-zero but negligible |
| `CLH6` | `7.93e-05` | Non-zero but negligible |

**Observations:**
- `metadata.get_cost` works as expected for `ohlcv-1d` on outright futures contracts.
- Daily bars over short windows are effectively free or near-zero cost.
- `raw_symbol` symbology is sufficient for cost gating on explicit contracts.
- Dataset entitlement end date must be respected to avoid 422 errors.

**Conclusion:**
Cost gating is viable and should be treated as a mandatory pre-step before any time-series pull.



**Important clarification (cost):**
The near-zero costs observed in Proof 3 apply only to a tiny 10-day sample window.
They do not imply that daily data is "free" at production scale. A full research backfill
(≈15 years × contract chains × 100+ products) will be materially billable, and must be
budgeted using `metadata.get_cost` / `metadata.get_billable_size` before executing.



### Proof 4 — Daily OHLCV pull for a single active futures contract

**Objective:**  
Verify that Databento can deliver daily OHLCV bars for a *specific, explicitly named CME futures contract* with clear identity and usable structure.

**Dataset:** `GLBX.MDP3` (CME Globex MDP 3.0)  
**Schema:** `ohlcv-1d`  
**Symbology:** `stype_in = raw_symbol`  
**Contract:** `ESH6` (E-mini S&P 500, March 2026)  
**Window:** `2026-01-03 → 2026-01-13` (end exclusive)

#### Result Summary

- **Rows returned:** 8 daily bars
- **Index:** `ts_event` (UTC, `datetime64[ns, UTC]`)
- **Time bounds:**
  - Min: `2026-01-04 00:00:00Z`
  - Max: `2026-01-12 00:00:00Z`
- **Daily cadence:** one row per trading day (no weekends)

#### Returned Columns

| Column | Type | Notes |
|------|------|-------|
| `ts_event` | datetime (index) | Inclusive start of daily aggregation period (UTC) |
| `rtype` | uint8 | Record type (`35` = OHLCV-1d) |
| `publisher_id` | uint16 | `1` = CME Globex (Databento publisher) |
| `instrument_id` | uint32 | Stable Databento instrument identifier |
| `symbol` | object | Requested raw symbol (`ESH6`) |
| `open` | float64 | Daily open price |
| `high` | float64 | Daily high price |
| `low` | float64 | Daily low price |
| `close` | float64 | Daily close price |
| `volume` | uint64 | Total traded volume during aggregation period |

**Identity clarity:**  
Each bar is unambiguously attributable via:
- `(dataset, instrument_id)` as the canonical identifier, and
- `symbol` retained as a convenience / human-readable label.

#### Key Observations

- Prices are returned **already scaled** as floating-point values (no manual 1e-9 rescaling required at the Python/DataFrame level).
- `ts_event` aligns to **00:00:00 UTC** for daily bars.
- Contract expiry matters: expired contracts (e.g. `ESZ5` in Jan 2026) correctly return empty datasets.
- Active contracts (e.g. `ESH6`) return complete daily bars as expected.

#### Conclusion (Session 3 Capability)

It is now technically established that:

> **Databento can be used as a daily-bar provider on an instrument-by-instrument basis for CME futures, with explicit contract identification, cost gating, and clean DataFrame outputs suitable for MXM V1.**

This satisfies the Session 3 success condition.

#### Explicitly Deferred (to later sessions)

- Precise interpretation of *what the daily bar represents* (Globex session vs settlement vs calendar day).
- Alignment of `ts_event` with exchange trading sessions and holidays.
- Validation against CME settlement prices.
- Contract-chain construction and rolling logic.
- Evaluation of Databento as a replacement or supplement for `mxm-refdata`.

These are **semantic and design questions**, not blockers to technical capability, and will be addressed separately.


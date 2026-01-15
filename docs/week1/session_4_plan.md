# MXM V1 — Session 4 Plan (Morning Session, 2025-01-14 09:00–12:30)

**Session focus:**  
Design and implement the *minimal, end-to-end market data spine* for Databento daily bars, with strict scope control and clear proofs of correctness.

This session is about **making one thing work completely**, not about generality.

## Session 4 Objective

By the end of this morning session, we must be able to say:

> “MXM can ingest daily bars from Databento once, store them in our own opinionated format, and serve them back to downstream code **without ever touching Databento again**.”

## Success Criteria (Proofs)

Session 4 is successful if **all** of the following are true:

1. A single Databento daily-bar pull (golden path) can be:
   - cost-gated,
   - ingested,
   - persisted to disk.

2. The same data can be:
   - read back via an internal MXM API,
   - returned as a clean DataFrame in our canonical schema,
   - with *no Databento call made*.

3. Re-running the ingestion for the same range:
   - does not duplicate rows,
   - does not corrupt the store,
   - is idempotent.

Golden-path test case:
- Dataset: `GLBX.MDP3`
- Schema: `ohlcv-1d`
- Contract: `ESH6`
- Window: `2026-01-03 → 2026-01-13`

## Explicit Non-Goals (Out of Scope)

Do **not** implement or design today:

- multiple vendors
- spreads / expressions
- FX conversion
- continuous contracts / rolls
- intraday schemas
- full universe ingestion
- refdata integration beyond what is strictly required
- session/holiday semantics validation

If it does not serve the success criteria above, it is deferred.

## Work Plan (Ordered, Time-Boxed)

### Phase 1 — Lock the Storage Contract (≈ 30–40 min)

**Goal:** Decide and freeze the on-disk representation.

Tasks:
- Decide file format: **Parquet**
- Define canonical daily-bar schema:
  - required columns
  - dtypes
  - time index convention (`ts_event`, UTC)
- Decide sort order and deduplication key:
  - primary key: `ts_event`
- Decide minimal metadata sidecar contents

Deliverable:
- Written schema definition (inline comment or short doc snippet)
- Agreement: “This is the format downstream will consume.”

### Phase 2 — Implement Marketdata Store (≈ 60 min)

**Goal:** Build the read/write spine independent of Databento.

Tasks:
- Implement `write_daily_bars(...)`
  - input: canonical DataFrame + instrument identity
  - behavior:
    - load existing Parquet if present
    - append + deduplicate on `ts_event`
    - sort
    - atomic write (temp file + rename)
- Implement `read_daily_bars(...)`
  - input: instrument identity + date range
  - output: canonical DataFrame

Proof:
- Write a small dummy DataFrame → read it back → verify equality.
- Run write twice with overlapping dates → no duplication.

### Phase 3 — Golden-Path Ingestion (≈ 45–60 min)

**Goal:** Connect Databento → Store once, correctly.

Tasks:
- Implement minimal Databento pull function:
  - inputs: dataset, schema, symbol, start, end
  - output: raw DataFrame
- Add cost gate before pull:
  - fail hard if estimated cost > cap
- Normalize pulled DataFrame into canonical schema
- Call `write_daily_bars(...)`
- Persist minimal pull metadata (can be JSON for now)

Proof:
- Run ingestion for `ESH6` over test window.
- Verify:
  - rows written to Parquet
  - metadata written
  - no exceptions

### Phase 4 — Store-Only Serving Proof (≈ 20–30 min)

**Goal:** Prove downstream decoupling from Databento.

Tasks:
- Implement minimal public API:
  - `get_daily_bars(mxm_contract_or_instrument_id, start, end)`
  - **store-only**, no vendor fallback
- Call API for `ESH6`
- Compare output against ingested data

Proof:
- Logs confirm:
  - no Databento session opened
  - data served purely from local store

## Expected End State (12:30)

By the end of Session 4, you should have:

- A fixed, opinionated Parquet schema for daily bars
- A working marketdata store (read/write, idempotent)
- A golden-path Databento ingestion that populates the store
- A store-only serving API for downstream use
- High confidence that:
  - API cost is controlled
  - data ownership has shifted from vendor to MXM

Anything beyond this belongs to Session 5 or later.

## Guardrail for the Session

Whenever you are tempted to add a feature, ask:

> “Is this required to prove that one Databento daily-bar series can be ingested once and served many times without re-querying?”

If the answer is **no**, stop and defer.


# session_22c_plan.md — MXM V1
## Session 22c — Inspection Architecture Expansion and statistics_1d Inspector

## Session context

### Where we are (after Sessions 22 and 22b)

**Session 22**
- Completed hermetic idempotency validation for `statistics_1d`.
- Proved ingestion repeatability and ledger correctness.

**Session 22b**
- Integrated `statistics_1d` into the product-level meta-orchestrator as Stage 4.
- Hardened control-plane semantics:
  - deterministic stage ordering
  - correct budget propagation
  - downstream gating integrity
  - exception terminalisation
- Introduced first dedicated test suite for `product_marketdata.py`.

At this point, the **control-plane is complete and defended**.

What remains unfinished in the broader Session 22 scope:

1. Inspection tooling for `statistics_1d`
2. Derived daily settlement surface (`get_settlement_1d`)
3. Full-universe daily update workflow
4. Visualisation layer (settlement, volume, diagnostics)

Session 22c focuses on item (1) and prepares for item (2).

## Session 22c intent

Session 22c has two tightly related objectives:

1. Clarify and formalise the **inspection module architecture**.
2. Implement inspection support for `statistics_1d` alongside `ohlcv_1d`.

This is an operator-surface session.

No ingestion semantics change.
No completeness refactors.
No economic modelling yet.

# Part A — Clarify inspection architecture

## A1. Why inspection matters

Inspection tooling answers operator questions:

- Do we have data?
- What is the coverage window?
- Is it plausibly shaped?
- Are there anomalies or gaps?
- Are settlement events finalised?
- Did ingestion attempt recently fail?

Without this surface, debugging full-universe runs becomes opaque.

Inspection is not analytics.
Inspection is not reporting.
Inspection is not completeness validation.

It is **observability**.

## A2. Current inspection state (ohlcv_1d)

Before extending to `statistics_1d`, we must clarify:

- Where does `ohlcv_1d` inspection live?
- Is it pure transform logic?
- Is CLI separate from core functions?
- Is it JSON-serialisable?
- Are there shared patterns we should preserve?

### Desired architectural principles

Inspection modules should:

- Be dataset-scoped (e.g. `inspect/ohlcv_1d.py`, `inspect/statistics_1d.py`)
- Expose pure functions returning JSON-serialisable dicts
- Avoid printing / side effects
- Avoid implicit global state
- Be testable via small dataframe fixtures
- Not depend on CLI concerns

CLI wrappers should:

- Live in `scripts/marketdata/inspect/...`
- Format JSON or human-readable summaries
- Not contain business logic

## A3. Proposed inspection module structure

```
mxm/v1/marketdata/inspect/
    __init__.py
    ohlcv_1d.py
    statistics_1d.py
```

Each dataset module exposes:

- `inspect_<dataset>_instrument(...)`
- `inspect_<dataset>_attempts(...)`

Future possibility (not in scope now):

- Shared helpers in `inspect/_common.py`

# Part B — Implement statistics_1d inspection

## B1. Inspection scope (MVP)

The statistics dataset is an **event stream**, not a daily surface.

Inspection must therefore reveal:

- Event density
- Stat type distribution
- Settlement-specific structure
- Finalisation patterns
- Timestamp integrity

We do not yet derive economic surfaces here.

## B2. Core function: per-instrument inspection

### Signature

```python
inspect_statistics_1d_instrument(
    *,
    store: Statistics1DStore,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start=None,
    end=None,
    sample_n: int = 5,
) -> dict
```

### Required report structure (MVP)

```
{
  "identity": {...},
  "rows": {
      "row_count": int,
      "min_ts_event": "...",
      "max_ts_event": "...",
      "min_ts_recv": "...",
      "max_ts_recv": "..."
  },
  "distributions": {
      "stat_type_counts": {...},
      "settlement": {
          "is_final_counts": {...},
          "is_actual_counts": {...},
          "stat_flags_topk": [...]
      }
  },
  "quality": {
      "ts_ref_null_count": int,
      "ts_ref_null_fraction": float
  },
  "samples": {
      "head": [...],
      "tail": [...]
  }
}
```

All values must be JSON-serialisable.

## B3. Settlement-specific diagnostics

For `stat_type == 3` (settlement):

Include:

- Number of events per trading_date (optional)
- Count of final vs non-final
- Whether multiple finals occur
- Latest event timestamp

This prepares directly for Session 22d (daily settlement derivation).

## B4. Attempts inspection

Implement:

```
inspect_statistics_1d_attempts(product_id, limit=200)
```

Include:

- Status counts
- Recent failures
- Last attempt per contract
- Incomplete contracts

This mirrors the ohlcv inspection approach.

## B5. Testing strategy

Unit tests:

- Pure dataframe transform tests
- stat_type distribution correctness
- settlement breakdown correctness
- null handling
- empty dataframe handling

Integration test:

- Ingest fixture
- Call inspector
- Assert non-empty and required keys exist

No vendor calls.
No parquet I/O in tests (use in-memory dataframes or patch store read).

# Part C — Prepare for daily_stats surface

Session 22c does not implement the daily settlement view yet,
but must architect with it in mind.

## C1. Why inspection precedes daily view

Before building:

```
get_settlement_1d(...)
```

we must be confident that:

- Final flags are stable
- Multiple finals are rare or deterministic
- Event sequences are monotonic
- ts_event and sequence ordering are reliable

Inspection provides this validation surface.

## C2. Next session preview (Session 22d)

Session 22d will:

1. Implement pure selection logic:
   - final > latest fallback
   - deterministic tie-breaking
2. Expose `get_settlement_1d(...)`
3. Add unit tests
4. Add basic plotting script
5. Run full-universe daily update

Session 22c is the prerequisite for 22d.

# Definition of Done — Session 22c

Session 22c is complete when:

1. `statistics_1d` inspection module exists.
2. Inspector returns structured JSON for:
   - per-instrument
   - attempts
3. Unit tests exist for transform logic.
4. CLI wrapper can print inspection summary.
5. Manual inspection of at least one contract has been performed.

# Broader roadmap (this week)

After Session 22c:

- Session 22d — Daily settlement derivation
- Session 22e — Full-universe daily update runner
- Session 22f — Visualisation layer (settlement + volume curves)

Goal:

> End of week: fully running daily update with inspectable, plottable settlement surface across the full contract universe.

## Closing note

Session 22c transitions the marketdata module from:

> Control-plane complete

to

> Operator-observable and economically interpretable

It is the bridge between ingestion correctness and economic surface generation.

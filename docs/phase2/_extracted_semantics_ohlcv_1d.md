# Extracted Semantics — OHLCV-1D (Working Notes)

> ⚠️ This document is **non-authoritative**.
> It is a forensic extraction of semantics as found in planning documents,
> schemas, and code. It exists to support later consolidation into an
> authoritative semantics specification.

## A. Extracted from Planning Document  
**Source:** “MXM V1 — OHLCV-1D State & Retry Model (Phase 2)”  
**Status in source:** Draft  
**Introduced:** S12.2  
**Scope:** `datasets/ohlcv_1d` orchestrator and meta-orchestrator

## A.1 Purpose (as stated)

The planning document defines a **derived state model** and **retry decision logic**
for OHLCV-1D ingestion.

It explicitly separates:

1. **Observed outcomes**  
   (attempt ledger rows)

2. **Derived operational state**  
   (small, stable, policy-relevant)

3. **Execution decisions**  
   (`attempt`, `noop`, `stop`)

Stated goals:
- deterministic behaviour
- idempotent retries
- clean reasoning about partial data, vendor limits, and failures

## A.2 Background assumptions

- Each orchestrator run records **exactly one attempt row per contract considered**
  in an append-only `ohlcv_1d_attempts` ledger.

- Attempt rows record:
  - expected window surfaces
  - coverage snapshots
  - outcome status
  - vendor finality
  - error information (if any)

- **Derived state** is computed from:
  - the latest attempt (if any)
  - the current expected window
  - the current storage coverage

- Derived state **drives retry behaviour**.

## A.3 Action space (minimal)

All orchestration decisions reduce to exactly one of:

- `noop` — take no ingestion action for this contract
- `attempt_ingest` — attempt vendor ingestion
- `stop_run` — stop the orchestrator run (systemic failure)

Actions are:
- produced by a decision function
- executed by the orchestrator

## A.4 Derived state vocabulary (planning-level)

The planning document defines a **small, stable derived state enum**.
These states are explicitly described as **policy-level concepts**,
intended to remain stable even if low-level attempt statuses evolve.

### A.4.1 DONE

**Definition (verbatim):**  
> No further ingestion action is possible or necessary under current surfaces.

Includes:
- fully complete coverage, or
- partial coverage where `vendor_final == true`

Planned action: `noop`

### A.4.2 BLOCKED_UNMAPPED

**Definition (verbatim):**  
> The contract cannot be ingested because no vendor mapping exists.

Notes:
- explicitly not an error condition

Planned action: `noop`

### A.4.3 BLOCKED_EMPTY_EXPECTED

**Definition (verbatim):**  
> The expected window is empty after intersecting:
> interest × dataset availability × lifecycle.

Notes:
- there is nothing to ingest

Planned action: `noop`

### A.4.4 NEEDS_INGEST

**Definition (verbatim):**  
> Further vendor ingestion may improve coverage.

Includes:
- no coverage
- partial coverage with `vendor_final == false`
- first-time attempts
- dry-run observations
- budget-skipped attempts

Planned action: `attempt_ingest`

### A.4.5 RETRYABLE_ERROR

**Definition (verbatim):**  
> A previous ingestion attempt failed due to a transient operational error.

Examples listed:
- network timeouts
- temporary vendor API failures
- transient database locks

Planned action:
- `attempt_ingest` (subject to retry policy)

### A.4.6 FINAL_ERROR

**Definition (verbatim):**  
> A non-recoverable failure under current assumptions.

Examples listed:
- repeated identical failures exceeding retry limits
- vendor-final expected window with persistent failure
- schema incompatibility
- corrupted local storage

Planned action:
- `noop` (per-contract), or
- `stop_run` if classified as systemic

### A.4.7 SKIPPED_BUDGET

**Definition (verbatim):**  
> Ingestion was skipped due to run-level budget constraints.

Notes:
- explicitly stated to be *not a data state*
- does not imply completion

Planned action:
- `noop` (eligible in future runs)

### A.4.8 UNKNOWN

**Definition (verbatim):**  
> State derivation failed or invariants were violated.

Notes:
- indicates bug or corruption

Planned action:
- `stop_run`

## A.5 Derived State → Action mapping (planning-level)

| Derived State           | Planned Default Action |
|------------------------|------------------------|
| DONE                   | `noop` |
| BLOCKED_UNMAPPED       | `noop` |
| BLOCKED_EMPTY_EXPECTED | `noop` |
| SKIPPED_BUDGET         | `noop` |
| NEEDS_INGEST           | `attempt_ingest` |
| RETRYABLE_ERROR        | `attempt_ingest` (policy-gated) |
| FINAL_ERROR            | `noop` or `stop_run` |
| UNKNOWN                | `stop_run` |

## A.6 Derivation principles (planning intent)

The planning document states the following principles explicitly:

1. **Coverage beats history**  
   Derived state should prefer *current coverage vs expected window* over
   prior attempt status.

2. **Vendor finality is decisive**  
   If `vendor_final == true`, retries cannot improve coverage.

3. **Errors are not incompleteness**  
   Operational failures must be distinguished from missing data.

4. **Budget is not state**  
   Budget skips do not change data completeness.

## A.7 Reference function signatures (planning intent)

### State derivation

```python
derive_state(
    *,
    latest_attempt: OHLCV1DAttemptRow | None,
    expected_window: ExpectedWindow,
    coverage_now: CoverageSnapshot | None,
) -> DerivedState
```

Declared requirements:
- pure
- deterministic
- side-effect free

### Decision logic

```python
decide_action(
    *,
    state: DerivedState,
    policy: RetryPolicy,
    budgets: BudgetContext,
    latest_attempt: OHLCV1DAttemptRow | None,
) -> Decision
```

Decision includes:
- action (`noop`, `attempt_ingest`, `stop_run`)
- reason (for reporting/debugging)

## A.8 Explicit non-goals (Phase 2, planning)

- no automatic mapping rebuilds
- no conditional local resets
- no cross-dataset coordination
- no long-term state persistence beyond the attempts ledger



## B. Extracted from SQLite Schema — `ohlcv_1d_attempts`
**Source:** `0003_ohlcv_1d_attempts.sql`  
**Table:** `ohlcv_1d_attempts`  
**Declared purpose (schema header):** append-only operational attempts ledger; supports retry/state logic; does not encode the state machine itself.

### B.0 Ledger-level assertions (explicit in schema design notes)

- The table is **append-only** (no silent mutation).
- The table intentionally uses **no foreign keys** (ingestion must not be blocked by upstream incompleteness).
- Timestamps are stored as **ISO8601Z `TEXT`**, intended to support lexicographic ordering stability.
- The table is described as an **operational ledger**, not a canonical truth table.

Implication:
- “Latest attempt” is a query convention, not a unique constraint in the schema.
- Multiple attempts for the same contract/run can exist unless prevented by code (schema does not prevent it).

## B.1 Column-level semantics (representable dimensions)

### B.1.1 Primary identity & system time

- `attempt_uid` (TEXT, PK)
  - Unique identifier for the ledger row. Schema implies **attempt rows are first-class events**.

- `created_at` (TEXT, NOT NULL, default now)
  - System timestamp for row creation (system-plane time).
  - Schema implies this is not the control-plane run timestamp (separate column exists).

### B.1.2 Orchestrator run metadata (control-plane inputs)

- `run_ts_utc` (TEXT, NOT NULL)
  - Orchestrator report timestamp (control-plane).
  - Implies attempts are grouped into a run via this value.

- `mode` (TEXT, NOT NULL)
  - Enumerated by comment: `"bootstrap" | "update"`.

- `dry_run` (INTEGER, NOT NULL, default 0)
  - Run-level flag stored per attempt row; implies decisions can be recorded without ingestion.

- `reset_local` (INTEGER, NOT NULL, default 0)
  - Run-level flag stored per attempt row; implies destructive local reset may be part of operational context.

### B.1.3 MXM contract identity (operational keys)

- `product_id` (TEXT, NOT NULL)
  - Product-level grouping key.

- `contract_id` (TEXT, NOT NULL)
  - Contract identifier (internal).

- `contract_key` (TEXT, NOT NULL)
  - Human-readable/stable operational key (example: `"cme_emini_snp500_futures:2017-12"`).
  - Implies an intended display key separate from internal IDs.

### B.1.4 Vendor identity (nullable; mapping may be absent)

- `feed` (TEXT, nullable)
  - Optional vendor feed identity.

- `dataset` (TEXT, nullable)
- `publisher_id` (INTEGER, nullable)
- `instrument_id` (INTEGER, nullable)
- `raw_symbol` (TEXT, nullable)

Implications:
- The ledger can represent **unmapped/unresolved vendor identity** (via nullability).
- Vendor identity is not enforced as complete even if present (no NOT NULL constraints).
- The schema supports multiple vendor identity granularities (dataset/publisher/instrument/raw_symbol).

### B.1.5 Window surfaces (all stored as ISO8601Z TEXT; half-open semantics stated)

#### Interest window (from refdata; half-open [start,end))

- `interest_start` (TEXT, NOT NULL)
- `interest_end` (TEXT, NOT NULL)

Implication:
- Interest window is always defined for considered contracts.

#### Dataset availability surface (from vendor dataset_range; half-open [start,end))

- `dataset_start` (TEXT, NOT NULL)
- `dataset_end` (TEXT, NOT NULL)

Implication:
- Vendor availability is always recorded (even if unmapped vendor identity columns are null).
- The schema enforces presence of dataset availability boundaries as part of an attempt row.

#### Lifecycle surface (from instrument_definitions; nullable)

- `activation_floor` (TEXT, nullable)
- `expiration_ceiling` (TEXT, nullable)

Implication:
- Lifecycle constraints may be unknown/absent; schema can represent incomplete lifecycle knowledge.

#### Expected window (intersection; half-open [start,end))

- `expected_start` (TEXT, NOT NULL)
- `expected_end` (TEXT, NOT NULL)
- `is_empty` (INTEGER, NOT NULL, default 0)

Implications:
- Expected window is always recorded as boundaries, even when empty; emptiness is additionally tagged.
- The schema can represent **empty-expected** explicitly (`is_empty=1`), independently of `status`.

### B.1.6 Diagnostics on expected vs interest (explicit causal flags)

- `is_vendor_limited` (INTEGER, NOT NULL, default 0)
  - Indicates expected differs from interest due to dataset availability limits.

- `is_lifecycle_limited` (INTEGER, NOT NULL, default 0)
  - Indicates expected differs from interest due to lifecycle constraints.

Implications:
- The schema encodes *two orthogonal “why” explanations* for expected truncation.
- Both can be true simultaneously (no constraints enforce exclusivity).

### B.1.7 Vendor finality (orthogonal boolean)

- `vendor_final` (INTEGER, NOT NULL, default 0)
  - True if, given surfaces, no future vendor data can extend `expected_end`.

Implications:
- Vendor finality is representable independently from coverage and status.
- The schema supports the planning principle that vendor_final is **decisive for retry potential**, without tying it to “complete”.

### B.1.8 Orchestrator decision/result label (string + optional detail)

- `status` (TEXT, NOT NULL)
  - A string label representing the outcome/decision of the run for the contract.

- `status_detail` (TEXT, nullable)
  - Free text for diagnostics.

Comment suggests recommended stable strings:
- `"unmapped"`
- `"skipped_empty_expected_window"`
- `"complete"`
- `"dry_run"`
- `"skipped_cost_cap"`
- `"ingested"`
- `"incomplete"`

Implications:
- Status is an **attempt-level label**, not necessarily a coverage-level truth.
- The schema permits additional status values beyond the recommendation (no CHECK constraint).
- The schema supports **diagnostic expansion** without breaking the stable `status` label (via `status_detail`).

### B.1.9 Cost accounting (optional; multiple notions)

- `cost_cap_usd` (REAL, nullable)
- `cost_estimated_usd` (REAL, nullable)
- `cost_charged_usd` (REAL, nullable)
- `cost_used_usd` (REAL, nullable)

Implications:
- The schema can represent the difference between “cap in force”, “estimate used”, “actual billed”, and “budget decrement”.
- None are mandatory; cost may be unknown or unrecorded for certain statuses.

### B.1.10 Coverage snapshots (pre and post; optional)

Before attempt:
- `stored_min_before` (TEXT, nullable)
- `stored_max_before` (TEXT, nullable)
- `stored_rows_before` (INTEGER, nullable)
- `bars_path_before` (TEXT, nullable)

After attempt:
- `stored_min_after` (TEXT, nullable)
- `stored_max_after` (TEXT, nullable)
- `stored_rows_after` (INTEGER, nullable)
- `bars_path_after` (TEXT, nullable)

Implications:
- The schema can represent:
  - “no stored data” (null min/max/rows)
  - partial coverage windows (min/max)
  - row-count evidence
  - location/path of stored artefact(s)
- Because both before and after are stored, the schema supports **delta reasoning** per attempt.

### B.1.11 Error capture (optional; per attempt)

- `error_type` (TEXT, nullable)
- `error_message` (TEXT, nullable)

Implication:
- Errors are representable without failing the pipeline (ledger captures rather than enforces).
- Error presence is not constrained by `status`; schema allows combinations that may be invalid semantically unless code enforces invariants.

## B.2 Index-level semantics (what queries are “first-class”)

- `idx_ohlcv1d_attempts_contract_ordering` on `(product_id, contract_id, run_ts_utc, created_at)`
  - Suggests “latest attempts per contract” queries are central.
  - Note: ordering keys include both run_ts_utc and created_at; “latest” may depend on both.

- `idx_ohlcv1d_attempts_vendor_ordering` on `(dataset, publisher_id, instrument_id, created_at)`
  - Supports vendor-diagnosis views by instrument identity.

- `idx_ohlcv1d_attempts_run` on `(run_ts_utc, created_at)`
  - Supports run-level reporting (all attempts in a run).

- `idx_ohlcv1d_attempts_status` on `(status, created_at)`
  - Supports filtering/grouping by status for ops diagnostics.

## B.3 Latent semantic dimensions implied by the schema (non-normative observation)

The table can represent, as independent axes:

1. **Contract identity** (product_id, contract_id, contract_key)
2. **Vendor identity resolution** (nullable vendor columns)
3. **Four window surfaces** (interest, dataset availability, lifecycle, expected)
4. **Expected emptiness** (`is_empty`)
5. **Expected truncation causes** (`is_vendor_limited`, `is_lifecycle_limited`)
6. **Vendor finality** (`vendor_final`)
7. **Attempt outcome label** (`status`, `status_detail`)
8. **Cost context** (cap/estimate/charged/used)
9. **Coverage before/after** (min/max/rows/path)
10. **Operational failure evidence** (error_type/message)

Important: the schema does not enforce mutual exclusivity or invariants between these axes.

## B.4 Immediate questions to carry into Extraction C (not answered here)

- What is the authoritative definition of “latest attempt”:
  - max(run_ts_utc)? max(created_at)? or both?
- Are there code-level invariants tying `status` to:
  - `is_empty`
  - vendor identity nullability
  - error fields non-null
  - coverage snapshot presence
- Does code ensure “exactly one attempt row per contract considered per run”, or can duplicates occur?

(These will be resolved by extracting predicates from the attempts store and orchestrator code.)


## B.2 Extracted from Attempts Store — `datasets/ohlcv_1d/attempts_store.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/attempts_store.py`  
**Store:** `OHLCV1DAttemptsStore`  
**Table:** `ohlcv_1d_attempts`  
**Declared usage:** orchestrator calls `record_attempt(...)` exactly once per contract considered, including skips.

### B.2.1 Persisted models defined in the store

#### `CoverageSnapshot` (lightweight coverage model)
- `min_ts: pd.Timestamp | None`
- `max_ts: pd.Timestamp | None`
- `row_count: int`
- `bars_path: str | None = None`

Implications:
- Coverage is represented as a min/max interval plus row count.
- Null min/max represent “no stored data observed”.
- Coverage model uses `pandas.Timestamp` at the data model boundary (control-plane uses string serialization when writing).

#### `OHLCV1DAttemptRow` (read model)
- Mirrors a subset of the table columns as typed fields.
- Uses:
  - `run_ts_utc: str` (control-plane timestamp label)
  - `created_at: str` (system-plane timestamp label)
  - many interval fields stored as `str` (ISO8601Z)
  - vendor identity fields nullable
  - `vendor_final: bool`
  - `status: str`
  - `error_type/message: str | None`
  - coverage before/after fields
  - optional cost fields: `cost_cap_usd`, `cost_estimated_usd`

Important representational fact:
- This read model is **not a full projection** of the schema: it omits some schema fields (see mismatches below).

### B.2.2 Write path semantics (`record_attempt`)

#### Attempt identity
- `attempt_uid` is generated as `uuid.uuid4()` per call.
- Implies:
  - attempt rows are not idempotent by default.
  - “exactly one row per contract considered” is a **code convention**, not an enforced uniqueness constraint.

#### Migration behaviour
- `self._backend.ensure_migrated()` is called on each record attempt.
- Implies:
  - store assumes migrations are cheap/safe to check at write time.
  - failure to migrate prevents recording.

#### Serialization / formatting of timestamps
- All window timestamps are written via `_fmt_ts` / `_fmt_ts_or_none`.
- `_fmt_ts` canonicalises to:
  - UTC
  - ISO8601Z
  - **second resolution** (`%Y-%m-%dT%H:%M:%SZ`)
  - sub-second precision is deliberately stripped.

Implications:
- The store enforces a **lossy** projection from any higher-precision timestamp inputs.
- Ordering stability is intended to be lexicographic.
- This is explicitly stated as a convention alignment choice.

#### Expected window input
- `ew: ExpectedWindow` is required input (“always present in your new design” comment).
- Store writes:
  - interest: `interest_start/end`
  - dataset range: `dataset_start/end`
  - lifecycle: `activation_floor/expiration_ceiling` (nullable)
  - expected intersection: `expected_start/end`
  - derived flags: `is_empty`, `is_vendor_limited`, `is_lifecycle_limited`, `vendor_final`

Implication:
- The attempts ledger row is a **snapshot of the expected-window derivation** at the time of the attempt; it is not recomputed on read.

#### Status and outcomes
- `status` is required input.
- `status_detail` is optional.

Implication:
- Status is an externally-determined label (orchestrator-level) recorded verbatim.
- The store does not validate status strings against an enum.

#### Cost accounting write support (superset)
The store accepts and writes:
- `cost_cap_usd`
- `cost_estimated_usd`
- `cost_used_usd`
- `cost_charged_usd`

Implication:
- The write API supports richer cost fields than the read model currently projects (see mismatches).

#### Coverage snapshots write behaviour
Coverage before/after are optional.
If present:
- `min_ts/max_ts` are formatted via `_fmt_ts_or_none`
- `row_count` is stored as int
- `bars_path` is stored as text

Implication:
- The ledger can represent:
  - attempts with no pre-scan
  - attempts with pre-scan but no post-scan
  - attempts with both pre and post scans

#### Error capture write behaviour
- `error_type` and `error_message` are optional and written as provided.
- Store does not enforce coupling between `status` and error fields.

### B.2.3 Read path semantics (projection + “latest” conventions)

#### `_row_to_attempt`
- Converts SQLite row dict to `OHLCV1DAttemptRow`.
- Normalises:
  - integer 0/1 columns to bool via `_bool01`
  - int columns via `_int_or_none`
  - vendor identity to typed optional values
  - timestamps remain strings (no parsing)

Implication:
- Read model is intentionally *control-plane string-first*; timestamp parsing is not performed in this store.

#### “Latest attempt” for a contract
`get_latest_attempt_for_contract(product_id, contract_id)`:
- ORDER BY `run_ts_utc DESC, created_at DESC, attempt_uid DESC`
- LIMIT 1

Implications:
- “Latest” is defined primarily by **run_ts_utc**, then system-time, then uid tie-break.
- Because `run_ts_utc` is text, correctness depends on canonical formatting stability.

#### “Latest attempts per contract_key for a product”
`list_latest_attempts_for_product(product_id)` uses a two-stage CTE:
1. `latest_run`: per `contract_key`, `MAX(run_ts_utc)`
2. `latest_created`: within that run_ts_utc, per `contract_key`, `MAX(created_at)`
3. Joins back to table on `(contract_key, run_ts_utc, created_at)`

Implications:
- The “latest per contract” logic is:
  - latest run_ts_utc per contract_key
  - and within that run, latest created_at
- If multiple rows share identical `(contract_key, run_ts_utc, created_at)`, the join can return multiple rows; schema does not prevent this.
- The store assumes created_at is sufficiently granular and unique in practice.

#### System-wide latest per contract_key
`list_latest_attempts_all_contracts()` uses the same CTE pattern without product filter.

#### Products with any attempts
`list_products_with_attempts()` returns `SELECT DISTINCT product_id`.

### B.2.4 Explicit store-level invariants (enforced vs assumed)

Enforced by code:
- Every recorded attempt has:
  - `attempt_uid`
  - `run_ts_utc`, `mode`, `dry_run`, `reset_local`
  - `product_id`, `contract_id`, `contract_key`
  - a fully materialised ExpectedWindow (`ew`)
  - `status`

Assumed (not enforced in schema or store):
- Exactly one attempt row per contract considered per run.
- Status/value compatibility rules (e.g. `status="unmapped"` implies vendor identity nulls).
- Mutual exclusivity of boolean flags and status categories.
- Uniqueness of `(contract_key, run_ts_utc, created_at)` in “latest per contract_key” queries.

### B.2.5 Schema/store/read-model mismatches (facts only)

These are representational mismatches between:
- the SQL schema,
- the store write API,
- the store read projection (`OHLCV1DAttemptRow`),
- and SELECT projections.

1) `feed` column exists in schema and is written by `record_attempt`, but:
   - `OHLCV1DAttemptRow` does not include `feed`.
   - All SELECT projections in this store omit `feed`.
   Implication: `feed` is persisted but not observable through this store's read API.

2) Schema includes `is_vendor_limited` and `is_lifecycle_limited` and the store writes them, but:
   - `OHLCV1DAttemptRow` does not include these fields.
   - All SELECT projections omit them.
   Implication: these diagnostics are persisted but not available in current read methods.

3) Schema includes `cost_used_usd` and `cost_charged_usd` and the store writes them, but:
   - `OHLCV1DAttemptRow` includes only `cost_cap_usd` and `cost_estimated_usd`.
   - SELECT projections include only `cost_cap_usd` and `cost_estimated_usd`.
   Implication: `cost_used_usd` and `cost_charged_usd` are persisted but not surfaced via this store’s read model.

### B.2.6 Temporal formatting note (important for later semantic consolidation)

- `_fmt_ts` currently depends on `pandas.Timestamp` and yields second-resolution UTC ISO8601Z strings.
- This is a control-plane serialization choice embedded in the store.

Carry-forward question for Session 14a consolidation:
- Planning doc states “canonical ISO8601Z with microseconds”; current store enforces second resolution and uses pandas in formatting helpers.



## B.3 Extracted from Local Dataset Store — `datasets/ohlcv_1d/store.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/store.py`  
**Store:** `OHLCV1DStore`  
**Persistence substrate:** local Parquet (delegated to `stores/parquet/daily_bars.py`)  
**Coverage mechanism:** reads Parquet file and inspects `ts_event` column.

### B.3.1 Storage identity model

The local storage identity for daily bars is:
- `(dataset: str, publisher_id: int, instrument_id: int)`

This identity maps to a filesystem path via:
- `MarketdataLayout.bars_path(dataset, publisher_id, instrument_id)`

Implication:
- Local OHLCV-1D persistence is vendor-identity scoped (not contract scoped).
- Multiple MXM contracts could theoretically map to the same `(dataset, publisher_id, instrument_id)` identity if upstream mapping were wrong; the store does not prevent this.

### B.3.2 Persistence API semantics

- `write(dataset, publisher_id, instrument_id, df_new)`
  - Delegates to `write_daily_bars(...)` (not shown here).
  - Implies “append/merge” semantics are owned by the Parquet writer module.

- `read(dataset, publisher_id, instrument_id, start=None, end=None)`
  - Delegates to `read_daily_bars(...)` (not shown here).
  - Optional windowed reads are supported at the API boundary.

- `delete(dataset, publisher_id, instrument_id)`
  - Identity-scoped destructive reset.
  - Deletes the Parquet file if it exists; returns boolean “was deleted”.

Implication:
- Deletion is coarse (whole-identity file). No partial deletion.

### B.3.3 Coverage / introspection semantics (`scan_coverage`)

Coverage is computed by inspecting the on-disk Parquet file:

1) If file does not exist:
   - `exists=False`, `row_count=0`, `min_ts=None`, `max_ts=None`

2) If file exists but is empty:
   - `exists=True`, `row_count=0`, `min_ts=None`, `max_ts=None`

3) If file exists and non-empty:
   - reads entire Parquet into a DataFrame
   - expects `ts_event` column to be present
   - computes:
     - `ts_min = Timestamp(min(df["ts_event"]))`
     - `ts_max = Timestamp(max(df["ts_event"]))`
   - normalises both to UTC tz-aware timestamps (localize/convert)
   - returns `row_count=len(df)` and `(min_ts, max_ts)`.

Declared docstring:
- “min_ts/max_ts are dates (UTC) derived from ts_event.”

Observed behaviour:
- `min_ts`/`max_ts` are computed as timestamps from `ts_event` min/max; there is **no explicit day-flooring in this function**.

Implications / representable semantics:
- “stored window” (for Level-0 completeness checks) is approximated as:
  - `[stored_min, stored_max]` via extrema of `ts_event`, plus `row_count`.
- Coverage computation cost scales with reading the full Parquet file.
- Coverage can represent “some data exists” without implying contiguity or absence of gaps.

### B.3.4 Dependency note: pandas in coverage plane

- Coverage window representation and computation uses `pandas.Timestamp`.
- This is part of the current control-plane implementation for coverage introspection.

Carry-forward for later consolidation:
- Day-label semantics are stated in comments; enforcement of “day alignment” is not visible in this store.


## B.4 Extracted from Expected Window Derivation — `datasets/ohlcv_1d/expected.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/expected.py`  
**Public function:** `derive_expected_window(...) -> ExpectedWindow`  
**Core role:** defines “expected window” as intersection of interest × dataset availability × lifecycle clamps, in UTC half-open form.

### B.4.1 Value object: `ExpectedWindow`

`ExpectedWindow` stores:

Identity:
- `product_id`, `contract_id`

Input surfaces (all pd.Timestamp, UTC tz-aware):
- `interest_start`, `interest_end`
- `dataset_start`, `dataset_end`
- `activation_floor` (nullable)
- `expiration_ceiling` (nullable)

Derived interval:
- `expected_start`, `expected_end` (half-open)

Derived flags:
- `is_empty`
- `is_vendor_limited`
- `is_lifecycle_limited`
- `vendor_final`

Important: ExpectedWindow is constructed as timestamps; it is later serialized to strings when written into the attempts ledger.

### B.4.2 Interest window semantics

`derive_interest_window(first_day_of_interest, last_trading_day)` returns:

- `start = first_day_of_interest @ 00:00Z`
- `end = (last_trading_day + 1 day) @ 00:00Z`

This explicitly defines a **half-open** interval:
- `[first_day_of_interest@00:00Z, (last_trading_day+1)@00:00Z)`

### B.4.3 Dataset availability surface semantics

In `derive_expected_window`:
- `ds_start = _ts_utc(pd.Timestamp(dataset_start))`
- `ds_end = _ts_utc(pd.Timestamp(dataset_end))`

Notes:
- `dataset_end` is treated as end-exclusive (as documented in inputs).
- Both are coerced to UTC tz-aware timestamps.

### B.4.4 Lifecycle bound semantics (day-aligned clamps)

Lifecycle inputs:
- activation and expiration may be:
  - ints (nanoseconds since epoch)
  - ISO strings
  - datetime / pandas.Timestamp
  - None / NaN

Extraction pipeline:
- `_extract_ns(...)` coerces to `ns since epoch int | None`
- `_dt_from_ns_utc(ns)` converts to UTC datetime (nanos truncated to micros)

Derived lifecycle constraints:
- `activation_floor = floor_to_utc_day(activation)`
- `expiration_ceiling = ceil_to_next_utc_day(expiration)`

Where:
- floor = 00:00Z of activation day
- ceil = next 00:00Z boundary unless expiration already exactly 00:00Z (then unchanged)

Both are returned as pd.Timestamp UTC tz-aware, nullable.

### B.4.5 Expected window derivation (intersection + clamps)

Steps:

1) Base intersection of interest and dataset:
- `expected_start = max(interest_start, ds_start)`
- `expected_end = min(interest_end, ds_end)`

2) `is_vendor_limited` is set as:
- `(expected_start != interest_start) OR (expected_end != interest_end)`

Observation:
- This flags “expected differs from interest” but does not distinguish whether the difference comes from dataset_start shifting start vs dataset_end truncating end.

3) Apply lifecycle clamps:
- if `activation_floor > expected_start`: set expected_start = activation_floor, mark lifecycle limited
- if `expiration_ceiling < expected_end`: set expected_end = expiration_ceiling, mark lifecycle limited

4) Emptiness:
- `is_empty = expected_end <= expected_start`

5) Vendor finality:
- `vendor_final = (expiration_ceiling is not None) AND (ds_end >= expiration_ceiling)`

Important nuance:
- vendor_final is defined **only** relative to expiration_ceiling (requires known expiration).
- vendor_final is orthogonal to emptiness; it can be true even if expected is empty, depending on surfaces.

### B.4.6 Timestamp toolchain note

This module uses:
- pandas.Timestamp as primary timestamp type
- python datetime utilities for day boundary operations
- nanosecond extraction utilities, with micros truncation for datetime conversion

Carry-forward mismatch for consolidation:
- planning doc and store formatting conventions may differ on sub-second resolution and “no pandas in control plane”.


## B.5 Extracted from Derived State & Decision Logic — `datasets/ohlcv_1d/state.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/state.py`  
**Public functions:** `derive_state(...)`, `decide_action(...)`  
**Role:** define a derived state enum and map it to an action decision.

### B.5.1 Derived state vocabulary (implemented)

Enum `DerivedState` values:
- `done`
- `blocked_unmapped`
- `blocked_empty_expected`
- `needs_ingest`
- `retryable_error`
- `final_error`
- `skipped_budget`
- `unknown`

Decision action space:
- `noop`
- `attempt_ingest`
- `stop_run`

A `Decision` includes:
- `action`
- `reason` (string)

### B.5.2 Retry policy (MVP)

`RetryPolicy` parameters:
- `max_consecutive_errors: int = 3`
- `stop_run_on_systemic_error: bool = True`

Notable implementation note:
- `_consecutive_error_count` currently returns `1` if latest attempt status is `"error"` else `0`.
- It does not inspect multiple attempts; this is stated explicitly as an MVP limitation.

### B.5.3 Systemic error classifier

`_is_systemic_error(error_type, error_message)` uses conservative string heuristics, including:
- auth/permission/unauthorized
- migration/no such table/schema error
- sqlite OperationalError excluding “locked” as transient

Implication:
- systemic error classification is not a structured taxonomy; it is heuristic and string-based.

### B.5.4 derive_state predicate ordering (as implemented)

Inputs:
- `latest_attempt: OHLCV1DAttemptRow | None`
- `ew: ExpectedWindow`
- `coverage_now: CoverageSnapshot | None`
- `is_mapped: bool`
- `reset_local: bool`

Ordering rules (implemented):

1) Blockers first:
- if not mapped -> `blocked_unmapped`
- if ew.is_empty -> `blocked_empty_expected`

2) Operator override:
- if reset_local -> `needs_ingest` (except empty expected already handled)

3) Determine presence of any local data:
- `_has_any_local_data` is true if:
  - row_count > 0 OR min_ts/max_ts non-null

4) If local data exists:
- compute `is_complete_now = is_complete_level0(...)` using:
  - stored_min/stored_max/row_count
  - ew.expected_start/ew.expected_end
- if complete -> `done`
- else if ew.vendor_final -> `done` (vendor-final partial accepted *only if some local data exists*)
- else -> `needs_ingest`

5) If no local data exists:
- vendor_final does NOT imply done
- consult latest_attempt only for:
  - skipped_cost_cap -> `skipped_budget`
  - error -> `retryable_error`
  - unmapped -> blocked_unmapped
  - skipped_empty_expected_window -> blocked_empty_expected
- otherwise -> `needs_ingest`

Implication:
- Coverage dominates DONE vs NEEDS_INGEST.
- Vendor_final is used as a “DONE despite incomplete” permit only when there is evidence of some local data.

### B.5.5 decide_action mapping (as implemented)

1) Immediate noops:
- done, blocked_unmapped, blocked_empty_expected, skipped_budget, final_error -> noop(reason=state)

2) unknown -> stop_run

3) needs_ingest:
- if budgets.remaining_usd <= 0 -> noop("budget_exhausted")
- else attempt_ingest("needs_ingest")

4) retryable_error:
- if systemic and policy says stop -> stop_run("systemic_error")
- if retry limit reached -> noop("retry_limit_reached")
- if budget exhausted -> noop("budget_exhausted_after_error")
- else attempt_ingest("retryable_error")

Defensive default:
- stop_run("unhandled_state")

### B.5.6 Planning vs implementation note (fact)
- `final_error` exists in enum but is not produced by `derive_state` in the pasted implementation.
- `_consecutive_error_count` does not implement “max consecutive errors” beyond 0/1 given only the latest attempt.

## B.6 Extracted from Vendor Normalization — `vendors/databento/normalize/ohlcv_1d.py`
**Source:** `mxm/v1/marketdata/vendors/databento/normalize/ohlcv_1d.py` (as pasted)  
**Function:** `normalize_ohlcv_1d(df_raw, dataset, raw_symbol=None) -> pd.DataFrame`  
**Role:** convert a Databento OHLCV-1D response dataframe into MXM canonical OHLCV-1D schema.

### B.6.1 Declared Databento semantics for daily bars (as documented)
The normalizer docstring states Databento typically returns:
- index: `ts_event` (UTC midnight)
- columns: open/high/low/close/volume plus identity (publisher_id, instrument_id, symbol)

It then states MXM standardises to:
- explicit `ts_event` column (not index)
- canonical names/ordering
- enforced UTC tz-aware timestamps

### B.6.2 Normalization steps (as implemented)

1) Copy the dataframe.
2) If Databento returned `ts_event` as the index (index.name == "ts_event"):
   - reset index, making `ts_event` an explicit column.
3) If `symbol` column exists and `raw_symbol` does not:
   - rename `symbol -> raw_symbol`
4) If `raw_symbol` parameter is provided:
   - overwrite/set `df["raw_symbol"] = raw_symbol` (canonical override)
5) Enforce a required column set:
   - keep_cols = [`ts_event`, `open`, `high`, `low`, `close`, `volume`, `publisher_id`, `instrument_id`, `raw_symbol`]
   - raise ValueError if any missing.
6) Subset to keep_cols in that order.
7) Delegate schema enforcement to:
   - `coerce_ohlcv_1d(df, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True)`

Implications:
- `ts_event` is canonical key column and is required.
- This module does not itself floor/ceil timestamps; it relies on `coerce_ohlcv_1d` to “enforce UTC tz-aware timestamps”.
- The meaning “UTC midnight” for `ts_event` is stated as a Databento typical property, not enforced explicitly here.


## B.7 Extracted from Parquet Persistence — `stores/parquet/daily_bars.py`
**Source:** `mxm/v1/marketdata/stores/parquet/daily_bars.py` (as pasted)  
**Functions:** `write_daily_bars`, `read_daily_bars`  
**Role:** idempotent merge/write and windowed read for OHLCV-1D bars under a `(dataset, publisher_id, instrument_id)` identity.

### B.7.1 Write semantics (`write_daily_bars`)

Declared rules (docstring):
- primary key: `ts_event`
- deduplicate on `ts_event` (keep last)
- sort by `ts_event` ascending
- atomic write (tmp then `os.replace`)

Implemented steps:

1) Coerce incoming `df_new`:
- `df_new = coerce_ohlcv_1d(df_new, dataset, schema="ohlcv-1d", ensure_column_order=True)`

2) Compute identity paths:
- `bars_path = layout.bars_path(...)`
- `tmp_path = layout.tmp_bars_path(...)`
- ensure parent directory exists.

3) If file exists:
- read `df_old = pd.read_parquet(bars_path)`
- re-coerce `df_old` via `coerce_ohlcv_1d(...)` (early drift/corruption detection)
- concatenate `df_old + df_new` (ignore_index=True)
Else:
- `df_all = df_new.copy()`

4) Deduplicate:
- `df_all = df_all.drop_duplicates(subset=["ts_event"], keep="last")`

“keep last” implies:
- if the same `ts_event` appears multiple times across writes, the newest write wins.

5) Sort and stabilise:
- `df_all = df_all.sort_values("ts_event").reset_index(drop=True)`

6) Validate:
- `validate_ohlcv_1d(df_all)` (strict final check)

7) Atomic write:
- `df_all.to_parquet(tmp_path, index=False)`
- `os.replace(tmp_path, bars_path)`

Implications:
- Local storage is *idempotent with respect to ts_event*.
- `row_count` for a persisted file should equal the number of unique `ts_event` values after merge/dedup.
- The file is a stable canonical representation (sorted, column order enforced).

### B.7.2 Read semantics (`read_daily_bars`)

1) If file missing: raise FileNotFoundError.
2) Read parquet, then coerce schema via `coerce_ohlcv_1d(...)`.
3) Optional filtering:
- `start` filters: `ts_event >= start` (start inclusive)
- `end` filters: `ts_event < end` (end exclusive)
- both coerced to UTC tz-aware timestamps (localize or convert)
4) Returns reset-index dataframe.

Implications:
- Read window semantics match the half-open convention `[start, end)`.
- Filtering uses the stored `ts_event` column as the time axis.

### B.7.3 Operational linkage to coverage semantics

Because persistence deduplicates on `ts_event` and sorts, and coverage scanning uses:
- `min/max(df["ts_event"])`
- `len(df)` as row_count,

the store’s coverage extrema and row_count are consistent with:
- the number of unique day labels (assuming ts_event encodes day labels),
- post-coercion schema constraints enforced on every write and read.


# C. Extracted from Orchestrator Predicates (OHLCV-1D)
**Source:** orchestrator `ingest_ohlcv_1d_for_product(...)` (as pasted)  
**Goal of this extraction section:** record exactly how the orchestrator assigns attempt `status` and how it gates vendor calls.

## C.1 Status assignment catalogue (as implemented)

The orchestrator uses `status` strings that include (comment in ContractRun):
- complete | ingested | unmapped | skipped_cost_cap | dry_run | incomplete | error

Observed assignments (by control path):

### C.1.1 Mapping resolution failure
When `resolve_databento_instrument(...)` raises:
- `ew` is still computed using dataset range, with lifecycle=None
- `status = "unmapped"`
- `status_detail = f"mapping_failed:{type(e).__name__}"`
- loop continues
- attempt row is still recorded in `finally`

### C.1.2 Empty expected window
If `ew.is_empty`:
- `status = "skipped_empty_expected_window"`
- `status_detail = "expected_window_empty"`
- loop continues
- attempt row recorded

### C.1.3 Coverage scan occurs before state derivation (when mapped & non-empty expected)
Coverage is scanned as `cov_before`, except:
- if reset_local and dry_run: cov_before is simulated empty

`is_complete_now` is computed via `is_complete_level0(cov0, ew.expected_start/end)`

Derived state is computed via `derive_state(...)` and decision via `decide_action(...)`.

### C.1.4 Dry-run override
If `dry_run` is true (after decision computed):
- `status = "dry_run"`
- `status_detail = f"dry_run_decision={decision.action}"`
- no vendor call
- attempt recorded

### C.1.5 Decision: noop
If `decision.action == "noop"`:

If derived_state == done:
- if `is_complete_now`:
  - `report.complete_before += 1`
  - `status = "complete"`
  - `status_detail = "already_complete"`
- else (vendor-final partial done):
  - `status = "complete"`
  - `status_detail = "vendor_final_partial_done"`

If derived_state == blocked_unmapped:
- `status = "unmapped"`
- `status_detail = "blocked_unmapped"`

If derived_state == blocked_empty_expected:
- `status = "skipped_empty_expected_window"`
- `status_detail = "expected_window_empty"`

If derived_state == skipped_budget:
- `status = "skipped_cost_cap"`
- `status_detail = "skipped_budget"`

Else (fallback for noop-returning states):
- `status = "dry_run" if dry_run else "complete"`
- `status_detail = decision.reason`

### C.1.6 Decision: stop_run
If `decision.action == "stop_run"`:
- `status = "error"`
- `status_detail = f"stop_run:{decision.reason}"`
- `report.stopped_reason = "stop_run"`
- `should_break_after = True`
- attempt recorded, then break

### C.1.7 Attempt_ingest path and cost gating
Before vendor call:
- If remaining <= 0:
  - `status = "skipped_cost_cap"`
  - `status_detail = "cost_cap_reached"`
  - `report.stopped_reason = "cost_cap"`
  - `should_break_after = True`

Estimate:
- `cost_estimated_usd = estimate_cost_ohlcv_1d(...)`

If estimate exceeds remaining:
- `status = "skipped_cost_cap"`
- `status_detail = "estimate_exceeds_remaining"`
- continue (does not break; later contracts may be cheaper)

Vendor call and persistence:
- `df_raw = pull_ohlcv_1d_by_instrument_id(...)`
- `df = normalize_ohlcv_1d(...)`
- `store.write(...)`

Cost bookkeeping:
- `cost_used_usd = cost_estimated_usd`
- `cost_charged_usd = cost_estimated_usd`
- remaining reduced

Coverage after:
- cov_after computed via store.scan_coverage
- complete_after computed via is_complete_level0(cov1, ew.expected_start/end)

If complete_after:
- `status = "ingested"`
- `status_detail = "ingested_complete"`
- `report.completed_this_run += 1`

Elif ew.vendor_final:
- `status = "ingested"`
- `status_detail = "vendor_final_partial_done"`
- `report.completed_this_run += 1`

Else:
- `status = "incomplete"`
- `status_detail = "incomplete_after_ingest"`

### C.1.8 Exception catch-all
On any exception in try:
- `status = "error"`
- `status_detail = "exception"`
- error_type = type(e).__name__
- error_message = str(e)[:500]
- attempt recorded in finally

## C.2 Ledger invariants enforced by orchestrator (as implemented)

- An attempt row is always recorded in `finally`, even on early `continue` paths.
- If `ew` is None at finally, it is derived with lifecycle=None.
- Vendor identity fields are written only if `ident` exists.
- Coverage snapshots are optional; `cov_before` exists only after mapping & non-empty expected paths (or simulated for reset_local + dry_run).
- `cost_used_usd` and `cost_charged_usd` are recorded only on vendor-call completion (MVP treats them equal to estimate).

## C.3 Report surface note (fact)
`ContractRun.target_start/target_end` are set to interest window strings (interest_start_s/interest_end_s),
while `vendor_start/vendor_end` are the expected window strings (exp_start_s/exp_end_s).


## C.4 Extracted from Window Semantics — `datasets/ohlcv_1d/api.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/api.py`  
**Functions:** `contract_window_utc_half_open`, `_coerce_date`  
**Role:** canonical conversion from date-based contract lifecycle to half-open UTC timestamp windows.

### C.4.1 Canonical OHLCV window type
`OHLCV1DWindow` is defined as:
- `start: pd.Timestamp`
- `end: pd.Timestamp`

With explicit semantics:
- “Canonical half-open window [start, end) for ohlcv-1d pulls.”

### C.4.2 Date coercion semantics (`_coerce_date`)
Accepted input shapes (as implemented):
- `datetime.date` (non-datetime subclass) -> returned unchanged
- `str` -> parsed with `date.fromisoformat` (expects `YYYY-MM-DD`)
- `datetime.datetime` -> coerced to `.date()`

Implication:
- The canonical date fields are intended to be day-granular and ISO-parsable.

### C.4.3 Half-open UTC conversion (`contract_window_utc_half_open`)
Inputs:
- `start_date: date`
- `end_date_inclusive: date` (inclusive last day on which a bar should exist)

Returns:
- `start = start_date @ 00:00Z`
- `end = (end_date_inclusive + 1 day) @ 00:00Z`

This establishes the core daily-bar semantics:
- a bar “belongs to” the UTC day label for the trading day
- the half-open end boundary is one day after the inclusive last day.

This matches the interest-window semantics in `expected.py` (`derive_interest_window`).


## C.5 Extracted from Completeness Predicate — `datasets/ohlcv_1d/api.py`
**Source:** `mxm/v1/marketdata/datasets/ohlcv_1d/api.py`  
**Function:** `is_complete_level0(...) -> bool`  
**Role:** authoritative MVP definition of “complete coverage” for OHLCV-1D, expressed in half-open window semantics.

### C.5.1 Declared Level-0 completeness definition (as implemented)

Given:
- local stored coverage extrema: `stored_min`, `stored_max`
- `row_count`
- expected interval boundaries: `target_start`, `target_end` (half-open)

The predicate returns True iff:
1) `row_count > 0`
2) `stored_min` and `stored_max` are not None
3) timestamps are compared in UTC tz-aware form
4) `stored_min <= target_start`
5) `stored_max >= (target_end - 1 day)`  (named `last_expected`)

Rationale (documented in code):
- For a half-open window ending at 00:00Z of the day after `last_trading_day`,
  the last expected bar is on `(target_end - 1 day)`.

### C.5.2 Notable properties and limitations implied by the predicate

- Completeness is decided using only:
  - extrema of ts_event (min/max)
  - row_count
- There is no check for:
  - contiguity (gaps)
  - duplicates
  - correct day-label stamping
  - density (expected number of bars)
- Therefore, “complete” is a Level-0 boundary coverage test, not a rigorous completeness proof.

This is consistent with an MVP semantics of “coverage window encloses the expected window” rather than “all expected bars exist”.



## D.1 Extracted from Inspection Layer — Contract Coverage (`inspect/contracts.py`)
**Sources:**  
- `mxm/v1/marketdata/inspect/contracts.py`  
- `mxm/v1/marketdata/inspect/models.py`  
**Role:** read-only operator-facing synthesis of “coverage surfaces”, “coverage windows”, and “latest attempt” into stable report models.

### D.1.1 Canonical report identity
Contract identity is surfaced as:
- `product_id`, `contract_id`, `contract_key`
- vendor identity: `dataset`, `publisher_id`, `instrument_id`, `raw_symbol`

Note: `dataset` is defaulted to `""` (empty string) if absent in the attempt row.

### D.1.2 Day-aligned parsing policy (strict)
The inspection layer enforces day-label correctness by requiring UTC-midnight timestamps for DayRange fields:

- `_parse_day_ts(v: str)` parses into a tz-aware UTC `pd.Timestamp`, then requires:
  - hour=0, minute=0, second=0, microsecond=0

It applies this strict policy to:
- `interest_start`, `interest_end`
- `dataset_start`, `dataset_end`
- `activation_floor`, `expiration_ceiling` (if both present)
- `expected_start`, `expected_end`

Implication:
- The persisted attempts ledger becomes the canonical source of day-aligned surfaces; any drift is surfaced as an exception during inspection.

### D.1.3 Coverage surfaces synthesis
The inspection constructs:

- `interest: DayRange([interest_start, interest_end))`
- `dataset: DayRange([dataset_start, dataset_end))`
- `lifecycle: DayRange([activation_floor, expiration_ceiling))` **only if** both endpoints exist and `a < e`.

Then:

- `available = dataset ∩ lifecycle` if lifecycle is known, else dataset.

This exactly matches the conceptual model:
- available = dataset ∩ lifecycle (or dataset if lifecycle unknown)

### D.1.4 Expected window is “trusted from ledger”
The inspection explicitly **trusts** the persisted attempt row for expected window:

- `expected = DayRange([expected_start, expected_end))`

However, the code contains an explicit warning comment and error wrapper:
- it anticipates that empty expected windows may be persisted with `start==end`,
- and suggests “Either allow empty DayRange (recommended) or change how expected windows are persisted.”

This is a semantics tension with the current `DayRange` invariant (see D.1.8).

### D.1.5 Stored snapshot selection policy (after-preferred)
Stored coverage is taken from:
- `stored_*_after` if present, else `stored_*_before`

Then:
- `row_count = int(stored_rows or 0)`
- `stored_observed = ObservedRange(min_ts=stored_min, max_ts=stored_max)` if min/max exist and row_count > 0
- `stored_window = stored_observed.to_day_window()` if observed exists

Meaning:
- stored_observed is descriptive min/max ts_event
- stored_window is day-aligned normalisation for comparing against expected DayRange

### D.1.6 ObservedRange → DayRange normalisation semantics
`ObservedRange.to_day_window()` defines:

- `start_day = floor_to_day(min_ts)`
- `end_day_excl = floor_to_day(max_ts) + 1 day`
- returns `DayRange([start_day, end_day_excl))`

This allows stored_observed timestamps to be non-midnight (in principle), while stored_window is always midnight-aligned.

### D.1.7 Window completeness used by inspection
Inspection uses `CoverageWindows.complete` as the canonical “is complete” criterion:

- If expected is empty: returns True (vacuously complete)
- Else if no stored_window: returns False
- Else: `stored_window.contains(expected)`

This is a *coverage containment* criterion (not a density/gap check).

### D.1.8 DayRange invariants (as implemented) vs stated semantics
`DayRange` docstring states:
- invariant: `start < end`

But implementation checks:
- `if s > e: raise` (allows equality)
- and enforces UTC-midnight alignment

Therefore:
- empty ranges with `start == end` are permitted by the class, **despite** docstring claiming `start < end`.

This matters because several higher-level semantics rely on empty expected windows being representable.

### D.1.9 Attempt status vocabulary (inspection model)
`AttemptStatus` Enum includes:
- unmapped
- skipped_empty_expected_window
- complete
- dry_run
- skipped_cost_cap
- ingested
- incomplete
- error

This aligns with the statuses emitted by the orchestrator and recorded in the attempts ledger.

### D.1.10 “Vendor final” appears in two distinct forms
Inspection surfaces two notions:

1) `AttemptSummary.vendor_final` (ledger field from orchestrator/expected.py)
2) `CoverageWindows.vendor_final` (derived window relation):
   - True iff `expected == available`
   - None if available unknown

These are not the same definition.


## D.2 Extracted from Inspection Layer — Product Rollup (`inspect/product.py`)
**Source:** `mxm/v1/marketdata/inspect/product.py`  
**Role:** product-level status rollup based on latest attempt per contract_key plus window completeness.

### D.2.1 Product status vocabulary
`ProductStatus`:
- never_run
- done
- partial
- blocked
- error

### D.2.2 Input set: latest attempt per contract_key
The report is computed from:
- `list_contract_coverages_for_product(...)`
which itself uses:
- latest attempt per `contract_key` (not per contract_id).

If no attempts exist: status is `never_run`.

### D.2.3 Count semantics and “incomplete” bucket
For each contract coverage:

- `unmapped` attempt status:
  - increments `contracts_unmapped`
  - also increments `contracts_incomplete`

- `skipped_cost_cap` status:
  - increments `contracts_blocked_cost`
  - also increments `contracts_incomplete`

- `error` status:
  - increments `contracts_error`
  - also increments `contracts_incomplete`

For all other statuses:
- completeness is computed from `c.windows.complete`:
  - if True -> `contracts_complete += 1`
  - else -> `contracts_incomplete += 1`

Additional consistency check:
- if attempt status is "complete" but windows.complete is False,
  it increments `contracts_error` and flags contract as error-like.

### D.2.4 Product roll-up rules (implemented)
- done:
  - all contracts complete AND no unmapped/errors/blocked_cost
- otherwise:
  - error if any errors (including inconsistent “complete” vs windows)
  - blocked if any unmapped
  - blocked if any blocked_cost
  - partial otherwise


## D.3 Extracted from Inspection Layer — System Rollup (`inspect/system.py`)
**Source:** `mxm/v1/marketdata/inspect/system.py`  
**Role:** system-wide rollup across products, using latest attempt per contract_key.

### D.3.1 System product status vocabulary
`SystemProductStatus`:
- done
- partial
- blocked
- error

(no "never_run" here; absence of attempts means product is absent from report)

### D.3.2 Status roll-up rules (implemented)
Per product:
- counts are computed using the same bucketing as product.py:
  - unmapped / skipped_cost_cap / error count as incomplete
  - otherwise rely on `c.windows.complete`
  - "complete" attempt status that disagrees with windows.complete increments errors

Status precedence:
- done only if all complete AND no errors/unmapped/blocked_cost
- else error if any errors
- else blocked if any unmapped
- else blocked if any blocked_cost
- else partial


## D.4 Extracted from Ops Inspection Scripts — Printed Semantics (CLI surface)
**Sources:**  
- `scripts/marketdata/ops/inspect_contract.py` (contract coverage)  
- `scripts/marketdata/ops/inspect_product.py` (product coverage)  
- `scripts/marketdata/ops/inspect_system.py` (system coverage)  
**Role:** define the *operator-facing semantics* by choosing which fields to print, how to label them, and which derived concepts are juxtaposed.

### D.4.1 Common operational assumptions (all scripts)
All inspection scripts are read-only and share the same bootstrapping pattern:

- Root directory:
  - `--root` optional, defaults to `~/.mxm`
- Layout/DB:
  - `MarketdataLayout(root=...)`
  - `SQLiteBackend(layout=layout)`
  - `backend.ensure_migrated()` is always called before reads
- Attempts store:
  - `OHLCV1DAttemptsStore(backend=backend)`

This implies:
- inspection requires migrations to be compatible with the current codebase
- if the schema is missing/behind, inspection is expected to fail loudly rather than silently degrade

### D.4.2 Contract inspection script — what is considered authoritative
The contract inspector prints (in this order):

**Identity**
- `contract_key`
- vendor identity: dataset, publisher_id, instrument_id, raw_symbol

**Latest attempt summary**
- `last_attempt.ts`, `mode`, `status`, `status_detail`
- prints attempt flags:
  - `is_empty` (from AttemptSummary, derived from ledger field)
  - `vendor_final` (from AttemptSummary, derived from ledger field)
- prints error if present:
  - `error_type`, `error_message`

**Surfaces (DayRanges)**
- `interest` as [start .. end)
- `dataset_rng` as [start .. end)
- `lifecycle` as [start .. end) or (none)
- `available` as [start .. end) or (none / empty intersection)
- `expected` as [start .. end) with `days=...`

**Stored**
- `stored_rows`
- `stored_obs` (ObservedRange) or none
- `stored_win` (DayRange) or none

**Derived outputs**
- `complete: {w.complete}`
- `derived_vendor_final: {w.vendor_final}`

Semantics implied by the juxtaposition:
- the script treats `w.complete` as the completeness verdict
- it explicitly exposes *two vendor-finality notions*:
  1) attempt-level `vendor_final` (ledger field)
  2) window-derived `derived_vendor_final` (CoverageWindows.vendor_final)

### D.4.3 Product inspection script — what is printed and prioritised
The product inspector prints:

- `status_counts`: Counter of `last_attempt.status` across all contracts included in the report
- `product_id`
- `status` + `status_reason` (from ProductCoverageSummary)
- `last_run` timestamp and mode (max run_ts across contracts)

Then two count lines:
- `contracts: total, complete, incomplete`
- `breakdown: empty_expected, vendor_final, unmapped, cost_blocked, errors`

Optional:
- `--show-incomplete` prints `incomplete_contract_keys` (first N, default N=50 via `--limit`)

Semantics implied:
- “status_counts” is an operational diagnostic surface distinct from semantic roll-up
- the printed “vendor_final” is a product-level count field coming from the report summary
  (which itself uses AttemptSummary.vendor_final, not window-derived vendor_final)

### D.4.4 System inspection script — tabular roll-up semantics
The system inspector prints:

Header summary:
- `products: {len(products)}   contracts: {contracts_total}`

Then a fixed table header:
- `product_id | status | total | complete | incomplete | unmapped | cost_blocked | errors | last_run | mode`

Rows print from SystemProductRow:
- status is one of: done / partial / blocked / error
- last_run is ISO format if present

Semantics implied:
- there is no explicit “never_run” category at system level; products without any attempts do not appear
- “blocked” conflates unmapped and cost-blocked, but the counts are shown to disambiguate

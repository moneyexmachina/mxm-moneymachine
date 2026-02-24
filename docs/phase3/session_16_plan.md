# session_16_plan.md — MXM V1 Trading Calendars (Observed + Projected)

## Purpose

Establish a **deterministic, versioned, calendar-aware foundation** for MXM V1 that supports:

- daily trading-day arithmetic
- `bdays_to_ltd` and roll-window logic
- forward synthetic holdings generation
- automatic correction as authoritative calendar data expands

This session defines **how trading calendars are sourced, constructed, stored, versioned, projected, and reconciled**, without introducing intraday/session complexity.

## Core stance (locked)

### Authority model

- **Upstream datasource:** `exchange_calendars` Python package (version-pinned)
- **MXM authoritative surface:** derived, immutable calendar artifacts stored in `mxm_v1/refdata`
- **Truth validation:** reconciliation against observed OHLCV-1D bar availability

Calendars are **generated once**, stored as data, and **never recomputed at runtime**.

## Calendar layers

### 1) Observed calendar (authoritative)

Derived directly from `exchange_calendars` schedule.

- Covers the historical + near-future range provided by the package
- Contains full session information (open/close UTC)
- Treated as authoritative for all dates it covers

Artifacts:
- `schedule_observed.parquet`
- `trading_days_observed.parquet`

### 2) Projected calendar (explicit fallback)

Extends beyond the observed end date using a **simple, transparent rule**.

Projection rule v1:
- Trading day = weekday (Mon–Fri)
- Excluding a **minimal full-closure holiday set**:
  - New Year’s Day
  - Martin Luther King Jr. Day
  - Presidents’ Day
  - Good Friday (if applicable)
  - Memorial Day
  - Juneteenth
  - Independence Day
  - Labor Day
  - Thanksgiving Day
  - Christmas Day

Projection horizon:
- `projection_end = observed_end + 2 years`

Artifacts:
- `trading_days_projected.parquet`
- (optional) `schedule_projected.parquet` (open/close may be NaT in V1)

Projection is **explicitly weaker than observed** and is automatically superseded as observed coverage expands.

### 3) Effective calendar (consumer view)

- All observed trading days
- Plus projected trading days strictly after `observed_end`

All runtime calendar operations use the **effective trading-days array**.

## What is in scope (V1)

### Calendar operations
- `is_trading_day`
- `normalize(date, how=next|prev|raise)`
- `next_trading_day`, `prev_trading_day`
- `add_trading_days`
- `trading_days_between`
- `bdays_to_ltd` (scalar + vectorised)

### Data surfaces
- Daily trading-day index (`datetime64[D]`)
- Optional daily schedule (open/close UTC) for diagnostics

### Provenance & versioning
- Source package name + version
- Calendar name used (`exchange_calendars` identifier)
- Valid date range
- Generation timestamp
- SHA256 checksums of all artifacts
- Projection rule identifier

## What is explicitly out of scope (deferred)

- Intraday minute grids
- Early-close handling in logic (data stored only)
- Trading halts / ad-hoc disruptions
- Product-specific session modelling
- Calendar unions / intersections

## File layout (final)

### Refdata
```
mxm_v1/refdata/calendars/
  calendar_registry.yaml
  cmes/
    schedule_observed.parquet
    trading_days_observed.parquet
    trading_days_projected.parquet
```

### Holiday rules
```
mxm_v1/refdata/calendars/holiday_rules/
  us_federal_minimal_v1.yaml
```

### Code
```
mxm_v1/calendars/
  models.py        # TradingCalendar
  builders.py      # observed + projected calendar construction
  registry.py      # registry loading / validation
  loaders.py       # artifact loading
  inspect.py       # reconciliation vs OHLCV
```

## Work plan

### Step 0 — Confirm upstream coverage (done)
- Verify `exchange_calendars` coverage for CMES
- Confirm historical depth and forward limit

### Step 1 — Calendar registry schema
- Define registry entries with:
  - calendar_id
  - source package + version
  - observed_end
  - projection_end
  - checksums
  - projection_rule_id

### Step 2 — Observed calendar build
- Load `exchange_calendars` calendar
- Extract schedule and session index
- Persist observed artifacts
- Compute checksums

### Step 3 — Projected calendar build
- Generate weekday-only dates beyond `observed_end`
- Exclude holidays via `us_federal_minimal_v1`
- Persist projected artifacts
- Record projection metadata

### Step 4 — TradingCalendar implementation
- Load effective trading-days array
- Implement all calendar primitives
- Enforce strict vs normalised semantics

### Step 5 — Contract integration
- Ensure `FuturesContract` exposes:
  - `calendar_id`
  - `last_trading_day`
- Validate LTD availability for all V1 contracts

### Step 6 — `bdays_to_ltd`
- Implement scalar and vectorised versions
- Enforce trading-day strictness
- Support projected-region computation with tagging

### Step 7 — Reconciliation inspector
- Compare expected trading days vs observed OHLCV-1D availability
- Surface:
  - expected-but-missing days
  - unexpected observed days
- Report mismatch counts and examples

### Step 8 — Update workflow
- Refresh observed calendar periodically
- Detect observed_end extension or schedule changes
- Replace projected region as needed
- Trigger downstream synth recompute if effective calendar changes

## Acceptance criteria

1. Trading calendar loads deterministically from artifacts only.
2. `add_trading_days` and `bdays_to_ltd` work across observed and projected regions.
3. Projected calendar clearly distinguished from observed.
4. Calendar refresh produces a diffable, auditable change report.
5. Reconciliation vs OHLCV identifies any calendar/data boundary mismatches.
6. No runtime dependency on `exchange_calendars`.

## Design principle (explicit)

> Calendars are **data**, not code paths.  
> Projection is allowed, but only when explicit, versioned, and correctable.

This ensures MXM V1 remains operationally complete without pretending to have perfect future knowledge.

# session_16_plan.md — MXM V1 Trading Calendars (to LTD + bdays-to-LTD)

## Purpose

Establish a **fast, deterministic, calendar-aware** foundation for synthetic assets by implementing:

1. **Trading calendar support** per product / venue
2. **Last trading day (LTD)** availability as an authoritative surface on `FuturesContract`
3. Efficient **business-days-to-last-trading-day** computations:
   - scalar: `bdays_to_ltd(date, contract)`
   - vectorised: `bdays_to_ltd(dates[], contracts[])`

This session produces the primitives needed to build relative contracts (`M1`, `M2`, `Dec1`) and roll windows (`LTD-10bd → LTD-7bd`).

## Success conditions

### Functional
- For any product in the v1 universe, for any trading date `t`, we can compute:
  - whether `t` is a trading day
  - `add_trading_days(t, n)` (n ∈ ℤ)
  - `trading_days_between(t1, t2)` (signed int)
  - `bdays_to_ltd(t, contract_id)` for all contracts with known LTD

### Data surfaces
- `FuturesContract.last_trading_day` is present and reliable for v1 universe contracts:
  - sourced from exchange/vendor where possible,
  - otherwise derived using explicit product rules (but only if safe in v1).

### Performance
- `bdays_to_ltd` over a typical backfill window (e.g., 10k dates × 1–5 contracts/day) is not a bottleneck:
  - vectorised APIs exist,
  - caching exists at the right layer (calendar precomputation).

## Scope (strict V1)

### In
- Trading calendar representation for products (daily granularity).
- Calendar operations:
  - `is_trading_day`
  - `next_trading_day`, `prev_trading_day`
  - `add_trading_days`
  - `trading_days_between`
- LTD surface and `bdays_to_ltd`
- Storage/registry of calendars + explicit provenance metadata

### Out (defer)
- Intraday sessions, early closes, halts
- Holiday half-days affecting settlement timing
- Cross-calendar unions/intersections (save for synth session)
- Complex derivation of LTD from rule DSL for all venues (only as needed)

## Key design choices to settle in this session

### 1) Where calendars come from

We will support **two sources**, prioritised:

1. **Vendor calendar (preferred if available)**
   - If Databento provides a trading calendar / schedule endpoint that is accessible and reliable for our venues, use it.
   - Benefit: consistent with the data vendor’s notion of “trading day”.

2. **Exchange-published holiday calendars (fallback)**
   - Stored as curated static holiday lists per venue/product calendar.
   - Benefit: stable, inspectable, not vendor-dependent.

**V1 stance:** implement the pipeline so calendars are **curated inputs** (data files) and can later be swapped/augmented with vendor APIs without changing the consumer API.

Deliverable: a `calendar_registry` with provenance fields:
- `calendar_id`
- `source_type` (vendor|exchange|manual)
- `source_ref` (url/doc id, if known)
- `valid_from`, `valid_to`
- `generated_at`, `checksum`

### 2) Calendar representation (fast)

Represent a calendar as:
- a **sorted NumPy array of trading dates** as `datetime64[D]` (`trading_days`)
- optionally:
  - a set-like structure for membership checks (but membership can be binary-searched too)
  - a cached mapping date→index for very hot paths (optional; measure first)

Core ops via `np.searchsorted`:
- `is_trading_day(d)`:
  - `i = searchsorted(trading_days, d)`
  - `i < len && trading_days[i] == d`
- `next_trading_day(d)`:
  - `i = searchsorted(trading_days, d, side="right")`
  - return `trading_days[i]` (if i < len)
- `prev_trading_day(d)`:
  - `i = searchsorted(trading_days, d) - 1`
  - return `trading_days[i]` (if i >= 0)
- `add_trading_days(d, n)`:
  - find index of `d` if trading day else choose insertion position with clear semantics
- `trading_days_between(d1, d2)`:
  - return index(d2) - index(d1) with a precise definition

### 3) Semantics: what does “between” mean?

Define these explicitly (normative semantics addendum):

- `trading_days_between(d1, d2)` returns the number of trading-day steps to move from `d1` to `d2`:
  - if `d1 == d2` → 0
  - if `d2` is later → positive
  - if `d2` is earlier → negative
- `d1` and `d2` are interpreted as **dates**, not instants.
- If a date is not a trading day:
  - we choose one convention and enforce it everywhere:
    - either reject (raise) unless caller normalises
    - or normalise internally (e.g., next trading day)
  
**Recommendation for MXM V1:**
- Provide two layers:
  1. strict primitives require trading days (raise if not)
  2. convenience wrappers normalise (e.g., `normalize_to_trading_day(d, how="next")`)

This avoids silent bugs in LTD and roll logic.

### 4) LTD truth surface

We want `FuturesContract.last_trading_day` as an authoritative field.

Source priority:
1. Exchange/vendor published LTD for each contract (best)
2. Derived from contract rules only if:
   - rule is simple, well-known, and testable,
   - and we have official docs captured in `futures_products.csv` or similar.

**V1 approach:**
- Prefer to ingest LTD directly.
- If we must derive, do it per product with explicit unit tests + provenance.

### 5) `bdays_to_ltd` definition

For a contract with `LTD` and a date `t`:
- `bdays_to_ltd(t) = trading_days_between(t, LTD)`
- For roll logic, we usually want negative offsets from LTD:
  - `add_trading_days(LTD, -10)` etc.

We need both scalar and vectorised versions.

## Work plan

### Step 0 — Inventory current state (30–45 min)
- Locate existing calendar logic (if any) in mxm-v1 or shared libs.
- Identify where `last_trading_day` currently lives (instrument defs, mapping tables, etc.).
- Identify which products in the v1 universe require which calendar IDs.

Output:
- A short “current surfaces” note embedded in this session doc (appendix).

### Step 1 — Define calendar IDs and registry (60–90 min)
- Introduce a `calendar_id` naming scheme, e.g.:
  - `cme_globex` (or per exchange)
  - optionally per product if trading days differ materially (usually not needed initially)
- Create a registry file:
  - `mxm_v1/refdata/calendars/calendar_registry.yaml`
  - maps `calendar_id` → source/provenance/validity window

### Step 2 — Build calendar datasets (curated inputs) (time-box)
- Create per-calendar holiday list or direct trading-days list.
- Prefer generating trading-days list from:
  - start/end range
  - weekday rule
  - holiday exclusions
- Persist generated trading-days arrays to Parquet for fast load:
  - `refdata/calendars/<calendar_id>/trading_days.parquet`

V1 acceptance:
- cover from earliest historical date we care about through “today + 2y buffer”.

### Step 3 — Implement `TradingCalendar` core API (90–120 min)
- `TradingCalendar` loads `trading_days` as `np.datetime64[D]` array and exposes:
  - `is_trading_day(d)`
  - `normalize(d, how="next|prev|raise")`
  - `next_trading_day(d)`
  - `prev_trading_day(d)`
  - `add_trading_days(d, n, strict=True|False, normalize=...)`
  - `trading_days_between(d1, d2, strict=True|False, normalize=...)`

Add vectorised forms where obvious:
- `is_trading_day_many(dates) -> bool[]`
- `normalize_many(dates, how=...) -> dates[]`
- `add_trading_days_many(dates, n)` (optional in v1; could come later)

### Step 4 — Contract LTD surface integration (90–180 min)
- Ensure `FuturesContract` (or equivalent) has:
  - `last_trading_day: date`
  - `calendar_id: str`
- Create a reliable path to compute/obtain LTD:
  - from exchange-published contract specs if present
  - or from instrument definitions if Databento supplies last trade / expiration fields
- Add a small inspector:
  - check LTD presence for all contracts in initial universe

### Step 5 — Implement `bdays_to_ltd` (60–90 min)
Provide functions:

- `bdays_to_ltd(date, contract_id) -> int`
- `bdays_to_ltd_many(dates[], ltds[], calendar) -> int[]` (vectorised)

Implementation strategy:
- compute indices once:
  - `idx_t = calendar.index_of_date(t)` (via searchsorted)
  - `idx_ltd = calendar.index_of_date(LTD)`
  - return `idx_ltd - idx_t`

For vectorised:
- use `searchsorted` on arrays:
  - `idx_t = searchsorted(trading_days, dates)`
  - `idx_ltd = searchsorted(trading_days, ltds)`
  - subtract

Important: enforce that dates/ltds are trading days (strict), or normalise explicitly.

### Step 6 — Performance validation (60–90 min)
- Micro-benchmark:
  - 10,000 dates, 3 contracts each (30k computations)
  - ensure it is comfortably fast (order of milliseconds to low tens of ms in NumPy)
- Confirm no Python loops in hot paths:
  - `searchsorted` + vector ops only

If performance is still a concern:
- add caching:
  - precompute `date -> index` dict for the calendar (only if benchmark shows need)
  - avoid repeated date normalisation in loops

### Step 7 — Tests (90–180 min)
Unit tests for:
- `is_trading_day` around weekends + known holiday
- `next/prev` day behaviour around closures
- `add_trading_days` positive/negative offsets
- `trading_days_between` sign and boundary cases
- `bdays_to_ltd` correctness for known examples
- strict vs normalise behaviour

Property tests (optional):
- `add_trading_days(d, n)` then `trading_days_between(d, result) == n`

### Step 8 — Documentation (45–90 min)
Add a short normative extension doc:
- `docs/normative/trading_calendars.md`
that defines:
- calendar meaning in MXM V1
- strictness/normalisation rules
- definition of business-day offsets relative to LTD
- provenance expectations

## File layout (proposed)

### Refdata inputs
- `mxm_v1/refdata/calendars/calendar_registry.yaml`
- `mxm_v1/refdata/calendars/<calendar_id>/holidays.csv` (optional)
- `mxm_v1/refdata/calendars/<calendar_id>/trading_days.parquet`

### Code
- `mxm_v1/calendars/models.py`
  - `TradingCalendar`
  - `CalendarRegistry`
- `mxm_v1/calendars/loaders.py`
  - load registry
  - load calendar datasets
- `mxm_v1/calendars/ops.py`
  - CLI utilities to build/inspect calendars (optional but helpful)
- `mxm_v1/refdata/contracts.py` (or existing location)
  - ensures `last_trading_day` and `calendar_id` surfaces exist
- `mxm_v1/synth/primitives.py` (later session)
  - consumes `bdays_to_ltd` and relative contract logic

### Docs
- `mxm_v1/docs/normative/trading_calendars.md`

## CLI / Ops hooks (minimal)

### Build calendar datasets (if generation step exists)
- `mxm calendars build --calendar-id cme_globex --from 1990-01-01 --to 2030-12-31`

### Inspect calendar
- `mxm calendars inspect --calendar-id cme_globex --date 2020-01-01`

### Validate contract LTD coverage
- `mxm refdata validate-ltd --product-id cme_emini_snp500_futures`

(If you prefer to defer CLI: at least provide Python entrypoints used by orchestrators.)

## Acceptance checks (run at end of session)

1. Calendar loads quickly and deterministically.
2. `add_trading_days(LTD, -10)` returns the expected roll-start date for at least one known contract.
3. `bdays_to_ltd(t)` matches manual calculation on a small sample.
4. LTD coverage validator passes for initial v1 products (or clearly reports gaps).
5. Benchmarks show vectorised path is fast enough to not dominate synth materialisation.

## Open questions to resolve during the session

1. **Calendar granularity**:
   - do we treat “trading day” as “session with settlement price” (likely yes)?
2. **Non-trading-day input semantics**:
   - strict-only vs allowing normalisation by default
3. **Source of LTD**:
   - which vendor/exchange fields are already present in your instrument definitions dataset?
4. **Calendar scope**:
   - one calendar per exchange vs per product (default to per exchange)

## Notes on performance pitfalls (what to avoid)

- Avoid per-date Python loops in `bdays_to_ltd` or `trading_days_between`.
- Do not parse strings to dates in hot loops; normalise once at boundaries.
- Keep calendar dates in `datetime64[D]` or integer day ordinals for fast search.
- If you need membership checks at scale, benchmark `searchsorted` vs dict/set:
  - often `searchsorted` on a sorted array is already sufficient.

## Deliverables summary

- Trading calendar registry + at least one calendar dataset covering v1 products
- `TradingCalendar` API with strict semantics
- `last_trading_day` surfaced and validated for v1 contracts
- `bdays_to_ltd` scalar + vectorised implementation
- Tests + a short normative semantics doc extension

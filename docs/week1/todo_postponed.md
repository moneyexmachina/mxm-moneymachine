# Week 1 — Postponed / Deferred Work

This document records **important work deliberately postponed** during Week 1 of MXM V1.

The purpose is:
- to preserve architectural intent,
- to avoid scope creep during execution,
- and to provide a clear return path once the core spine is operational.

Items here are *not forgotten*; they are intentionally deferred.

## 2026-01-14 — Market Data System

### Internal cost expectation model (Databento)
**Deferred to:** later hardening session  
**Reason:** Not required to prove ingestion/store/serve loop.

- Implement internal estimate of expected rows / bytes for `ohlcv-1d`
- Compare internal estimate vs Databento `metadata.get_cost`
- Abort if outside tolerance (e.g. > ±50%) without explicit override
- Purpose: detect vendor-side surprises and human error early

### DataIO adapter for Databento pulls
**Deferred to:** Session 5  
**Reason:** Marketdata store semantics must be proven first.

- Wrap Databento pull in `mxm-dataio`
- Request-keyed caching (“do not ask the same question twice”)
- Immutable request/reply audit log
- No change to marketdata store or schema expected

### Instrument identity resolution via Databento metadata
**Deferred to:** Session 5 / later  
**Reason:** Raw symbol (`ESH6`) sufficient for golden path.

- Resolve and persist `instrument_id` mapping explicitly
- Avoid reliance on ambiguous year-digit symbols
- Formalise MXM contract ↔ vendor instrument mapping

### Pull ledger / ingestion provenance sidecars
**Deferred to:** later V1 hardening  
**Reason:** Parquet store correctness takes priority.

- Record pull-level metadata (request params, cost, timestamp)
- Store as append-only JSON or SQLite
- Keep row-level store clean

### Exchange calendar and session semantics validation
**Deferred to:** later  
**Reason:** Daily bar semantics accepted “as-is” from vendor for V1.

- Validate trading days vs holidays
- Clarify Globex session vs UTC day alignment
- Reconcile with settlements if required

## API Layer & Downstream Consumption

### Marketdata serving API (`mxm.v1.marketdata.api`)
**Deferred to:** Session 5  
**Reason:** Core store semantics proven; API adds ergonomics, not correctness.

- Introduce a stable serving API on top of the Parquet store
- Encapsulate:
  - `MarketdataLayout`
  - instrument identity handling
  - start/end slicing defaults
- Provide functions such as:
  - `get_daily_bars(instrument_key, start, end)`
  - `get_latest_daily_bars(instrument_key)`
- Ensure API layer:
  - never talks to vendors
  - never performs writes
  - only reads from the canonical store

**Purpose:**
- decouple downstream applications (signals, backtests, portfolio logic) from store internals
- allow store layout changes without breaking consumers
- provide a clean public contract for MXM V1 usage

**Explicitly not included (V1):**
- caching beyond the Parquet store
- rolling logic
- cross-instrument joins or alignment
- vendor fallbacks

These remain responsibilities of higher layers or future extensions.

## Architecture & Package Boundaries

### Extraction of Databento integration into `mxm-datakraken`
**Deferred to:** after MXM V1 marketdata spine is stable  
**Reason:** Avoid premature abstraction before semantics are proven.

- Extract Databento-specific logic (pull, cost, normalization) into `mxm-datakraken`
- Treat Databento as a *vendor domain adapter*
- Continue to use `mxm-dataio` inside `mxm-datakraken` for request caching
- Keep `mxm-v1` focused on *application-level orchestration*, not vendor plumbing

### Extraction of market data store into `mxm-marketdata`
**Deferred to:** after V1 proves operational usefulness  
**Reason:** Store semantics must stabilise before generalisation.

- Promote Parquet store, schema enforcement, and merge semantics into `mxm-marketdata`
- Generalise store to support:
  - multiple vendors
  - additional schemas (intraday bars, BBO, etc.)
- Preserve current instrument-keyed identity model
- Keep request caching and vendor logic *out* of `mxm-marketdata`

### Multi-vendor reconciliation
**Deferred to:** well beyond V1  
**Reason:** Requires stable internal instrument identity and semantics.

- Compare daily bars across vendors
- Decide authority / reconciliation rules
- Possibly introduce confidence or quality metrics per bar

## Notes

- Items are deferred **by design**, not due to oversight.
- New items should only be added here if they were consciously postponed.
- Once an item is implemented, remove it (do not mark “done” here).


### Packaging — Resolve `click` Version Constraint Conflict (`mxm-config` vs `mxm-secrets`)

**Context**  
While integrating `mxm-dataio` into MXM V1 (Session 5), a dependency resolution failure was discovered between `mxm-config` and `mxm-secrets`.

**Observed conflict**
- `mxm-secrets (0.1.0)` depends on `click ^8.2.1`
- `mxm-config (0.5.0)` depends on `click >=8.1.6,<8.2`
- This prevents co-installation of `mxm-config` and `mxm-secrets` in the same environment

**Impact**
- Blocks adding `mxm-config` as a dependency to MXM V1
- Forced use of a minimal local config shim for `mxm-dataio` in Session 5

**Intended resolution**
- Verify `mxm-config` compatibility with `click 8.2.x`
- If compatible:
  - Relax `mxm-config` click constraint to `<9` or `^8.1.6`
  - Release a patch version (e.g. `mxm-config 0.5.1`)
- Alternatively (less preferred):
  - Narrow `mxm-secrets` click constraint downward

**Notes**
- This is a packaging hygiene issue, not a functional blocker for MXM V1 marketdata ingestion
- Resolution should be handled as a dedicated maintenance task, not within an MVP delivery session



### Selective DataIO cache inspection & eviction tooling

**Deferred to:** later DataIO hardening / ops tooling session  
**Reason:** Not required to prove marketdata ingestion, persistence, and watermark semantics.

- Add capability to **inspect DataIO cache entries** (request metadata + artifact presence)
- Support **selective eviction** of cached responses:
  - by request hash
  - by source (e.g. `databento`)
  - by age (e.g. `older-than 30d`)
  - by simple parameter match (e.g. symbol contains `ES.FUT`)
- Default to **artifact-only deletion** (soft eviction):
  - force re-fetch on next request
  - preserve metadata / audit trail
- Provide optional **hard eviction** (metadata + artifacts) behind explicit flag
- Add a **cache doctor / repair** mode:
  - detect missing artifacts referenced by metadata
  - report disk usage
  - optionally clean dangling entries

**Intended interface (illustrative):**
- `mxm-dataio cache ls [--source databento] [--contains ES.FUT]`
- `mxm-dataio cache rm --hash <HASH> [--dry-run]`
- `mxm-dataio cache rm --older-than 30d --source databento`
- `mxm-dataio cache doctor [--fix]`

**Purpose:**
- enable controlled cache invalidation during development and debugging
- avoid full cache wipes or ad-hoc filesystem manipulation
- preserve DataIO’s auditability while allowing operational hygiene

**Explicitly not required for V1:**
- automatic eviction policies
- size-based cache management
- cross-user or multi-host cache coordination

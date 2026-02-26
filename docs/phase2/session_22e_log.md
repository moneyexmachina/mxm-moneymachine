# session_22e_log.md

## Session 22e — Daily Stats Derivation + Provenance Wiring

**Date:** 2026-02-25  
**Scope:** statistics_1d → daily_stats derived surface  
**Status:** Operationally complete; provenance semantics clarified; strict-mode enforcement partially wired and under review.

## 1. Context

Session 22 has focused on extending the marketdata layer beyond `ohlcv_1d` to include:

- `statistics_1d` ingestion
- Product-level orchestration integration
- Inspection tooling
- Construction of a derived daily-level surface: `daily_stats`

Session 22e specifically focused on:

- Finalising the `daily_stats` dataset store
- Wiring the orchestrator for update/reset flows
- Implementing meta-first coverage snapshots
- Testing idempotency and provenance semantics
- Introducing and evaluating `--require-source-meta`

This represents a significant architectural milestone:  
we now have a **second dataset type fully flowing through the V1 architecture**, including derived surface persistence and audit metadata.

## 2. What Was Achieved

### 2.1 DailyStatsStore (dataset-domain store)

Implemented:

- Stable path resolution via `MarketdataLayout`
- Parquet persistence via `write_daily_stats`
- Sidecar meta handling
- Coverage introspection via `scan_coverage()`

Key properties:

- Meta-first coverage snapshot
- Fallback to parquet scan if meta missing or corrupt
- Explicit snapshot structure:
  - `exists`
  - `row_count`
  - `min_ts` / `max_ts`
  - `content_sha256`
  - `artifact_sha256`
  - `source_content_sha256`
  - `meta_path`

This matches the architectural pattern used elsewhere in V1.

### 2.2 Derived Surface Semantics

`daily_stats`:

- Is identity-scoped (dataset + publisher_id + instrument_id)
- Is built from `statistics_1d`
- Is idempotent via upstream `content_sha256`
- Writes:
  - `content_sha256` (semantic hash of daily_stats)
  - `artifact_sha256` (parquet bytes)
  - `source_content_sha256` (fingerprint of upstream statistics)

We verified:

- First run builds
- Second run skips unchanged
- `--reset-local` forces rebuild
- Idempotency is stable across runs

The gating behaviour is functioning correctly.

### 2.3 Timestamp Alignment Fix

Resolved an upstream alignment issue:

- Previously used `fmt_day_ts(upstream.ts_min / ts_max)`
- Corrected to use run timestamps (`fmt_run_ts`) for event streams

This fixed non-day-aligned event stream issues and restored correct reporting.

### 2.4 Operational Test Matrix

Verified:

| Scenario | Expected | Observed |
|----------|----------|----------|
| Dry-run, no downstream | would_build | ✅ |
| Non-dry-run, no downstream | built | ✅ |
| Second run | skipped_unchanged | ✅ |
| Reset-local | built | ✅ |
| Upstream missing | skipped_no_upstream | ✅ |
| Meta sidecar written | Yes | ✅ |

All operational paths are behaving deterministically.

## 3. `--require-source-meta` Flag

### Intended Purpose

The flag was introduced to enforce **strict provenance semantics**:

When enabled:
- Only allow derivation if upstream statistics meta exists and is valid.
- Guarantee that `daily_stats.source_content_sha256`
  originates from upstream canonical meta.

Without it:
- Allow fallback hashing or permissive derivation.
- Maintain operational progress even if meta missing.

### Current Behaviour

Observed:

- Contracts with upstream parquet but no meta were still allowed to proceed in dry-run.
- This indicates that `scan_coverage()` fallback path is providing `content_sha256`
  even when meta does not exist.

Conclusion:

`require_source_meta` is not yet strictly gating on meta presence.

This is not a correctness bug.
It is a **provenance semantics decision point**.

## 4. Architectural Milestones Reached

This session represents meaningful progress:

1. Second dataset integrated end-to-end
2. Derived surface layer operational
3. Idempotent gating using upstream fingerprints
4. Meta sidecar semantics consistent
5. Reset flows validated
6. Strict-mode flag conceptually introduced
7. Provenance semantics explicitly debated

The V1 marketdata architecture now supports:

```
instrument_definitions
        ↓
mappings
        ↓
statistics_1d
        ↓
daily_stats (derived)
```

with identity-scoped stores and audit-grade metadata at each layer.

This is a major structural extension.

## 5. Open Design Questions (Deliberate, Not Bugs)

### 5.1 What Should `source_content_sha256` Mean?

Two possible semantics:

#### Option A — Strict Provenance (Recommended Long-Term)

- `source_content_sha256` only valid if derived from upstream meta.
- Fallback hashes must not populate it.
- `--require-source-meta` blocks derivation if meta absent.

This gives audit-grade chain of custody.

#### Option B — Operational Provenance

- Allow computed fallback hashes.
- Field means "observed upstream content hash".
- Useful for skip gating, but weaker audit meaning.

Decision pending.

## 6. TODO / Next Steps

### 6.1 Enforce Meta Presence in Strict Mode

If strict semantics chosen:

- Extend `Statistics1DStore.scan_coverage()` to expose:
  - `meta_exists`
  - optionally `content_sha256_source`
- In orchestrator:
  - If `require_source_meta` and no upstream meta → skip with:
    - `status = skipped_no_upstream`
    - `status_detail = statistics_meta_missing`

### 6.2 Clarify Hash Provenance Semantics

Define explicitly in docs:

- Whether fallback-computed hashes are acceptable.
- Whether downstream `source_content_sha256` may ever be null.
- Whether computed hashes should be labelled in meta.

### 6.3 Add Unit Tests

Add tests for:

- Strict-mode skip when meta missing.
- Non-strict-mode fallback behaviour.
- Downstream meta writing semantics under both modes.

### 6.4 Inspection Tooling

Extend inspection module to:

- Surface `source_content_sha256`
- Highlight meta-backed vs computed fingerprints
- Verify upstream/downstream hash alignment

### 6.5 Daily View API

Next structural step in Session 22:

- Construct product-level daily view
- Provide query interface for downstream systems
- Establish contract for consumption

## 7. Overall Assessment

Session 22e delivered:

- A fully operational derived daily surface
- Stable idempotent behaviour
- Reset and skip gating verified
- Provenance chain implemented
- Strict-mode enforcement concept introduced

This is not incremental progress.
This is structural completion of the second dataset integration phase.

The remaining work is not plumbing.
It is semantic tightening.

That is a good place to be.


# MXM V1 — Session 11b Plan
## DataIO Cache Integrity: Missing Payload ⇒ Cache Miss + Reissue

**Phase:** Phase 2 — Market Data Completion  
**Session:** 11b (repair session)  
**Primary package:** `mxm-dataio`  
**Primary consumer impacted:** `mxm-v1` Databento pull paths (instrument definitions, OHLCV, later datasets)  
**Branch:** `feat/dataio-missing-payload-reissue` (recommended)

## Objective

Fix `mxm-dataio` so that if a cached response entry exists but the referenced payload file is missing, the system treats this as a **cache miss**, **reissues the request**, and **repopulates the payload file**—without requiring manual cache resets and without leaking this concern into `mxm-v1`.

## Scope

### In-scope
- Detect missing payload files referenced by cache metadata/index.
- Convert “missing payload” into a **cache-miss path** (re-fetch + rewrite payload).
- Optional: mark the cache entry as corrupted/invalidated (depending on architecture).
- Add proof surface (script or test) demonstrating the repair behaviour.
- Ensure behaviour is consistent for both:
  - “read existing cached response”
  - “execute request and persist response”

### Out-of-scope
- Checksums / content hash validation of payload bytes (future enhancement).
- Partial writes / corrupt payload recovery beyond simple missing-file detection.
- Broader cache eviction, TTL, GC, or index compaction policies.

## Exit Criteria (Non-Negotiable)

1. When a cache record points to a missing payload file, the next identical request:
   - does **not** raise `FileNotFoundError`,
   - **reissues** the upstream request,
   - writes a new payload file at the expected location (or updates metadata to a new payload location),
   - returns a valid response payload to the caller.

2. A proof surface exists (test or script) that:
   - creates a cached response,
   - deletes only the payload file,
   - re-runs the same request,
   - demonstrates the reissue and successful recovery.

3. No changes are required in `mxm-v1` to work around this (other than removing any temporary hacks if present).

## Background / Problem Statement

During Session 11, instrument definitions orchestration failed because DataIO returned a response pointing at a cached payload path that had been deleted. The current implementation assumes “cache hit implies payload exists” and attempts to read `Path(resp.path).read_bytes()` unconditionally, triggering `FileNotFoundError`.

This violates operational robustness. Cache metadata must not be treated as authoritative if the payload file is absent.

## Proposed Behaviour (Specification)

### Terminology
- **Cache index/record:** metadata that indicates a prior response exists (request hash, response path, etc.).
- **Payload file:** the actual bytes persisted to disk.

### Behaviour
When resolving a request:
1. If the cache record exists:
   - If payload file exists: return cached response as normal.
   - If payload file is missing:
     - treat as cache miss
     - optionally mark cache record invalid (or delete it)
     - reissue request upstream
     - persist payload bytes
     - update cache record (if needed)
     - return the new response

### Logging
Emit a single explicit event for observability:
- e.g. `"[dataio][cache] missing_payload => reissue request_hash=... path=..."`

## Implementation Plan

### Step 1 — Locate the cache-hit resolution boundary
Identify the exact function/method where DataIO decides:
- “we have a cached response, return it”
vs
- “execute request and persist”

This is the correct injection point for the missing-file check.

**Deliverable:** pinpointed location + minimal patch strategy.

### Step 2 — Implement missing-payload detection
Add:

- `if not Path(payload_path).exists(): ...`

Decide on one of:
- **Invalidate** cache record (delete/mark-stale) and reissue
- Or **reissue without invalidation** but ensure subsequent reads will succeed

**Preferred MVP:** invalidate (delete record) then reissue, because it removes ambiguity and makes subsequent behaviour clean.

**Deliverable:** missing payload becomes deterministic cache miss.

### Step 3 — Ensure idempotent persistence semantics still hold
Confirm that the reissued response:
- is written to disk
- is referenced consistently by whatever response object DataIO returns
- preserves request-keyed caching semantics

**Deliverable:** no duplicate or inconsistent records, stable paths.

### Step 4 — Proof surface
Choose one (both acceptable):

#### Option A: Small proof script (fastest)
Create a script in `mxm-dataio` or in `mxm-v1/scripts/proofs/` that:
1. Executes a real request (small, bounded, cheap) through DataIO.
2. Records request hash + payload path.
3. Deletes the payload file only.
4. Re-runs the identical DataIO request.
5. Asserts:
   - no exception
   - payload file exists again
   - response is readable

#### Option B: Test with a fake adapter (cleaner, no paid calls)
- Use a dummy adapter that returns deterministic bytes.
- Verify cache recovery without network.

**Recommendation:** Option B if you already have a test harness; otherwise Option A is acceptable for this session, but keep it low-cost.

**Deliverable:** proof that fails on old behaviour and passes on new behaviour.

## Session Breakdown (Single-session, two passes)

### Pass 1 (Diagnosis + Patch)
- Find cache-hit boundary
- Implement missing-file detection
- Reissue behaviour + minimal logging
- Run local sanity checks

### Pass 2 (Proof + Tightening)
- Implement proof script/test
- Ensure failure mode is eliminated
- Confirm no regression for normal cache hits

## Proof Surfaces

### Proof 11b-1 — “Missing payload triggers reissue”
Expected output includes:
- detection message (`missing_payload`)
- a subsequent successful response read
- payload file re-created

### Proof 11b-2 — “Normal cache hit still works”
- same request run twice without deleting payload
- second run should use cache (as observed by your existing DataIO logging)

## Risk Notes

- If the cache index is written in a way that cannot be invalidated cleanly, prefer:
  - mark entry invalid (status field) rather than deleting
- If concurrency exists (multiple processes), ensure the missing-file branch cannot corrupt shared state.
  - MVP assumption can be single-process; document it.

## Deliverables (Files / Changes)

- `mxm-dataio`: missing payload detection + reissue logic at cache-hit boundary
- `mxm-dataio`: proof test/script demonstrating behaviour
- (Optional) small docs note in `mxm-dataio` README or `docs/` about cache integrity invariants

## Completion Checklist

- [ ] Missing payload no longer throws `FileNotFoundError`
- [ ] Reissue happens automatically and deterministically
- [ ] Payload file is recreated
- [ ] Proof surface added and passing
- [ ] No `mxm-v1` workaround required
- [ ] Commit message reflects behaviour change clearly

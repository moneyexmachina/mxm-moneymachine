# Session 36c Plan — Adopt `mxm-types` in `mxm-v1`

## Date
2026-04-20

## Summary

Session 36b extracted the canonical MXM timestamp substrate from `mxm-v1` into `mxm-types` and released it as `mxm-types v0.2.0`.

The next step is to adopt that shared package cleanly inside `mxm-v1`.

This is a focused warm-up session: small in scope, high in cleanliness, and directly useful for the continuation of Session 36 work. The goal is to remove remaining local ownership of the timestamp substrate in `mxm-v1` and replace it with imports from `mxm.types`.

## Session Objective

Update `mxm-v1` to use the newly shared timestamp package by:

- replacing imports from local timestamp modules with imports from `mxm.types`
- deciding how to handle any temporary compatibility shims
- confirming that tests still pass unchanged semantically

This session is not about redesigning timestamp semantics. It is about completing the ownership move already established in Session 36b.

## Core Goal

Ensure that `mxm-v1` no longer acts as the owner of the canonical timestamp model.

After this session:

- `mxm.types.timestamps` should be the authoritative source for the canonical timestamp substrate
- `mxm.types.pandas_timestamps` should be the authoritative source for pandas boundary adapters
- `mxm-v1` should consume these shared modules rather than defining equivalent local ownership

## Scope

### In Scope

- audit all imports in `mxm-v1` referring to:
  - `mxm.v1.utils.timestamps`
  - `mxm.v1.utils.pandas_timestamps`
- replace them with:
  - `mxm.types`
  - or explicit submodule imports from `mxm.types.timestamps` / `mxm.types.pandas_timestamps`
- update dependency metadata if needed
- decide whether to keep or remove local shim modules
- run tests and type checks to confirm the migration is clean

### Out of Scope

- redesign of timestamp APIs
- SQLite / Parquet / storage adapter work
- calendar or session semantics
- broader `mxm-v1` package cleanup unrelated to timestamps
- `mxm-pipeline` reporting model migration (that belongs to the next step after this)

## Main Design Question

The only real design question for this session is:

> Should `mxm-v1` keep temporary shim modules for `timestamps.py` and `pandas_timestamps.py`, or should imports be rewritten directly everywhere now?

### Preferred answer

If the import footprint is manageable, rewrite imports directly now and remove local ownership immediately.

### Acceptable fallback

If a direct rewrite creates too much churn for a short warm-up session, keep thin compatibility shims temporarily:

- `mxm.v1.utils.timestamps`
- `mxm.v1.utils.pandas_timestamps`

with those modules simply re-exporting from `mxm.types`.

If shims are used, they should be treated as transitional and removed soon after.

## Proposed Tasks

### 1. Audit current usage in `mxm-v1`

Find all references to:

- `mxm.v1.utils.timestamps`
- `mxm.v1.utils.pandas_timestamps`

Identify:

- direct imports
- transitive imports
- any local code still assuming those modules are owned by `mxm-v1`

### 2. Update package dependency

Confirm that `mxm-v1` now depends on:

- `mxm-types >= 0.2.0`

Update dependency metadata and lock state as needed.

### 3. Switch imports

Replace local timestamp imports with imports from `mxm.types`.

Preferred style:

- import from explicit submodules where clarity matters
- use package-level re-exports only where that improves readability and does not obscure layer boundaries

### 4. Decide on shim policy

Either:

- remove local timestamp modules entirely, or
- keep minimal temporary re-export shims

This should be a deliberate choice, not an accidental half-state.

### 5. Run validation

Run:

- tests
- Pyright
- Ruff / Black checks

Confirm that the migration is semantically neutral.

## Success Criteria

By the end of Session 36c:

- `mxm-v1` imports canonical timestamp functionality from `mxm.types`
- no timestamp semantics remain locally owned by `mxm-v1`
- dependency metadata reflects the new shared package
- checks pass
- the codebase is ready for continued pipeline and storage work on top of the shared timestamp substrate

## Why This Session Matters

This is a small but important completion step.

Session 36b moved the substrate.
Session 36c makes that move real in downstream usage.

Without this step, the extraction remains conceptually correct but operationally incomplete.

With it, the timestamp ownership boundary becomes fully established across the MXM ecosystem.

## Next Step After Session 36c

Resume Session 36a / `mxm-pipeline` work with the timestamp model now cleanly shared across packages:

- adopt canonical timestamps in reporting models
- implement reporting `serde.py`
- proceed with SQLite stores

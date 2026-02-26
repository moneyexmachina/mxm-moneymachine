# session_22f_plan.md

## Session 22f — Provenance Tightening, Integration, and First Visual Output

**Date:** 2026-02-25  
**Scope:** Hardening daily_stats semantics, integrating into product orchestration, and producing the first real reporting output of MXM V1.  
**Theme of the week:** Move from plumbing to visible surface.

## 1. Objectives

Session 22f has four architectural goals and one strategic goal.

### Architectural Goals

1. Resolve and formalise `--require-source-meta` semantics.
2. Wire `daily_stats` into the product-level marketdata orchestrator.
3. Build an inspect layer for `daily_stats`.
4. Expose a downstream API for consuming `daily_stats`.

### Strategic Goal (Most Important This Week)

Produce the **first proper output of the system**:

- Contract-level plots and reports.
- Product-level aggregated plots across contracts.

This is the first visible surface of the entire V1 data stack.

## 2. Task 1 — Resolve `require_source_meta`

### 2.1 Clarify Intended Semantics

We must choose and document one of the following:

#### Option A — Strict Provenance (Recommended)

- `source_content_sha256` must originate from upstream meta.
- If `require_source_meta=True` and meta missing → skip derivation.
- Fallback-computed hashes must not populate provenance fields.

This gives audit-grade chain-of-custody semantics.

#### Option B — Operational Mode

- Allow fallback hashing.
- `source_content_sha256` may originate from computed fingerprint.
- Strict mode only blocks if upstream parquet absent.

Less strict, faster iteration.

### 2.2 Required Implementation Changes

If strict semantics chosen:

- Extend `Statistics1DStore.scan_coverage()` to expose:
  - `meta_exists: bool`
  - optionally `content_sha256_source`
- In daily_stats orchestrator:
  - If `require_source_meta` and not `meta_exists`:
    - `status = skipped_no_upstream`
    - `status_detail = statistics_meta_missing`

Add tests for:

- Strict-mode skip when meta missing.
- Non-strict-mode fallback build.

Deliverable:
- Deterministic, documented provenance policy.

## 3. Task 2 — Wire daily_stats into Product Orchestrator

Currently:

- `instrument_definitions`
- `mappings`
- `ohlcv_1d`
- `statistics_1d`

Next:

- Add `daily_stats` stage to product-marketdata orchestration.

### 3.1 Design Principle

Product-level orchestration should:

- Treat `daily_stats` as a derived dataset stage.
- Gate on upstream `statistics_1d`.
- Respect dataset range arguments.
- Maintain idempotent behaviour.

### 3.2 Implementation

- Add `--stage daily_stats` or equivalent wiring.
- Ensure stage ordering:
  
  ```
  statistics_1d → daily_stats
  ```

- Integrate into cost and summary reporting.

Deliverable:
- Product-level invocation builds both statistics and daily_stats in one flow.

## 4. Task 3 — Inspect Layer for daily_stats

We need parity with `ohlcv_1d` and `statistics_1d`.

### 4.1 Required Capabilities

`marketdata_inspect daily_stats` should support:

- Identity-scoped inspection.
- Date range.
- Row count.
- Min/max session_date.
- Hash inspection:
  - content_sha256
  - artifact_sha256
  - source_content_sha256
- Sample rows (n=5).
- Human-readable summary.

### 4.2 Additional Feature

Add explicit upstream linkage reporting:

Example:

```
Upstream statistics content_sha256: X
Downstream daily_stats source_content_sha256: Y
Match: True
```

Deliverable:
- Full inspection parity across datasets.

## 5. Task 4 — Downstream API for daily_stats

This is where daily_stats becomes consumable.

### 5.1 Required API Surface

Identity-scoped read:

```python
read_daily_stats(
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
)
```

### 5.2 Product-Level View

Implement:

```python
read_product_daily_stats(
    product_id: str,
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
)
```

Returns:

- Concatenated contract-level daily stats.
- Multi-index or contract_key column.
- Sorted by session_date.

This will be the foundation for plotting and synthetic asset construction.

Deliverable:
- Clean API layer for downstream analytics.

## 6. Strategic Priority — First Proper Output

This week’s most important outcome is not another store or orchestrator.

It is a plot.

We want:

1. Per-contract report.
2. Product-level report across all contracts.

This is the first visible manifestation of MXM V1.

## 6.1 Contract-Level Report

For each contract:

Plot:

- Settle price over time.
- Volume.
- Open interest.
- Optional flags (settle_px_is_final).

Minimum required output:

- PNG file per contract.
- Stored under a deterministic reports path.
- Named by contract_key.

Optional additions:

- Summary statistics table.
- Final settle value.
- Date range coverage.

## 6.2 Product-Level Report

Aggregate across contracts:

Options:

- Overlay settle price time series.
- Stitch front contracts.
- Show contract roll windows.
- Compare open interest patterns.

Minimum deliverable:

- Single PNG showing:
  - Each contract settle price.
  - Labeled by contract_key.

This becomes:

> The first visual validation of the entire ingestion and derivation stack.

## 6.3 Technical Plan for Plotting

- Build a CLI entrypoint:
  ```
  scripts/marketdata/reports/daily_stats_report.py
  ```

- Use matplotlib (initially).
- Output PNG.
- Write to deterministic path:
  ```
  ~/.mxm/reports/daily_stats/{product_id}/...
  ```

- Log run metadata.

Optional enhancement:
- Generate HTML summary report (later).

## 7. Success Criteria for Session 22f

We consider 22f successful when:

- `require_source_meta` semantics are explicitly defined and enforced.
- `daily_stats` is wired into product-level orchestration.
- `marketdata_inspect` supports daily_stats.
- Downstream API exists and is clean.
- At least one product-level plot is generated.

The final bullet is the most important.

Because at that moment, the system stops being abstract architecture and becomes observable reality.

## 8. End-of-Week Target

By end of this week:

You should be able to run:

```bash
poetry run python scripts/marketdata/reports/daily_stats_report.py \
  --product-id cme_emini_snp500_futures
```

And obtain:

- Per-contract PNGs.
- A product-level PNG.
- Deterministic, reproducible output.

That will be the first proper surface of MXM V1.

## 9. Structural Positioning

Session 22e completed structural plumbing.  
Session 22f converts that plumbing into surface and signal.

This is the transition from:

> “Does the system work?”

to

> “What does the system show?”

That shift matters.


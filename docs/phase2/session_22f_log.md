# Session 22f — statistics_1d Hardening and daily_stats Integration

## Context

Session 22f focused on stabilizing the `statistics_1d` dataset semantics and completing
the downstream integration of `daily_stats` as the first derived surface within MXM V1.

The goals were:

1. Resolve timestamp invariant violations in `statistics_1d`.
2. Ensure deterministic and consistent `daily_stats` derivation.
3. Integrate `daily_stats` into the product-level meta-orchestrator.
4. Prepare for inspect-layer exposure (implementation deferred).

This session closes the loop from vendor statistics ingestion to a derived daily surface,
but does not yet complete the inspect integration.

## 1. statistics_1d Timestamp Semantics Correction

### Problem

`expected_start` and `expected_end` were being formatted using `fmt_day_ts`,
which enforces midnight alignment. However:

- `dataset_end` can legitimately be intraday (vendor timestamp).
- Therefore `expected_end` can also legitimately be intraday.

This caused invariant violations:

```
ValueError: Expected UTC-midnight timestamp
```

### Resolution

- Restricted `fmt_day_ts` strictly to:
  - interest_start / interest_end
  - activation_floor / expiration_ceiling
- All run metadata now uses `fmt_run_ts`.
- Removed midnight formatting from `expected_start` / `expected_end`.
- Explicitly rejected encoding datatype semantics into field names.

### Result

- statistics_1d inspect surface now terminal and clean.
- All mapped contracts (84/84) complete.
- Zero errors.
- Vendor-final correctly reflected.

The dataset now respects its own declared timestamp invariants.

## 2. daily_stats Selection Semantics Hardening

### Issue

`ts_ref` and `trading_date` are nullable in `statistics_1d`.

Previously, TradingCalendar mapping was applied only to stat_types without `ts_ref`.
However:

- Some stat_types with `ts_ref` may still have null `trading_date`.
- Those must also be mapped via TradingCalendar.

### Resolution

Selection layer updated to:

- Apply TradingCalendar mapping for:
  - event-time anchored stat_types
  - ts_ref stat_types where `trading_date` is null
- Enforce deterministic one-row-per-session_date selection.
- Preserve final-preference semantics.
- Maintain idempotent merge behavior across stat_types.

### Result

`daily_stats` derivation is now:

- Deterministic
- Calendar-consistent
- One-row-per-session_date
- Idempotent

The selection layer is structurally sound.

## 3. daily_stats Operational Execution

Executed:

```
poetry run python scripts/marketdata/ops/daily_stats.py \
  --product-id cme_emini_snp500_futures \
  --mode bootstrap
```

Observed:

- 84 contracts built
- 0 errors
- Compute-only stage (cost_used_usd = 0.0)
- Provenance respected
- No vendor calls triggered

This marks the first fully derived dataset in MXM V1.

## 4. Integration into product_marketdata Orchestrator

Added Stage 5:

```
statistics_1d
→ daily_stats
```

### Properties

- StageEnvelope normalization preserved.
- No vendor cost consumption.
- Budget propagation intact.
- Downstream gated on statistics_1d success.
- Included in product-level attempt envelope.

Pipeline now:

1. instrument_definitions
2. instrument_definition_mappings
3. ohlcv_1d
4. statistics_1d
5. daily_stats

Product-level orchestration verified via ops script.

## 5. Architectural Outcome

At the end of Session 22f:

- `statistics_1d` is stable and invariant-consistent.
- `daily_stats` is deterministic and reproducible.
- Product-level pipeline includes derived surface.
- End-to-end ingestion → derivation → orchestration loop operational.

This is the first complete vertical slice of MXM V1:

Vendor Data → Normalized Dataset → Derived Dataset → Product Orchestration.

## Deferred Work (Moved to Session 22g)

The following were designed conceptually but not implemented in Session 22f:

1. Integrate `daily_stats` into `marketdata_inspect.py`.
2. Add dispatch routes for:
   - daily_stats contract
   - daily_stats product
   - daily_stats system
   - daily_stats instrument
3. Provide inspect-level completeness diagnostics for daily_stats.
4. Add human-readable summaries for inspect outputs.

These items will be formalized in `session_22g_plan.md`.

Session 22f successfully stabilizes and operationalizes the first derived surface in MXM V1.

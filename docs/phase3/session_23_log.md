# Session 23 – ContractSeries (Identity Realisation Layer)

Status: ✅ Completed  
Date: 2026-03-XX  
Scope: Contracts subsystem (identity realisation over trading sessions)

## 1. Objective

Session 23 implemented the **ContractSeries** abstraction.

Conceptually:

> A `ContractSeries` is a time-indexed identity mapping:  
> given a `(product_id, SelectorRule)` and a trading-session range,  
> realise the selected `contract_id` at each session.

It is **not**:
- a storage object,
- a persistence layer,
- a P&L object,
- a synthetic asset,
- or a trading system.

It is a deterministic, pure builder that bridges:

- Trading calendars  
- Contract selection engine  
- Session-indexed time series surfaces  

This closes the loop from:
`SelectorRule (relative contract definition)`
→ `engine.explain(...)`
→ `time-indexed identity surface`.

## 2. Final Design

### 2.1 ContractSeriesSpec

```python
@dataclass(frozen=True)
class ContractSeriesSpec:
    product_id: str
    rule: SelectorRule
    start_session: np.datetime64
    end_session: np.datetime64
```

Semantics:
- `start_session` and `end_session` must be valid trading sessions.
- Range is inclusive.
- Sessions must be present in the calendar (exact match).
- End must be ≥ start.

### 2.2 ContractSeries (final form)

```python
@dataclass(frozen=True)
class ContractSeries:
    product_id: str
    canonical_relative_id: str
    short_rel_id: str
    sessions: np.ndarray  # datetime64[D]
    contract_ids: list[str]
```

Important design decisions:

- **Only `contract_ids` are stored.**
- `period_ids` are implicit via RefData and not duplicated.
- Series is guaranteed non-empty.
- Sessions are strictly increasing `datetime64[D]`.

Derived helpers:
- `switch_mask()`
- `switch_sessions()`
- `switch_view(max_rows=...)`

## 3. Builder Semantics

### `build_contract_series(...)`

Properties:

- Pure function (no caching, no storage).
- Hard fail if selection fails at any session.
- Uses `engine.explain(...)` to obtain:
  - `selected_contract_id`
  - canonical and short rule labels.

Time handling:
- Session day labels → `utc_day_start(day)`
- Full UTC normalization via `time_utils`.

This makes the identity realisation layer deterministic and auditable.

## 4. Real-World Smoke Script

Created:

```
scripts/contracts/smoke_contract_series.py
```

Example invocation:

```
poetry run python scripts/contracts/smoke_contract_series.py \
    --product-id cme_emini_snp500_futures \
    --start 2025-01-02 \
    --end 2025-03-31
```

Output shows:

- Canonical rule label
- Short rule label
- Session count
- Head rows
- Switch summary

Example switch:

```
2025-03-24 : Mar-2025  ->  Jun-2025
```

This provides:
- deterministic,
- repeatable,
- production-path validation

without interactive REPL state dependency.

This replaces notebook-driven exploration with reproducible object realisation.

## 5. Time Semantics Tightening

During integration, a gap was discovered:

`coerce_date()` did not accept `np.datetime64`.

### Change implemented:

Added explicit support for:

```python
if isinstance(value, np.datetime64):
    s = str(value.astype("datetime64[D]"))
    return date.fromisoformat(s)
```

This ensures:
- internal day-label surfaces are first-class citizens,
- no string workarounds required,
- consistent UTC semantics.

## 6. New Test Coverage

Added:

```
tests/unittests/mxm/v1/utils/test_date_utils.py
```

Covers:

- ensure_1d_day_array
- coerce_np_day
- coerce_date (including np.datetime64 support)
- searchsorted_exact
- utc_day_start / utc_day_end_exclusive
- fmt_iso_day
- day_in_set

All tests passing.

Full suite status:

```
153+ tests passing
```

## 7. Conceptual Position in System

After Session 23, the contracts layer now has:

- SelectorRule
- PeriodFilter
- canonical_relative_id / short_rel_id
- ContractSelectorEngine
- ContractSeries (identity over time)

This forms a complete and stable **contract identity subsystem**.

It is now ready to support:

- Session 24 – SyntheticAssetSpec
- Session 25 – Dynamic holdings
- Session 26 – Target holdings
- Session 27 – Target trades
- Session 28 – Executor
- Session 29 – P&L
- Session 30 – Plotting & inspection

## 8. Architectural Assessment

This layer is:

- Minimal
- Deterministic
- Fully test-covered
- Pure
- Calendar-aligned
- UTC-normalised
- Strict-failure semantics

It does not overreach into:
- storage
- execution
- aggregation
- portfolio construction

Therefore, Session 23 can be considered cleanly closed.


# Session 23 Complete

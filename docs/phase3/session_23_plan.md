# session_23_plan.md — MXM V1  
## Session 23 — Close ContractSeries (Instrument Identity Surface)

## Position in Architecture

We previously introduced the `ContractSeries` layer (Session 20 conceptually) as the realisation of:

    (product_id, rule, session_index) -> time-indexed contract identity path

This layer sits strictly between:

1. SelectorRule (intent)
2. SyntheticAssetSpec (instrument definition)

It is a **pure identity surface**.

It does not:
- define weights
- define roll logic
- compute holdings
- compute trades
- compute P&L

Session 23 finalises and locks this layer as a stable substrate.

## Objective

Declare `ContractSeries` complete, trusted, and deterministic.

By the end of Session 23:

- Semantics are explicitly tested.
- Failure modes are locked.
- Inspection surface exists.
- No ambiguity remains around calendar slicing or selection guarantees.

## Scope

### In Scope

- `ContractSeriesSpec`
- `ContractSeries`
- `build_contract_series(...)`
- Switch detection helpers (`switch_mask`, `switch_sessions`, `switch_view`)
- CLI inspection script

### Out of Scope

- Synthetic asset weights
- Holdings
- Trades
- Roll blending logic
- P&L

## ContractSeries — Intended Semantics (Locked)

### 1. Identity Surface

For each session in `[start_session, end_session]` (inclusive):

- Exactly one `contract_id`
- Exactly one `period_id`
- No gaps
- No partial builds

### 2. Calendar Semantics

- `start_session` and `end_session` must exist exactly in the product trading calendar.
- Range is inclusive.
- Session index must be `datetime64[D]`.
- Empty series is forbidden.

### 3. Selection Semantics

For every session `t`:

```
engine.explain(product_id, t, rule)
```

must return:

```
outcome == "selected"
```

Otherwise:

- Hard failure (`RuntimeError`)
- Error message must include:
  - product_id
  - canonical rule id
  - session
  - outcome

No silent skipping. No partial success.

### 4. Switch Semantics

A contract switch is defined as:

```
contract_ids[t] != contract_ids[t-1]
```

Switch helpers must satisfy:

- `switch_mask()[0] == False`
- mask length == number of sessions
- `switch_sessions()` corresponds exactly to mask
- `switch_view()` shows `(session, from, to)` pairs

Switches are identity-level only.
They are NOT roll events.

## Implementation Tasks

### 1. Code Hygiene

- Remove duplicated length validation in `ContractSeries.__post_init__`.
- Ensure all validation errors are explicit and informative.
- Confirm dtype enforcement for `sessions`.

No change in logic; only tightening.

### 2. Test Suite (Required)

Create dedicated tests for `ContractSeries`.

#### A. Spec Validation

- `end_session < start_session` → ValueError
- Sessions coerced to `datetime64[D]`

#### B. Calendar Range Semantics

Using a small fake calendar:

- Exact inclusive slicing
- start not in calendar → ValueError
- end not in calendar → ValueError

#### C. Selection Hard-Fail

Using a fake engine:

- Non-"selected" outcome at any session → RuntimeError
- Error message contains required identifiers

#### D. Identity Path

- Stable contract path over multiple sessions
- Length consistency between sessions, contract_ids, period_ids

#### E. Switch Logic

- No switch when constant contract id
- Correct mask for one-switch case
- Correct `(from, to)` mapping in `switch_view`

#### F. Integration Test (Minimal)

Using a real product + real rule fixture:

- Build series over small known date range
- Confirm non-empty output
- Confirm at least one switch for a front-month rule (if expected)

## Inspection Script

Create:

```
scripts/synthetic_assets/ops/contract_series_inspect.py
```

### CLI Inputs

- `--product-id`
- `--rule-id` (canonical relative id)
- `--start-session`
- `--end-session`
- `--max-rows` (optional)

### Output

1. Header:
   - product_id
   - canonical_relative_id
   - short_rel_id
   - session count
   - first session / last session

2. First N rows:
   - session
   - contract_id
   - period_id

3. Switch summary:
   - number of switches
   - first N switch rows via `switch_view`

Script must:

- Fail loudly on selection failure
- Never silently truncate
- Be deterministic

## Invariants Checklist

The following must hold before Session 23 is declared complete:

- [ ] No partial builds possible.
- [ ] All sessions dtype = datetime64[D].
- [ ] Length consistency strictly enforced.
- [ ] Switch helpers tested and deterministic.
- [ ] Error messages contain product + rule + session.
- [ ] Integration test green.
- [ ] Inspect script operational.

## Definition of Done

Session 23 is complete when:

- All tests pass.
- ContractSeries behaviour is fully covered by unit tests.
- An operator can inspect a contract path via CLI.
- No ambiguity remains in identity semantics.

At this point, `ContractSeries` becomes a trusted foundation for:

- Session 24 — SyntheticAssetSpec
- Session 25 — Dynamic Weights
- Session 26 — Target Holdings

No further structural changes to `ContractSeries` are expected after Session 23.

## Strategic Significance

Closing `ContractSeries` marks the transition from:

- single timestamp contract selection

to:

- stable time-indexed identity modelling.

This provides the deterministic backbone required for:

- synthetic continuous contracts
- structured synthetic instruments
- controlled roll mechanics
- reproducible P&L attribution

It is the identity layer on which the entire synthetic asset stack depends.

# Session 25 – Weights Rules Parsing & WeightsSeries Realisation (No WR Registry)

Status: 🔜 Planned  
Scope: Implement parseable `weights_rule_id` grammar and deterministic realisation of time-indexed leg weights for SyntheticAssetSpecs, producing a persisted WeightsSeries dataset per asset.  
Out of scope: TargetHoldings construction and unit/size conversions (Session 26).

## 1. Objective

Session 25 implements the **dynamic weights layer** for synthetic assets.

Given a `SyntheticAssetSpec` (Session 24b), we will:

1. Define a **parseable, deterministic** `weights_rule_id` grammar.
2. Implement `parse_weights_rule_id(...) -> WeightsRuleSpec` to revive semantics from the id.
3. Realise **WeightsSeries** for each synthetic asset by:
   - building required `ContractSeries` for each leg role
   - using contract metadata (incl. last trading day) to compute time-indexed weights
4. Persist weights datasets and provide CLI inspection.

At completion:

> Every `SyntheticAssetSpec` in the registry can be realised into a deterministic `WeightsSeries` dataset solely from `weights_rule_id` and leg bindings (via ContractSeries).

## 2. In Scope / Not In Scope

### 2.1 In Scope
- `weights_rule_id` canonical grammar + parsing
- Weights computation for all V1 synthetic asset kinds (CONT / TS / PS)
- WeightsSeries dataset representation + persistence
- Ops scripts to build and inspect weights datasets
- Tests for determinism and invariants

### 2.2 Out of Scope (Session 26)
- TargetHoldings construction:
  - combining ContractSeries + WeightsSeries + unit/size conversions
- Execution / trade derivation / P&L

## 3. Inputs and Outputs

### 3.1 Inputs
- `SyntheticAssetSpec` registry (asset_id → spec YAML)
- `ContractSeries` realisation layer (Session 23)
- Refdata contract metadata (incl. last trading day) and calendars

### 3.2 Outputs
- WeightsSeries datasets per asset:
  - deterministic artefacts on disk
  - keyed by `asset_id`
  - indexed by trading session
  - columns = leg roles

## 4. Weights Rule Identity (No Registry)

### 4.1 WeightsRuleSpec model

Create:

```
mxm/v1/synthetic_assets/weights_rules.py
```

Minimal model:

```python
@dataclass(frozen=True, slots=True)
class WeightsRuleSpec:
    kind: Literal["ROLL_V1"]
    params: Mapping[str, JSONValue]
```

Notes:
- No persistence layer needed; the rule is revived from `weights_rule_id`.
- `weights_rule_id` is treated as a canonical encoding of `WeightsRuleSpec`.

### 4.2 Canonical grammar for weights_rule_id

Implement in the same module:

- `canonical_weights_rule_id(spec: WeightsRuleSpec) -> str`
- `parse_weights_rule_id(weights_rule_id: str) -> WeightsRuleSpec`

Proposed initial grammar (lock in session):

```
WR::KIND=ROLL_V1::ANCHOR=LTD::WINDOW=K::RAMP=LINEAR
```

V1 intent:
- anchor: last trading day of the active “cur” contract in each rolling pair
- window: number of sessions over which weights transition
- ramp: linear in V1

This single rule should be sufficient to support:
- CONT roll weights
- TS weights (via composition of two roll pairs)
- PS weights (via composition of two roll pairs)

## 5. WeightsSeries Dataset

### 5.1 Representation

Create:

```
mxm/v1/synthetic_assets/weights_series/models.py
```

Represent weights as:

- index: session (`np.datetime64[D]` or ISO day strings consistently)
- columns: leg roles (e.g. `cur`, `nxt`, `near_cur`, ...)
- values: float weights

Also persist metadata:

- asset_id
- canonical_id
- weights_rule_id
- start/end session coverage
- provenance (build timestamp, inputs summary)

### 5.2 Storage layout

Create:

```
mxm/v1/synthetic_assets/weights_series/store_layout.py
mxm/v1/synthetic_assets/weights_series/store.py
```

Suggested filesystem layout:

```
~/.mxm/synthetic_assets/weights_series/
  data/<asset_id>.parquet
  meta/<asset_id>.json
```

## 6. Weights Realisation Engine

Create:

```
mxm/v1/synthetic_assets/weights_series/realise.py
```

Core function:

```python
def build_weights_series(
    *,
    spec: SyntheticAssetSpec,
    calendars: TradingCalendarService,
    refdata: RefDataAPI,
    start_session: np.datetime64,
    end_session: np.datetime64,
) -> WeightsSeries:
    ...
```

Responsibilities:

1. Parse weights semantics:
   - `wr = parse_weights_rule_id(spec.weights_rule_id)`
2. For each leg role in `spec.legs`:
   - parse selector_rule_id → `SelectorRule`
   - build `ContractSeriesSpec`
   - realise `ContractSeries` for the session range
3. Using realised contract identities and refdata metadata (LTD), compute weights per role.

Important: weights engine must be deterministic and auditable.

## 7. Rule Semantics to Implement

The V1 synthetic assets include:

- CONT L1..L12 (rolling)
- TS Ln Ln+1
- fixed-month CONT
- PS spreads

Session 25 must compute weights for all of these.

### 7.1 CONT weights (rolling pair)

Given roles `(cur, nxt)` and a `ROLL_V1` rule:

- outside roll window:
  - w_cur=1, w_nxt=0
- within window (K sessions before LTD of cur):
  - α(t) increases from 0→1
  - w_cur=1-α(t), w_nxt=α(t)
- after LTD:
  - w_cur=0, w_nxt=1
  - (and the realised contract series should have advanced)

### 7.2 TS weights

TS is defined as two rolling pairs:

- near: (near_cur, near_nxt)
- far:  (far_cur,  far_nxt)

Compute two roll weight vectors using the same rule, then combine:

- near legs: +
- far legs:  −

The output is weights for the four roles.

### 7.3 PS weights

PS is defined as two rolling pairs on two products:

- A: (a_cur, a_nxt)
- B: (b_cur, b_nxt)

Compute roll weights on each side then combine:

- A legs: +
- B legs: −

Directionality is preserved by roles, and by the spec itself.

## 8. Ops Scripts

Create:

```
scripts/synthetic_assets/ops/build_weights_series.py
scripts/synthetic_assets/ops/inspect_weights_series.py
```

### build_weights_series.py

Responsibilities:

- Load specs from spec registry
- For each spec:
  - realise weights for a given session range
  - persist dataset
- flags:
  - --dry-run
  - --overwrite
  - --asset-id
  - --product-id
  - --start-session YYYY-MM-DD
  - --end-session YYYY-MM-DD
  - --registry-root overrides (spec and weights roots as needed)

### inspect_weights_series.py

Responsibilities:

- list assets with weights present
- load one dataset
- print summary:
  - coverage range
  - roles
  - simple invariants checks (sum, sign structure)

## 9. Testing Strategy

Unit tests:

1. `parse_weights_rule_id` roundtrip for canonical ids
2. CONT invariants:
   - weights in [0,1]
   - w_cur + w_nxt == 1 (within tolerance)
   - monotone transition during roll window
3. TS/PS invariants:
   - correct sign pattern per role grouping
   - deterministic output for repeated runs
4. Integration smoke:
   - build weights for one asset over a short date range using real refdata fixtures (or minimal test harness)

## 10. Completion Criteria

Session 25 complete when:

- [ ] Canonical `weights_rule_id` grammar locked + implemented parser
- [ ] WeightsSeries dataset format implemented + persisted
- [ ] Weights realiser builds weights from SyntheticAssetSpec + ContractSeries + refdata LTD
- [ ] Works for CONT / TS / PS in the current asset registry
- [ ] Ops build and inspect scripts working
- [ ] All tests green
- [ ] No Pyright errors

## 11. Post-Completion State

After Session 25 we will have:

- deterministic time-indexed weights for all synthetic assets
- weights datasets persisted and inspectable

Next (Session 26):

> Combine ContractSeries + WeightsSeries + unit/size conversions to produce TargetHoldings (and later trades / P&L).

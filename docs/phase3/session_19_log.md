# session_19_log.md — MXM V1  
## Session 19 — Relative Contract Labelling & Identifier Layer (Completed)

---

## Session intent

Session 19 introduced a **naming and identity layer** on top of the deterministic
contract selection engine completed in Session 18.

Session 18 resolved:

    (product_id, as_of_timestamp, selector_rule) -> contract_id

Session 19 defines and attaches:

    selector_rule -> canonical_relative_id
                   -> short_rel_id

The objective was to produce:

- **stable, machine-safe identifiers** describing selection intent,
- **ergonomic, human-readable labels** for CLI and inspection,
- without altering selection semantics or introducing refdata dependencies
  into the naming layer.

The selection engine remains logically unchanged.

## Conceptual separation (locked)

Session 19 formalised a clean separation between:

1. **Product universe structure** (refdata)
2. **Selection intent** (SelectorRule)
3. **Selection outcome** (contract_id)
4. **Label surfaces** (derived from SelectorRule only)

Crucially:

> Labels describe explicit rule intent only.  
> They never encode product universe structure implicitly.

For example, ES naturally lists only Mar/Jun/Sep/Dec contracts via refdata.
If the rule does not explicitly filter by cycle, the short label remains `L1`,
not a derived quarterly marker.

This preserves architectural layering.

## Canonical Relative Identifier (machine-safe)

### Grammar (V1, frozen)

```
RC::PT=<period_type>::CYCLE=<cycle_repr>::RANK=LTD::N=<n>
```

Where:

- `PT` = `PeriodType.name`
- `CYCLE` =
  - `NONE`, or
  - `<cycle_id>[<ordered elements>]`
- `RANK` = `LTD` (engine-locked in Session 18)
- `N` = 1-indexed selection depth

Examples:

- Front listed:
  ```
  RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1
  ```

- December-only:
  ```
  RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[12]::RANK=LTD::N=1
  ```

Properties:

- Deterministic
- Independent of product_id
- Independent of contract_id
- Independent of calendars
- Pure function of `SelectorRule`

Canonical IDs are suitable for:

- persistence
- portfolio configuration
- synthetic asset definitions
- cross-product aggregation
- audit logs

## Short Relative Identifier (human-readable)

### Design principle

Short labels encode **explicit filter state only**.

They do not infer structure from product listing constraints.

### Grammar (V1)

Let `n = rule.n`.

1. If `cycle_elements is None`:

   ```
   L{n}
   ```

   Meaning: *listed-universe rank*.

2. If `cycle_elements` has a single element:

   - For `CALENDAR_MONTHS`:
     ```
     Dec{n}, Mar{n}, ...
     ```
   - For other cycles:
     ```
     <CycleAbbrev><elem>-{n}
     ```

3. If `cycle_elements` has multiple elements:

   - For `CALENDAR_MONTHS`:
     ```
     M[3,6,9,12]{n}
     ```
   - For other cycles:
     ```
     <CycleAbbrev>[...]{n}
     ```

Ordering of elements follows cycle-rank (ascending integer order in V1).

Short labels are:

- Deterministic
- Context-dependent
- Not suitable for persistence
- Intended for CLI, logging, and chart legends

## Engine integration

`SelectionExplanation` was extended with two new fields:

```
canonical_relative_id: str
short_rel_id: str
```

These are now:

- Always populated
- Present on both success and failure paths
- Included in `to_dict()` for serialisation

The engine now computes labels once per `explain()` call and threads them
through all return paths.

No selection semantics were modified.

## Test coverage added

New tests assert that:

- Canonical IDs are stable and grammar-exact.
- Short IDs follow explicit-filter-only semantics.
- Labels are present on:
  - success
  - `NoEligibleContracts`
  - `RelativeContractUnavailable`
- Engine outputs remain deterministic.

All existing selection tests remain green.

## Behavioural example (REPL)

Example output:

```
selected_contract_id: cme_emini_snp500_futures.Mar-2026
canonical_relative_id: RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1
short_rel_id: L1
outcome: selected
failure_type: None
```

This demonstrates:

- Rule intent (front listed month)
- Deterministic identity surface
- Separation of selection logic from labelling

## Architectural impact

After Session 19:

- Relative contracts can be referenced by canonical ID in configuration.
- Synthetic asset construction can key on canonical IDs.
- Portfolio logic can aggregate by intent rather than contract string.
- CLI inspection surfaces gain ergonomic identifiers.
- Failure explanations remain self-identifying and audit-safe.

Session 19 completes the identity layer required before constructing:

- InstrumentSeries
- Rolling synthetic assets
- Multi-contract allocation surfaces

## Status

Session 19 is complete.

The contract selection engine now produces both:

- Deterministic contract identity
- Stable relative contract intent identifiers

without coupling naming semantics to refdata or engine logic.

Next step: InstrumentSeries construction (Session 20).

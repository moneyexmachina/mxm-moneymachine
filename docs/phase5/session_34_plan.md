# Session 33 — Performance Baseline and Profiling

## Objective

Establish a reliable performance baseline for the full synthetic-asset backtest
pipeline over a realistic historical range, and identify the dominant cost
centres for later optimisation.

This session is about **measurement and understanding**, not optimisation.

---

## Context

Session 31 repaired the broken upstream marketdata surface and restored the full
end-to-end pipeline:

    statistics_1d → daily_stats → backtest → pnl → plot

The system is now functionally correct and deterministic on the smoke range.
That makes this the right moment to test runtime behaviour on a realistic full
history.

---

## Core Question

The purpose of Session 33 is to answer:

> How slow is the full pipeline over a realistic history, and where exactly is
> the time going?

We want a clear answer before any optimisation work begins.

---

## Starting Assumption

Our starting assumption should be:

> The system is probably not yet "super fast", and the dominant cost is likely
> to sit in Python-level computation or repeated DataFrame work rather than in
> plotting.

More concretely, the most plausible bottlenecks are:

1. backtest session loop / per-session computation
2. repeated price access / lookup work
3. PnL construction over session and contract results
4. DataFrame slicing, copying, and aggregation overhead

Less likely, but still possible:

5. local parquet read performance
6. plotting / output formatting overhead

This is only a hypothesis. The session is designed to test it.

---

## Test Scope

We define the pipeline under measurement as:

1. daily_stats access
2. backtest simulation
3. PnL construction
4. output / plotting

The initial target workload should be:

- asset:
  
      cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1

- price field:
  
      settle_px

- date range:
  
      2010-07-01 → 2025-12-31

This range is long enough to expose any genuine performance problem.

---

## Execution Conditions

To keep the measurement interpretable, we should use:

- single-threaded baseline run
- warm local storage
- no forced resets
- no ingestion
- same code path as the normal smoke script, only with the wider date range

This gives us a clean first operational baseline.

---

## Measurement Strategy

## Phase 1 — Coarse Top-Level Timing

First, instrument the major pipeline phases with explicit wall-clock timing via
`time.perf_counter()`.

At minimum, time:

- total runtime
- backtest runtime
- pnl construction runtime
- plotting / output runtime

If daily_stats loading is a separate visible phase, time that too.

Example shape:

~~~python
t0 = time.perf_counter()
# whole run
...
print(f"[timing] total={time.perf_counter() - t0:.3f}s")
~~~

Goal:

> determine which major phase dominates total runtime

If one phase clearly dominates, that will guide the profiler interpretation.

---

## Phase 2 — Backtest Internal Timing

Inside the backtest path, add one further layer of timing if needed:

- total session-loop runtime
- optional timing of price-access path
- optional timing of holdings / execution update path

This should remain light-touch. The goal is not to fully instrument every
function yet, only to split the dominant backtest region into a few meaningful
subregions.

Goal:

> determine whether the main cost is data access, loop mechanics, or contract/session computation

---

## Phase 3 — Deterministic Profiler Run

Once coarse timing is in place, run a full deterministic profiler.

Recommended first tool:

- `cProfile`

Reason:

- built-in
- stable
- low setup friction
- good enough for first bottleneck identification

Example command shape:

~~~bash
python -m cProfile -o dev_perf/session_33_full_backtest.prof \
  scripts/pnl/smoke_synthetic_asset_pnl.py \
  --asset-id cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1 \
  --start 2010-07-01 \
  --end 2025-12-31 \
  --price-field settle_px
~~~

And then inspect with:

~~~python
import pstats

p = pstats.Stats("dev_perf/session_33_full_backtest.prof")
p.sort_stats("cumulative").print_stats(50)
~~~

Focus on:

- highest cumulative time
- highest total call counts
- repeated inner functions
- expensive DataFrame utilities
- price access or PnL-construction hotspots

Goal:

> identify the concrete hot functions, not just hot phases

---

## Phase 4 — Escalation Only If Needed

If `cProfile` identifies a clear hotspot, that is enough for Session 33.

Only if the result is ambiguous should we consider deeper tools such as:

- line-level profiling for one hot function
- sampling profiler
- allocation / copy inspection

This is explicitly optional.

---

## Interpretation Rules

We should distinguish carefully between:

### Acceptable baseline
A full run takes some time, but the dominant cost is obvious and not yet urgent.

### Borderline baseline
A full run is slow enough to matter, but still operationally usable for current work.

### Unacceptable baseline
A full run is clearly too slow for iteration, signalling that optimisation must become the next priority.

The session is successful once we can place the current system into one of these categories with evidence.

---

## What We Expect to Learn

By the end of Session 33, we should know:

1. total runtime for a full realistic run
2. time split by major pipeline phase
3. dominant internal hotspot(s)
4. whether performance work is urgent
5. what the most likely high-leverage optimisation path is

---

## Non-Goals

This session will not:

- optimise code
- redesign architecture
- introduce vectorisation
- add parallelism
- refactor the full backtest pipeline

All of that comes later, and only after measurement.

---

## Success Criteria

Session 33 is complete when we can answer all three questions:

1. How long does the full realistic run take?
2. Which phase dominates runtime?
3. Which function(s) dominate within that phase?

---

## Likely Follow-On

Depending on results, Session 33 may focus on one of:

- price-access performance
- backtest loop optimisation
- DataFrame copy / allocation reduction
- PnL constructor optimisation

That decision should be evidence-driven.

---

## Summary

Session 31 restored correctness and control.

Session 33 will establish the first real performance baseline for the full
pipeline and identify the dominant bottleneck before any optimisation begins.

# session_35_plan.md

## Session 35 — Articulating the Foundations: What It Takes to Produce a 15-Year Synthetic Asset Backtest

## Status

Planned

## Summary

Session 34 established a major architectural milestone:

> A fully functioning end-to-end pipeline producing a stable 15-year PnL series for synthetic assets, based on:
>
> - an internally defined business calendar
> - a curated, continuous mark-to-market surface (`daily_mark`)
> - explicit execution and PnL construction logic

Session 35 focuses on:

> **Articulating this achievement as a conceptual system**, through a formal MXM article.

This is not documentation of implementation details.

It is:

> A precise explanation of what it actually takes to construct a valid long-horizon backtest.

## Motivation

The common industry narrative assumes:

- time is given
- prices are complete
- execution is implicit

This leads to:

> backtests that appear well-defined but are in fact structurally underspecified.

The work of Session 33–34 demonstrates that:

- these assumptions do not hold
- and must be replaced with explicit system definitions

The article serves to:

- crystallise this insight
- communicate the MXM approach
- establish conceptual clarity for all subsequent system components

## Objective

Produce a first publication-quality article that:

1. Uses a **15-year synthetic asset PnL plot** as anchor
2. Demonstrates that such a plot is not trivial
3. Explains the **conceptual requirements** for making it well-defined
4. Introduces the MXM approach:
   - business calendar
   - mark surface
   - execution separation
5. Frames backtesting as a problem of:
   - defining time
   - defining valuation
   - defining execution

## Non-Goals

This session explicitly does **not** aim to:

- explain code or implementation details
- document dataset schemas
- provide a beginner tutorial on backtesting
- optimise performance or runtime

Those concerns are deferred to Session 36.

## Core Thesis (to refine during session)

> A long-term backtest is not primarily a statistical exercise, but an exercise in defining time, valuation, and execution consistently.

This thesis will be tested and sharpened during writing.

## Article Structure (Initial Draft)

### 1. Opening — The Illusion of Simplicity

- Introduce the idea of a 15-year cumulative PnL plot
- Highlight how trivial it appears
- State that this perception is misleading

### 2. The Naive Backtest

- Describe the implicit pipeline:
  - vendor data → returns → cumulative PnL
- Identify hidden assumptions

### 3. Where the Naive Model Breaks

#### 3.1 Time is not given

- calendars differ across venues
- missing days exist
- “what is a session?” is undefined

#### 3.2 Prices are not continuous

- missing settlements
- inconsistent marks
- vendor gaps

#### 3.3 Execution is implicit

- assumed fills
- no explicit execution model

### 4. Consequence

- backtest is not wrong, but undefined
- results depend on hidden assumptions

### 5. The MXM Approach

#### 5.1 Business Calendar

- defines decision-time domain
- independent of trading venues

#### 5.2 Mark Surface

- continuous valuation
- explicit gap handling
- deterministic construction

#### 5.3 Separation of Concerns

- time vs valuation vs execution
- explicit interfaces between layers

### 6. Result

- present the 15-year PnL plot
- optionally include:
  - outright synthetic asset
  - term-structure spread

Interpretation minimal.

### 7. Implications

- system is now internally coherent
- enables:
  - signals
  - risk models
  - portfolio construction

### 8. Closing

- restate thesis
- emphasise that:
  - the difficulty lies in defining the system, not computing the result

## Inputs Required

- cumulative PnL plots (outright + spread)
- basic metadata:
  - asset_id
  - date range
  - currency

No additional data preparation required.

## Deliverables

- first full draft in Markdown (mxm-core/docs/writing/)
- publication-ready `.qmd` version for Ghost pipeline
- associated plot assets saved in repository

## Open Questions

To be resolved during writing:

1. What is the exact framing of the central claim?
2. How strongly should the article critique existing practices?
3. How much system detail is necessary to establish credibility?
4. Should a diagram be included to illustrate:
   - vendor reality vs constructed reality?

## Success Criteria

Session 35 is successful if:

- the article clearly explains why a 15-year backtest is non-trivial
- the MXM approach is introduced at a conceptual level
- the piece stands on its own without requiring code inspection
- the result feels aligned with MXM writing style:
  - precise
  - minimal
  - structurally clear

## Next Session

Session 36:

- performance profiling and optimisation of:
  - synthetic asset construction
  - backtesting pipeline

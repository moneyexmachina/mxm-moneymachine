"""
Contract interpretation and selection semantics for MXM V1.

This module defines the **authoritative contract-layer abstractions** used by MXM
to reason about futures contracts *as contracts*, independent of pricing,
holdings, or synthetic asset construction.

Scope
-----
The contracts module is responsible for:

- interpreting futures contracts relative to a trading calendar
- defining eligibility rules for contracts on a given trading day
- providing deterministic, rule-based resolution of *relative contracts*
  (e.g. M1, M2, Dec1) into concrete contract identifiers
- exposing stable, testable selection semantics that downstream layers
  (synthetics, rolls, holdings) can rely on without ambiguity

This layer answers questions of the form:

    "Which concrete contract does this selector refer to on this trading day?"

but it does **not** answer:

    "What is the price of that contract?"
    "How is exposure rolled or interpolated?"
    "What position or weight should be held?"

Non-goals
---------
The following concerns are explicitly out of scope for this module:

- pricing, NAV, or P&L computation
- roll logic or roll interpolation
- synthetic asset definitions or weighting schemes
- portfolio construction or strategy logic
- data ingestion, persistence, or caching

Layering and dependencies
-------------------------
This module depends on:

- reference data (contract metadata such as contract month and last trading day)
- trading calendars (observed or projected)

It does not own or mutate either.

All functionality in this module is defined as **pure, deterministic functions**
of:
- reference data
- trading calendars
- explicit input arguments

No internal caching, I/O, or side effects are permitted.

Position in the MXM architecture
--------------------------------
The contracts module sits:

- above raw reference data and calendars
- below synthetic asset construction and holdings materialisation

It forms the semantic bridge between *what contracts exist* and *how those
contracts are interpreted* in time.

In future iterations, this module is expected to migrate into a dedicated
synthetic/contract-interpretation package (e.g. ``mxm-synthetics``), but its
responsibilities and semantics are locked for MXM V1.
"""

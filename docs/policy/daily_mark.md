# daily_mark — Normative Dataset Specification

## Purpose

`daily_mark` is a policy-driven, curated MXM dataset that provides one authoritative
daily valuation mark for each `(contract_id, session)` pair, where `session` is an
MXM business session.

The dataset is intended for downstream economic use, including:
- mark-to-market valuation
- daily PnL construction
- backtesting
- attribution and reporting

`daily_mark` does not aim to reproduce any single upstream vendor dataset faithfully.
Instead, it expresses MXM's internal judgement of the best available daily mark for
valuation on each MXM business session, under an explicit and deterministic policy.

## Calendar Basis

`daily_mark` is indexed on the MXM business calendar.

Rows are defined for MXM business sessions, not for exchange trading sessions.
Upstream source data may originate on other calendar surfaces and must be mapped into
the MXM business-session domain during dataset construction.

## Primary Key

- `contract_id`
- `session`

where:
- `contract_id` identifies the futures contract
- `session` is the MXM business session label

## Economic Semantics

A `daily_mark` row represents MXM's authoritative valuation mark for the contract
associated with the close of the given MXM business session.

The row answers the question:

> What daily mark does MXM assign to this contract for valuation on this business session?

## Construction Principle

`daily_mark` is constructed by applying a deterministic mark-selection policy over
available upstream market data and previously constructed `daily_mark` values.

The initial v1 construction policy is:

1. If an acceptable same-session settlement-derived mark is available, use it.
2. Else if an acceptable same-session close-derived mark is available, use it.
3. Else if a prior authoritative `daily_mark` exists, carry it forward.
4. Else no mark is available for that session.

This policy is applied independently per `contract_id`, in ascending session order.

## Authoritative Mark

Each row contains a single authoritative mark value, referred to here normatively as
the dataset's valuation mark.

This mark is the value that downstream valuation and PnL systems are expected to use.

Downstream systems must not re-implement mark fallback logic independently when
consuming `daily_mark`.

## Provenance and Quality

`daily_mark` must record metadata describing:
- how the mark was obtained
- the source class of the mark
- the quality class of the mark
- whether the mark was carried forward
- enough lineage information to audit the derivation path

This metadata must be flexible enough to support future multiple-source mark
construction and must not assume a single permanent raw field structure such as
`px_settle_observed`.

## Initial Mark Source Hierarchy (v1)

The initial v1 hierarchy is:

- same-session settle-derived mark
- same-session close-derived mark
- carried-forward prior authoritative mark

The exact upstream dataset and field mappings used to realise these categories are
an implementation detail of the v1 builder, not the permanent semantic definition of
the dataset.

## Mark Availability

A `daily_mark` row should exist for each `(contract_id, MXM business session)` in the
constructed range.

However, the authoritative mark value itself may be unavailable before the first valid
markable observation has been obtained for that contract.

Therefore, row existence is total over the build domain, but mark availability need not
be total from the first session onward.

## Determinism

Construction of `daily_mark` must be deterministic given:
- the MXM business calendar
- the relevant upstream source datasets
- the configured mark-selection policy

Repeated builds over unchanged inputs must yield identical outputs.

## Intended Downstream Contract

`daily_mark` is the canonical daily valuation surface for session-based downstream
economic processes in MXM.

Any component requiring a daily contract mark on MXM business sessions should consume
`daily_mark` rather than directly querying raw or source-near datasets.

## Non-Goals (v1)

`daily_mark` v1 does not attempt to:
- reconstruct perfect economic truth
- reconcile multiple vendors
- estimate model-based fair marks
- interpolate missing marks statistically
- represent full market state beyond daily valuation marks

Its scope is limited to deterministic construction of a robust daily valuation mark
surface for MXM business sessions.

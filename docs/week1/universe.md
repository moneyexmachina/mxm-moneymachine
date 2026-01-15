# Week 1 — Universe, Reference Data, and Market Data

## Purpose of Week 1
Establish a concrete, inspectable trading universe and prove that reliable
historical daily price data can be loaded, stored idempotently, and inspected.
This week is about facts on disk and trust in inputs, not models or signals.

## Week 1 Success Condition
“I can load prices for any contract on any historical date and trust them.”

### Monday
- **09:00 – 12:30**  
  Repo setup checkpoint, refdata recall, first proof scripts.
- **13:00 – 15:00**  
  Databento onboarding, API smoke tests, instrument metadata exploration.

### Tuesday
- **09:00 – 12:30**  
  Single-instrument OHLCV backfill, persistence, idempotency proof.

### Wednesday
- **09:00 – 12:30**  
  Product-chain backfill (multiple contracts), coverage and health reporting.
- **14:00 – 17:30**  
  Resolve bottlenecks (vendor mapping vs refdata coverage); extend universe or
  mapping layer as needed.

### Thursday
- **09:00 – 12:20**  
  Freeze Week 1 universe; dry-run backfill for 2–3 products.
- **15:00 – 17:30**  
  Lock idempotency and caching policy; cost controls and safe re-runs.

### Friday
- **09:00 – 12:30**  
  End-to-end demo, consolidate Week 1 artefacts, prepare accountability bundle.

## Initial Futures Universe (Draft)
(10–20 products; mark status per product.)
- Product A — refdata-ready / mapping-ready / data-backfilled
- Product B — needs contract specs
- Product C — mapping pending
- …

(List products, even if incomplete, with status flags.)

## Week 1 Execution Plan (Ordered)
1. Create Week 1 docs scaffold and anchor this plan.
2. Verify existing `mxm-refdata` capabilities with CLI proofs.
3. Create Databento account and store API key via `mxm-secrets`.
4. Perform Databento metadata smoke tests and identifier mapping.
5. Backfill daily OHLCV for one instrument; prove idempotency.
6. Backfill a product chain; generate coverage/health report.
7. Freeze the Week 1 universe and document status.
8. Demonstrate safe re-runs with caching and cost controls.
9. Run an end-to-end proof and capture outputs.

(A short, ordered list of what must happen this week.)

## Expected Artefacts
- `docs/week1/universe.md` (this document)
- `docs/week1/refdata_proofs.md`
- `docs/week1/databento_notes.md`
- `docs/week1/data_health.md`
- Persisted OHLCV data for instruments in scope

## Explicit Non-Goals for Week 1
- No signals, risk models, or portfolio logic
- No pipelines or orchestration frameworks
- No visual dashboards beyond simple CLI outputs
- No expansion to 120+ products
- No execution or trading logic

# Session 31 — statistics_1d repair and pipeline unblock

## Objective
Repair incomplete statistics_1d coverage for Mar-2025 contract and restore
end-to-end PnL pipeline.

## Findings
- daily_stats surface contained only 3 rows for Mar-2025
- upstream statistics_1d contained only 975 rows over expiry window
- vendor dataset range was valid → issue local or cache-side

## Implementation
- added contract_id filter to statistics_1d orchestrator
- implemented force_reset:
  - delete local parquet
  - bypass DataIO cache (CacheMode.BYPASS)
  - preserve attempts_store

- propagated same pattern to daily_stats orchestrator

## Repair
- re-ingested statistics_1d for instrument_id=5002
  → 94,562 rows (2022-12-16 → 2025-03-21)

- rebuilt daily_stats
  → 612 rows (2022-12-15 → 2025-03-21)

## Result
- backtest executes successfully
- PnL constructed and plotted
- pipeline unblocked

## Conclusion
Failure caused by stale partial local/cache surface, not mapping or logic error.
System now supports targeted repair via contract-scoped orchestration and force_reset.

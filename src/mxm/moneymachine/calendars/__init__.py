"""
MXM V1 — Trading Calendars

This package provides the authoritative trading-day calendar infrastructure
for MXM V1.

Calendars in MXM are treated as **reference data**, not executable logic.
They are generated offline from an upstream source, persisted as immutable
artifacts under the user's refdata directory, and loaded read-only at runtime.

The runtime API operates exclusively on pre-materialised trading-day arrays
and never depends on upstream calendar packages or recomputation.

Core responsibilities:
- loading validated calendar artifacts from refdata
- providing deterministic trading-day arithmetic
- supporting roll-window and last-trading-day computations
- enabling reconciliation against observed OHLCV-1D availability

Design principles:
- calendars are data, not code paths
- observed data is authoritative where available
- projected data is explicit, versioned, and strictly weaker
- all semantics are deterministic and auditable

This package does **not** model:
- intraday session structure
- early closes or partial trading days
- ad-hoc market disruptions
- product-specific session overrides

Those concerns are intentionally deferred beyond MXM V1.

Public API:
- TradingCalendar
- load_calendar

All calendar construction, refresh, and inspection logic is internal to this
package and accessed via explicit operational workflows, not runtime imports.
"""

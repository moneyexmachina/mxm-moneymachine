from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import databento as db


@dataclass(frozen=True)
class CostEstimate:
    estimated_cost_usd: float
    billable_size: int | None = None


def _normalize_symbols(symbols: str | Sequence[str]) -> list[str]:
    if isinstance(symbols, str):
        return [symbols]
    return list(symbols)


def _parse_cost_response(res: Any) -> CostEstimate:
    """
    Databento client versions differ:
    - some return a float (estimated cost)
    - some return a mapping/object with fields like estimated_cost, billable_size
    """
    if isinstance(res, (float, int)):
        return CostEstimate(
            estimated_cost_usd=float(res),
            billable_size=None,
        )

    # Deliberately brittle fallback for dict-like returns
    estimated_cost = float(res["estimated_cost"])
    billable_size = res.get("billable_size")
    return CostEstimate(
        estimated_cost_usd=estimated_cost,
        billable_size=billable_size,
    )


def estimate_cost_timeseries(
    *,
    client: db.Historical,
    dataset: str,
    schema: str,
    symbols: str | Sequence[str],
    stype_in: str = "raw_symbol",
    start: str,
    end: str,
) -> CostEstimate:
    """
    Generic Databento cost estimator for timeseries.get_range(...) calls.

    This is an operational safety mechanism and MUST be called before any
    Databento pull (even when DataIO caching is in place).

    Parameters must match the eventual pull request exactly.
    """
    symbols_list = _normalize_symbols(symbols)

    res = client.metadata.get_cost(
        dataset=dataset,
        schema=schema,
        symbols=symbols_list,
        stype_in=stype_in,
        start=start,
        end=end,
    )

    return _parse_cost_response(res)


def estimate_cost_ohlcv_1d(
    *,
    client: db.Historical,
    dataset: str,
    symbols: str | Sequence[str],
    stype_in: str = "raw_symbol",
    start: str,
    end: str,
) -> CostEstimate:
    """
    Estimate Databento cost for an ohlcv-1d daily bars query.
    """
    return estimate_cost_timeseries(
        client=client,
        dataset=dataset,
        schema="ohlcv-1d",
        symbols=symbols,
        stype_in=stype_in,
        start=start,
        end=end,
    )


def estimate_cost_instrument_definition(
    *,
    client: db.Historical,
    dataset: str,
    symbols: str | Sequence[str],
    stype_in: str = "raw_symbol",
    start: str,
    end: str,
) -> CostEstimate:
    """
    Estimate Databento cost for instrument definition events (schema="definition").

    Note:
    - Costs are typically very small per product, but historical replays
      must still be cost-gated.
    """
    return estimate_cost_timeseries(
        client=client,
        dataset=dataset,
        schema="definition",
        symbols=symbols,
        stype_in=stype_in,
        start=start,
        end=end,
    )


def enforce_cost_cap(*, estimated_cost_usd: float, cap_usd: float) -> None:
    if estimated_cost_usd > cap_usd:
        raise RuntimeError(
            f"Databento cost estimate {estimated_cost_usd:.6f} USD "
            f"exceeds cap {cap_usd:.6f} USD. Aborting pull."
        )

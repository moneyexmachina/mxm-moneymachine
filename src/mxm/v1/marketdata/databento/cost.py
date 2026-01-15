from __future__ import annotations

from dataclasses import dataclass

import databento as db


@dataclass(frozen=True)
class CostEstimate:
    estimated_cost_usd: float
    billable_size: int | None = None


def estimate_cost_ohlcv_1d(
    *,
    client: db.Historical,
    dataset: str,
    symbols: list[str] | str,
    stype_in: str = "raw_symbol",
    start: str,
    end: str,
) -> CostEstimate:
    """
    Estimate Databento cost for a daily bar query.

    This is an operational safety mechanism. It must be called before a pull.
    """
    symbols_list = [symbols] if isinstance(symbols, str) else symbols

    # Databento metadata cost call
    res = client.metadata.get_cost(
        dataset=dataset,
        schema="ohlcv-1d",
        symbols=symbols_list,
        stype_in=stype_in,
        start=start,
        end=end,
    )
    # Databento client versions differ:
    # - some return a float (estimated cost)
    # - some return a mapping/object with fields like estimated_cost, billable_size
    if isinstance(res, (float, int)):
        return CostEstimate(estimated_cost_usd=float(res), billable_size=None)

    # Deliberately brittle fallback for dict-like returns
    estimated_cost = float(res["estimated_cost"])
    billable_size = res.get("billable_size")
    return CostEstimate(estimated_cost_usd=estimated_cost, billable_size=billable_size)


def enforce_cost_cap(*, estimated_cost_usd: float, cap_usd: float) -> None:
    if estimated_cost_usd > cap_usd:
        raise RuntimeError(
            f"Databento cost estimate {estimated_cost_usd:.6f} USD exceeds cap {cap_usd:.6f} USD. Aborting pull."
        )

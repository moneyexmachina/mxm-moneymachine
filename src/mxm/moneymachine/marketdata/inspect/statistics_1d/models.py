from __future__ import annotations

from dataclasses import dataclass

from mxm.moneymachine.marketdata.inspect.models import AttemptSummary


@dataclass(frozen=True)
class Statistics1DContractAttempt:
    product_id: str
    contract_id: str
    contract_key: str

    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None

    last_attempt: AttemptSummary

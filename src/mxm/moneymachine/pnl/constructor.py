"""
PnL constructor for mxm-moneymachine.

This module converts an ordered sequence of SessionResult objects into a
canonical PnLSeries.

The constructor is intentionally agnostic to the source of the
SessionResult sequence. The sequence may arise from historical backtests,
paper-trading runs, live execution journals, or other multi-session
SessionEngine workflows.

For each session, the constructor computes contract-level economic PnL
and then explicitly aggregates that detail into session totals.

The implemented decomposition is:

    price_move_pnl
        mark-to-market change of holdings carried into the session

    trade_pnl
        execution-quality effect of realised trades relative to the
        session mark

Contract-level PnL is scaled by authoritative contract size from
reference data.

PnL is constructed in a specified target currency.

Session 29 scope
----------------
Session 29 currently supports only the same-currency case:

    contract_currency == target_currency

Cross-currency PnL construction and FX attribution are intentionally
deferred. The FX hook is present in the constructor boundary so that full
translation can be introduced later without changing the public API.

Design notes
------------
- contract-level PnL is the canonical computational grain
- session totals are explicit aggregations over contract-level rows
- first-session price-move PnL is defined as zero because no in-horizon
  prior mark exists
- missing marks, fill prices, and refdata lookups fail loudly
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from mxm.moneymachine.execution.contract_bundles import ContractBundle
from mxm.moneymachine.execution.executor import ExecutionResult
from mxm.moneymachine.execution.price_accessors import MarkPriceAccessor
from mxm.moneymachine.execution.session_engine import SessionResult
from mxm.moneymachine.fx.spot_fx_converter import SpotFXConverter
from mxm.moneymachine.pnl.models import ContractPnL, PnLSeries, SessionPnL
from mxm.refdata.api.ref_data_api import RefDataAPI


def build_pnl_series(
    *,
    session_results: Sequence[SessionResult],
    mark_price_accessor: MarkPriceAccessor,
    spot_fx_converter: SpotFXConverter,
    ref_data_api: RefDataAPI,
    target_currency: str,
) -> PnLSeries:
    """
    Build a canonical PnLSeries from an ordered SessionResult sequence.

    Parameters
    ----------
    session_results:
        Ordered realised session-state transitions.

    mark_price_accessor:
        Accessor used to resolve the session mark price for each contract.

    spot_fx_converter:
        FX conversion surface used to express PnL in target currency.

        Session 29 note:
            This is currently only exercised structurally. Same-currency
            construction returns an FX multiplier of 1.0; cross-currency
            construction raises NotImplementedError.

    ref_data_api:
        Reference-data API used to resolve contract metadata such as
        contract size and contract currency.

    target_currency:
        Currency in which the resulting PnL should be expressed.

    Returns
    -------
    PnLSeries
        Ordered session-level PnL series with contract-level detail
        preserved within each SessionPnL.
    """
    session_pnls: list[SessionPnL] = []

    for session_result in session_results:
        session_pnls.append(
            _build_session_pnl(
                session_result=session_result,
                mark_price_accessor=mark_price_accessor,
                spot_fx_converter=spot_fx_converter,
                ref_data_api=ref_data_api,
                target_currency=target_currency,
            )
        )

    return PnLSeries(session_pnls=tuple(session_pnls))


def _build_session_pnl(
    *,
    session_result: SessionResult,
    mark_price_accessor: MarkPriceAccessor,
    spot_fx_converter: SpotFXConverter,
    ref_data_api: RefDataAPI,
    target_currency: str,
) -> SessionPnL:
    """
    Build one SessionPnL from one SessionResult.
    """
    contract_ids = _collect_relevant_contract_ids(session_result=session_result)

    contract_pnls: list[ContractPnL] = []
    for contract_id in contract_ids:
        contract_pnls.append(
            _build_contract_pnl(
                contract_id=contract_id,
                session_result=session_result,
                mark_price_accessor=mark_price_accessor,
                spot_fx_converter=spot_fx_converter,
                ref_data_api=ref_data_api,
                target_currency=target_currency,
            )
        )

    price_move_total = sum(cp.price_move_pnl for cp in contract_pnls)
    trade_total = sum(cp.trade_pnl for cp in contract_pnls)
    total = sum(cp.total_pnl for cp in contract_pnls)

    return SessionPnL(
        previous_session=session_result.previous_session,
        session=session_result.session,
        contract_pnls=tuple(contract_pnls),
        price_move_pnl=price_move_total,
        trade_pnl=trade_total,
        total_pnl=total,
    )


def _collect_relevant_contract_ids(
    *,
    session_result: SessionResult,
) -> list[str]:
    """
    Collect the contracts that can contribute PnL in this session.

    A contract is relevant if it appears in either:

    - initial holdings carried into the session
    - realised trades executed during the session
    """
    initial_ids = set(session_result.initial_holdings.contract_ids)
    trade_ids = set(session_result.execution_result.realised_trades.contract_ids)

    return sorted(initial_ids.union(trade_ids))


def _build_contract_pnl(
    *,
    contract_id: str,
    session_result: SessionResult,
    mark_price_accessor: MarkPriceAccessor,
    spot_fx_converter: SpotFXConverter,
    ref_data_api: RefDataAPI,
    target_currency: str,
) -> ContractPnL:
    """
    Build one ContractPnL for one contract in one session.
    """
    initial_quantity = _bundle_quantity(
        bundle=session_result.initial_holdings,
        contract_id=contract_id,
    )
    trade_quantity = _bundle_quantity(
        bundle=session_result.execution_result.realised_trades,
        contract_id=contract_id,
    )

    contract_multiplier = _get_contract_multiplier(
        contract_id=contract_id,
        ref_data_api=ref_data_api,
    )
    fx_multiplier = _get_fx_multiplier(
        contract_id=contract_id,
        session=session_result.session,
        target_currency=target_currency,
        ref_data_api=ref_data_api,
        spot_fx_converter=spot_fx_converter,
    )

    price_move_pnl = _compute_contract_price_move_pnl(
        contract_id=contract_id,
        previous_session=session_result.previous_session,
        session=session_result.session,
        initial_quantity=initial_quantity,
        contract_multiplier=contract_multiplier,
        fx_multiplier=fx_multiplier,
        mark_price_accessor=mark_price_accessor,
    )
    trade_pnl = _compute_contract_trade_pnl(
        contract_id=contract_id,
        session=session_result.session,
        trade_quantity=trade_quantity,
        contract_multiplier=contract_multiplier,
        fx_multiplier=fx_multiplier,
        execution_result=session_result.execution_result,
        mark_price_accessor=mark_price_accessor,
    )

    return ContractPnL(
        contract_id=contract_id,
        price_move_pnl=price_move_pnl,
        trade_pnl=trade_pnl,
        total_pnl=price_move_pnl + trade_pnl,
    )


def _compute_contract_price_move_pnl(
    *,
    contract_id: str,
    previous_session: np.datetime64 | None,
    session: np.datetime64,
    initial_quantity: int,
    contract_multiplier: float,
    fx_multiplier: float,
    mark_price_accessor: MarkPriceAccessor,
) -> float:
    """
    Compute price-move PnL for one contract.

    Price-move PnL is computed on the quantity carried into the session.
    """
    if previous_session is None:
        return 0.0

    if initial_quantity == 0:
        return 0.0

    previous_mark = mark_price_accessor.get_mark_price(
        contract_id=contract_id,
        session=previous_session,
    )
    current_mark = mark_price_accessor.get_mark_price(
        contract_id=contract_id,
        session=session,
    )

    return float(
        initial_quantity
        * contract_multiplier
        * fx_multiplier
        * (current_mark - previous_mark)
    )


def _compute_contract_trade_pnl(
    *,
    contract_id: str,
    session: np.datetime64,
    trade_quantity: int,
    contract_multiplier: float,
    fx_multiplier: float,
    execution_result: ExecutionResult,
    mark_price_accessor: MarkPriceAccessor,
) -> float:
    """
    Compute trade PnL for one contract.

    Trade PnL is computed on realised trades during the session, relative
    to the session mark.
    """
    if trade_quantity == 0:
        return 0.0

    fill_price = _get_fill_price(
        fill_prices=execution_result.fill_prices,
        contract_id=contract_id,
    )
    current_mark = mark_price_accessor.get_mark_price(
        contract_id=contract_id,
        session=session,
    )

    return float(
        trade_quantity
        * contract_multiplier
        * fx_multiplier
        * (current_mark - fill_price)
    )


def _bundle_quantity(
    *,
    bundle: ContractBundle,
    contract_id: str,
) -> int:
    """
    Return the signed lot quantity for one contract from a ContractBundle.

    Missing contract_id implies zero by ContractBundle semantics.
    """
    quantities = bundle.quantities

    if contract_id not in quantities.index:
        return 0

    return int(quantities.loc[contract_id])


def _get_fill_price(
    *,
    fill_prices: pd.Series,
    contract_id: str,
) -> float:
    """
    Return the fill price for one traded contract.

    Raises
    ------
    ValueError
        If a traded contract does not have a corresponding fill price.
    """
    try:
        value = fill_prices.loc[contract_id]
    except KeyError as exc:
        raise ValueError(
            "Missing fill price for traded contract in ExecutionResult.fill_prices: "
            f"{contract_id!r}"
        ) from exc

    return float(value)


def _get_contract_multiplier(
    *,
    contract_id: str,
    ref_data_api: RefDataAPI,
) -> float:
    """
    Return the authoritative economic size of the contract.
    """
    contract = ref_data_api.get_contract_by_id(contract_id)

    return float(contract.contract_size)


def _get_fx_multiplier(
    *,
    contract_id: str,
    session: np.datetime64,
    target_currency: str,
    ref_data_api: RefDataAPI,
    spot_fx_converter: SpotFXConverter,
) -> float:
    """
    Return the FX multiplier used to express PnL in target currency.

    Session 29 currently supports only the same-currency case.

    Parameters
    ----------
    contract_id:
        Contract whose native currency is to be resolved.

    session:
        Session at which the FX multiplier would apply.

    target_currency:
        Currency in which PnL should be expressed.

    Returns
    -------
    float
        FX multiplier for target-currency construction.

    Raises
    ------
    NotImplementedError
        If contract currency differs from target currency.
    """
    currency = ref_data_api.get_contract_by_id(contract_id).currency
    return float(
        spot_fx_converter.get_fx_multiplier(
            from_currency=currency,
            to_currency=target_currency,
            session=session,
        )
    )

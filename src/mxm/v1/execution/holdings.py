"""
MXM V1 — Holdings transition helpers.

This module contains pure functions operating on holdings-like execution
state.

At the current stage of the execution design, holdings and realised
trades are represented by the generic realised / executable bundle
carrier:

    ContractBundle

rather than by separate nominal classes.

This is intentional.

The distinctions between:

    realised_holdings
    initial_holdings
    realised_trades

are currently treated as semantic role distinctions, not type
distinctions. All obey the same underlying invariant regime:

    contract_id -> signed integer lots

and therefore all are represented as ContractBundle objects.

The two primary holdings-side transitions captured here are:

    realised_holdings(t-1)
        ↓ validation / housekeeping / preparation
    initial_holdings(t)

and

    initial_holdings(t) + realised_trades(t)
        ↓
    realised_holdings(t)

In Session 28, the preparation step performs a minimal lifecycle check:
it raises an error if any carried holding refers to a contract that is on
or beyond its last trading day at the current session.

All functions in this module are pure:
they take bundle objects and reference inputs as arguments, and return
new bundle objects without mutating state.
"""

from __future__ import annotations

import numpy as np

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.execution.contract_bundles import ContractBundle


def prepare_initial_holdings(
    realised_holdings: ContractBundle,
    session: np.datetime64,
    ref_data_api: RefDataAPI,
) -> ContractBundle:
    """
    Prepare decision-ready initial holdings from prior realised holdings.

    This function makes explicit the transition:

        realised_holdings(t-1) -> initial_holdings(t)

    In the current Session-28 implementation, preparation performs a
    minimal validity check against contract lifecycle:

    - every held contract must exist in refdata
    - every held contract must have a last trading day
    - no held contract may be on or beyond its last trading day at the
      current session

    If an invalid carried holding is found, a ValueError is raised.

    Parameters
    ----------
    realised_holdings:
        The authoritative realised contract inventory from the previous
        execution state.

    session:
        The current trading session for which decision-ready initial
        holdings are being prepared.

    ref_data_api:
        Reference-data API used to resolve contract lifecycle metadata.

    Returns
    -------
    ContractBundle
        The decision-ready initial holdings bundle.

    Raises
    ------
    ValueError
        If a held contract is missing refdata, is missing a
        last_trading_day, or is on or beyond its last trading day at the
        current session.
    """
    held_contract_ids = realised_holdings.contract_ids

    if len(held_contract_ids) == 0:
        return ContractBundle.empty()

    session_date = session.astype("datetime64[D]").item()

    invalid_contract_ids: list[str] = []

    for contract_id in held_contract_ids:
        contract = ref_data_api.get_contract_by_id(contract_id)

        if contract is None:
            raise ValueError(
                "prepare_initial_holdings() could not resolve held contract "
                f"in refdata: {contract_id!r}"
            )

        last_trading_day = contract.last_trading_day
        if session_date >= last_trading_day:
            invalid_contract_ids.append(contract_id)

    if invalid_contract_ids:
        raise ValueError(
            "prepare_initial_holdings() found holdings in contracts on or "
            "beyond last trading day at session "
            f"{session!r}: {invalid_contract_ids!r}"
        )

    return ContractBundle(realised_holdings.quantities)


def apply_realised_trades(
    initial_holdings: ContractBundle,
    realised_trades: ContractBundle,
) -> ContractBundle:
    """
    Apply realised trades to initial holdings to produce realised holdings.

    This function makes explicit the state update:

        initial_holdings(t) + realised_trades(t) -> realised_holdings(t)

    Parameters
    ----------
    initial_holdings:
        Decision-ready holdings entering the execution step.

    realised_trades:
        Realised executed trade quantities for the step.

    Returns
    -------
    ContractBundle
        The realised holdings after applying realised trades.
    """
    return initial_holdings + realised_trades

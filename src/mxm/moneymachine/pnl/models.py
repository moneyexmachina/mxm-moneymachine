"""
mxm.v1.pnl.models

Canonical PnL result models for MXM V1.

This module defines the core data structures used to represent economic
profit-and-loss results produced by MXM backtests.

These objects represent the economic consequences of execution outcomes.
They are constructed from ordered SessionResult chains and provide a
deterministic representation of realised economic performance.

Conceptual Position in the Architecture
---------------------------------------

The PnL layer sits above the execution layer.

Execution determines:

    - holdings entering a session
    - trades executed during the session
    - fill prices of those trades
    - holdings after execution

The PnL layer converts those state transitions into economic results by
comparing mark-to-market values across sessions.

The output is a sequence of session-level PnL observations, with
contract-level detail preserved as the canonical computational grain.
Session totals are explicit aggregations over contract-level PnL rows.

PnL Decomposition
-----------------

Session PnL is decomposed into two components:

1. Price-Move PnL

   PnL resulting from the mark-to-market change of positions carried into
   the session.

       price_move_pnl =
           initial_holdings x contract_multiplier x (mark_t - mark_{t-1})

2. Trade PnL

   PnL resulting from executing trades at prices different from the
   session mark.

       trade_pnl =
           realised_trades x contract_multiplier x (mark_t - fill_price)

Total PnL is defined as:

    total_pnl = price_move_pnl + trade_pnl

This decomposition isolates the economic effects of:

    - exposure during the session
    - execution quality relative to the session mark

Economic Scaling
----------------

PnL calculations must include the economic size of each contract.

Each contract-level contribution is scaled by:

    quantity x contract_multiplier x price_change

Contract multipliers are obtained from reference data.

Currency Assumptions (Session 29)
---------------------------------

For the first implementation (Session 29), PnL construction assumes that
contract currency is identical to the target currency.

Under this assumption:

    fx_multiplier = 1.0

If contract currency differs from target currency, the PnL constructor
will currently raise an error.

Full FX translation support will be implemented in a later session.

TODO — FX Mark-to-Market Attribution
------------------------------------

When contract currency differs from the target or reporting currency,
PnL must account for FX movements between sessions.

The economically correct target-currency value of a position is:

    V_t = quantity x contract_multiplier x price_t x fx_rate_t

Therefore the true target-currency PnL across a session is:

    PnL = V_t - V_{t-1}
        = quantity x multiplier x (price_t x fx_t - price_{t-1} x fx_{t-1})

This differs from simply translating native-currency PnL using a single
end-of-period FX rate.

Future implementations should therefore compute PnL using value
differences in the target currency rather than translating native PnL.

Once FX translation is introduced, target-currency PnL can be further
decomposed into:

    - native price movement
    - FX movement
    - price-FX interaction term

For example:

    Δ(price x fx)
        = Δprice x fx_{t-1}
        + price_{t-1} x Δfx
        + Δprice x Δfx

Proper attribution will require FX marks at both session boundaries and,
for trade attribution, potentially FX rates at fill time.

This functionality is intentionally deferred beyond Session 29 in order
to keep the first PnL implementation focused and deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ContractPnL:
    """
    Economic PnL contribution of one contract in one session.

    Parameters
    ----------
    contract_id
        Contract identifier for this contract-level PnL row.

    price_move_pnl
        PnL caused by the mark-to-market change of the quantity carried
        into the session.

    trade_pnl
        PnL caused by executing trades in this contract at prices
        different from the session mark.

    total_pnl
        Total contract-level PnL, defined as:

            price_move_pnl + trade_pnl
    """

    contract_id: str
    price_move_pnl: float
    trade_pnl: float
    total_pnl: float

    def __post_init__(self) -> None:
        expected_total = self.price_move_pnl + self.trade_pnl
        if not math.isclose(
            self.total_pnl, expected_total, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                "ContractPnL total_pnl must equal price_move_pnl + trade_pnl. "
                f"Got total_pnl={self.total_pnl}, "
                f"price_move_pnl={self.price_move_pnl}, "
                f"trade_pnl={self.trade_pnl}, "
                f"expected_total={expected_total}."
            )


@dataclass(frozen=True, slots=True)
class SessionPnL:
    """
    Aggregate economic PnL for a single session, with contract-level detail.

    Parameters
    ----------
    previous_session
        The immediately preceding session used as the start mark for
        price-move PnL. For the first session in a run this is typically
        None.

    session
        The session for which this PnL is computed.

    contract_pnls
        Canonical contract-level PnL rows for this session.

    price_move_pnl
        Session-level aggregate price-move PnL. This must equal the sum
        of contract-level price_move_pnl values.

    trade_pnl
        Session-level aggregate trade PnL. This must equal the sum of
        contract-level trade_pnl values.

    total_pnl
        Session-level aggregate total PnL. This must equal the sum of
        contract-level total_pnl values.
    """

    previous_session: np.datetime64 | None
    session: np.datetime64
    contract_pnls: tuple[ContractPnL, ...]
    price_move_pnl: float
    trade_pnl: float
    total_pnl: float

    def __post_init__(self) -> None:
        self._validate_contract_rows()
        self._validate_aggregates()

    def _validate_contract_rows(self) -> None:
        contract_ids = [cp.contract_id for cp in self.contract_pnls]

        if len(contract_ids) != len(set(contract_ids)):
            raise ValueError(
                "SessionPnL.contract_pnls must not contain duplicate contract_id values."
            )

    def _validate_aggregates(self) -> None:
        expected_price_move = sum(cp.price_move_pnl for cp in self.contract_pnls)
        expected_trade = sum(cp.trade_pnl for cp in self.contract_pnls)
        expected_total = sum(cp.total_pnl for cp in self.contract_pnls)

        if not math.isclose(
            self.price_move_pnl, expected_price_move, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                "SessionPnL price_move_pnl must equal the sum of contract-level "
                "price_move_pnl values. "
                f"Got price_move_pnl={self.price_move_pnl}, "
                f"expected_price_move={expected_price_move}."
            )

        if not math.isclose(
            self.trade_pnl, expected_trade, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                "SessionPnL trade_pnl must equal the sum of contract-level "
                "trade_pnl values. "
                f"Got trade_pnl={self.trade_pnl}, "
                f"expected_trade={expected_trade}."
            )

        if not math.isclose(
            self.total_pnl, expected_total, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                "SessionPnL total_pnl must equal the sum of contract-level "
                "total_pnl values. "
                f"Got total_pnl={self.total_pnl}, "
                f"expected_total={expected_total}."
            )


@dataclass(frozen=True, slots=True)
class PnLSeries:
    """
    Ordered collection of session-level PnL values.

    Responsibilities
    ----------------
    - enforce deterministic session ordering
    - preserve contract-level session detail
    - provide tabular session-level and contract-level views
    - provide cumulative session-level PnL views for plotting

    Notes
    -----
    Cumulative PnL is treated as a derived view rather than stored
    state. This keeps the canonical representation limited to
    per-session economic facts plus contract-level decompositions.
    """

    session_pnls: tuple[SessionPnL, ...]

    def __post_init__(self) -> None:
        sessions = [sp.session for sp in self.session_pnls]

        if len(sessions) != len(set(sessions)):
            raise ValueError("PnLSeries contains duplicate session identifiers.")

        if sessions != sorted(sessions):
            raise ValueError("PnLSeries.session_pnls must be ordered by session.")

    def __len__(self) -> int:
        return len(self.session_pnls)

    def __iter__(self):
        return iter(self.session_pnls)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Return a flat session-level PnL table.

        Columns
        -------
        previous_session
        session
        price_move_pnl
        trade_pnl
        total_pnl
        """
        records = [
            {
                "previous_session": sp.previous_session,
                "session": sp.session,
                "price_move_pnl": sp.price_move_pnl,
                "trade_pnl": sp.trade_pnl,
                "total_pnl": sp.total_pnl,
            }
            for sp in self.session_pnls
        ]
        return pd.DataFrame.from_records(records)

    def to_contract_dataframe(self) -> pd.DataFrame:
        """
        Return a flat contract-level PnL table.

        Columns
        -------
        previous_session
        session
        contract_id
        price_move_pnl
        trade_pnl
        total_pnl
        """
        records: list[dict[str, object]] = []

        for sp in self.session_pnls:
            for cp in sp.contract_pnls:
                records.append(
                    {
                        "previous_session": sp.previous_session,
                        "session": sp.session,
                        "contract_id": cp.contract_id,
                        "price_move_pnl": cp.price_move_pnl,
                        "trade_pnl": cp.trade_pnl,
                        "total_pnl": cp.total_pnl,
                    }
                )

        return pd.DataFrame.from_records(records)

    def to_cumulative_dataframe(self) -> pd.DataFrame:
        """
        Return a session-level PnL table including cumulative columns.

        Additional Columns
        ------------------
        cumulative_price_move_pnl
        cumulative_trade_pnl
        cumulative_total_pnl
        """
        df = self.to_dataframe().copy()

        if df.empty:
            df["cumulative_price_move_pnl"] = pd.Series(dtype=float)
            df["cumulative_trade_pnl"] = pd.Series(dtype=float)
            df["cumulative_total_pnl"] = pd.Series(dtype=float)
            return df

        df["cumulative_price_move_pnl"] = df["price_move_pnl"].cumsum()
        df["cumulative_trade_pnl"] = df["trade_pnl"].cumsum()
        df["cumulative_total_pnl"] = df["total_pnl"].cumsum()
        return df

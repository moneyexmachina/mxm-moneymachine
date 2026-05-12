"""
MXM V1 — Multi-session backtest runner.

This module defines a thin historical runner over SessionEngine.

Architectural role
------------------
The Backtester is intentionally simple. It does not implement any
session-step logic itself. Instead it:

- iterates sessions in order
- slices target holdings for each session
- carries realised holdings forward across sessions
- delegates each session step to SessionEngine
- collects SessionResult objects

This makes the layering explicit:

    TargetHoldings
        ↓ per-session slicing
    SessionEngine.run_session(...)
        ↓
    SessionResult
        ↓ collection over sessions
    BacktestResult

Current scope
-------------
The current implementation is designed around TargetHoldings surfaces as
produced by the synthetic-asset layer, but the runner is intentionally
generic enough that later strategy- or portfolio-level target-holdings
surfaces can be used in the same way.

Temporal semantics
------------------
MXM V1 backtesting is session-native.

The Backtester iterates over session labels represented canonically as
`np.datetime64[D]`. It does not introduce timestamp semantics. Any
timestamped order or execution facts are introduced downstream by the
order-generation and execution layers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.session_engine import SessionEngine, SessionResult
from mxm.v1.synthetic_assets.target_holdings import TargetHoldings
from mxm.v1.utils.date_utils import coerce_np_day


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """
    Collected results of running a SessionEngine across multiple sessions.

    Parameters
    ----------
    session_results:
        Ordered session-step results.

    Notes
    -----
    The session_results list is expected to be in strictly increasing
    session order.
    """

    session_results: list[SessionResult]

    def __post_init__(self) -> None:
        self._validate_ordering()

    def _validate_ordering(self) -> None:
        sessions = [result.session for result in self.session_results]
        if sessions != sorted(sessions):
            raise ValueError(
                "BacktestResult.session_results must be sorted by session."
            )

    def is_empty(self) -> bool:
        return len(self.session_results) == 0

    def first_session(self) -> np.datetime64:
        if not self.session_results:
            raise ValueError("BacktestResult is empty.")
        return self.session_results[0].session

    def last_session(self) -> np.datetime64:
        if not self.session_results:
            raise ValueError("BacktestResult is empty.")
        return self.session_results[-1].session


@dataclass(frozen=True, slots=True)
class Backtester:
    """
    Thin multi-session historical runner over SessionEngine.

    Parameters
    ----------
    session_engine:
        Session engine used to process each session step.
    """

    session_engine: SessionEngine

    def run_target_holdings(
        self,
        *,
        target_holdings: TargetHoldings,
        initial_realised_holdings: ContractBundle | None = None,
    ) -> BacktestResult:
        """
        Run the session engine over all sessions in a TargetHoldings surface.

        Parameters
        ----------
        target_holdings:
            Session-indexed target holdings surface.

        initial_realised_holdings:
            Realised holdings carried into the first session. If omitted,
            empty holdings are assumed.

        Returns
        -------
        BacktestResult
            Ordered collection of SessionResult objects.
        """
        sessions = self._extract_sessions(target_holdings)

        previous_realised_holdings = (
            ContractBundle.empty()
            if initial_realised_holdings is None
            else initial_realised_holdings
        )

        previous_session: np.datetime64 | None = None
        session_results: list[SessionResult] = []

        for session in sessions:
            target_bundle = self._target_bundle_for_session(
                target_holdings=target_holdings,
                session=session,
            )

            result = self.session_engine.run_session(
                session=session,
                previous_realised_holdings=previous_realised_holdings,
                target_holdings=target_bundle,
                previous_session=previous_session,
            )

            session_results.append(result)
            previous_realised_holdings = result.realised_holdings
            previous_session = result.session

        return BacktestResult(session_results=session_results)

    @staticmethod
    def _extract_sessions(target_holdings: TargetHoldings) -> list[np.datetime64]:
        """
        Extract unique realised sessions from the TargetHoldings surface in
        deterministic order.
        """
        sessions = target_holdings.frame.index.get_level_values("session").unique()
        return [coerce_np_day(session) for session in sessions]

    @staticmethod
    def _target_bundle_for_session(
        *,
        target_holdings: TargetHoldings,
        session: np.datetime64,
    ) -> TargetContractBundle:
        """
        Convert one TargetHoldings session slice into a TargetContractBundle.
        """
        frame = target_holdings.holdings_for_session(session)

        series = frame["target_holding"].copy()
        contract_index = frame.index.get_level_values("contract_id")
        series.index = pd.Index(contract_index, name="contract_id")

        return TargetContractBundle(series)

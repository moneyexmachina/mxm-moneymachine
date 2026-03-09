from __future__ import annotations

"""
Linear roll model for futures contract pairs, expressed in session-distance space.

This module implements a unit-less linear roll schedule for a rolling pair
("cur", "nxt") using the derived series:

    d[t] = bdays_to_ltd(asof=t, ltd=LTD(contract_id[t]))

where d is expressed in *trading-session space* (business-day indices on the
product's trading calendar).

ContractSeries alignment
------------------------
MXM selector eligibility is strict:

    eligible iff last_trading_day > as_of_session

Therefore, the expiring contract does not appear in ContractSeries on its LTD
session (d == 0); the final eligible session is d == 1.

This model never requires d == 0 for the expiring contract and clips roll ramps
accordingly.

Roll definition
---------------
Parameters:
    N1 : roll_start_offset
         start the roll when d == N1 (i.e. N1 sessions before LTD)

    D  : roll_duration
         number of sessions over which to linearly transfer exposure from cur to nxt.
         D = 1 corresponds to a one-session roll on the roll-start session.

Let:
    d_low = max(1, N1 - D + 1)

Weights are defined piecewise by d:

    if d > N1:
        w_cur = 1, w_nxt = 0

    elif d < d_low:
        w_cur = 0, w_nxt = 1

    else:
        linear ramp over effective_len = (N1 - d_low + 1) sessions, with:
            k = N1 - d       (0 at roll start, increasing towards expiry)
            alpha = (k + 1) / effective_len   (first ramp day alpha=1/len, last alpha=1)
            w_nxt = alpha
            w_cur = 1 - alpha

Determinism
-----------
Pure function: no I/O, no timestamps, no external services.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class LinearRoll:
    roll_start_offset: int  # N1 >= 0
    roll_duration: int  # D >= 1

    def compute_weights_from_bdays_to_ltd(
        self,
        *,
        bdays_to_ltd: NDArray[np.int64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """
        Compute (w_cur, w_nxt) from a session-aligned bdays_to_ltd series.

        Parameters
        ----------
        bdays_to_ltd:
            1D int64 array aligned to the ContractSeries sessions, where
            bdays_to_ltd[t] = index(LTD(contract_id[t])) - index(session[t]).

        Returns
        -------
        w_cur, w_nxt:
            1D float64 arrays aligned with bdays_to_ltd.

        Invariants
        ----------
        - w_cur + w_nxt == 1 (up to float tolerance)
        - weights in [0,1]
        """
        if self.roll_start_offset < 1:
            raise ValueError("roll_start_offset must be >= 1")

        if self.roll_duration <= 0:
            raise ValueError("roll_duration must be >= 1")

        if self.roll_duration > self.roll_start_offset:
            raise ValueError("roll_duration must be <= roll_start_offset")

        d = np.asarray(bdays_to_ltd, dtype=np.int64)
        n = int(d.size)

        N1 = int(self.roll_start_offset)
        D = int(self.roll_duration)

        d_low = N1 - D + 1
        effective_len = D

        w_cur = np.empty(n, dtype=np.float64)

        # Regions
        pre = d > N1
        post = d < d_low
        ramp = ~(pre | post)

        # Pre-roll: fully cur
        w_cur[pre] = 1.0

        # Post-roll: fully nxt (still before the switch day in the old regime)
        w_cur[post] = 0.0

        # Ramp: linear transition
        if np.any(ramp):
            # k = 0 at d==N1, increases as d decreases towards d_low
            k = (N1 - d[ramp]).astype(np.int64)

            # alpha first day = 1/len, last day = 1
            alpha = (k + 1).astype(np.float64) / float(effective_len)
            alpha = np.clip(alpha, 0.0, 1.0)

            w_cur[ramp] = 1.0 - alpha

        w_nxt = 1.0 - w_cur
        return w_cur, w_nxt

from __future__ import annotations

"""
MXM V1 — Spot FX conversion boundary.

This module defines the interface for converting native-currency economic
values into a target currency using spot FX rates.

Architectural role
------------------
The PnL layer computes economic value changes at contract level and may
need to express those values in a target currency different from the
native contract currency.

The SpotFXConverter provides the boundary for that conversion.

At the current stage of Session 29, the converter is included so that
PnL construction can depend on an explicit FX interface without yet
requiring real FX market-data ingestion.

Current scope
-------------
The first implementation provided here supports only the identity case:

    from_currency == to_currency  ->  1.0

If currencies differ, conversion is not yet implemented and the
converter raises NotImplementedError.

Future direction
----------------
Later implementations will need to support:

- lookup of FX spot or equivalent translation surfaces
- timestamp-indexed conversion factors
- inversion logic (for example USD/EUR vs EUR/USD storage)
- deterministic failure on missing FX data
- attribution of PnL into:
    - native price effect
    - FX effect
    - price–FX interaction
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


class SpotFXConverter(ABC):
    """
    Abstract timestamp-indexed spot FX conversion interface.

    Implementations return the multiplier used to convert a native-
    currency amount into a target-currency amount at a given moment.

    Conceptually:

        amount_target =
            amount_native
            * get_fx_multiplier(from_currency, to_currency, timestamp)
    """

    @abstractmethod
    def get_fx_multiplier(
        self,
        *,
        from_currency: str,
        to_currency: str,
        timestamp: pd.Timestamp,
    ) -> float:
        """
        Return the FX multiplier converting from one currency into
        another at a given timestamp.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class IdentitySpotFXConverter(SpotFXConverter):
    """
    Minimal Session-29 spot FX converter.

    Behaviour
    ---------
    - returns 1.0 if from_currency == to_currency
    - otherwise raises NotImplementedError
    """

    def get_fx_multiplier(
        self,
        *,
        from_currency: str,
        to_currency: str,
        timestamp: pd.Timestamp,
    ) -> float:
        if from_currency == to_currency:
            return 1.0

        raise NotImplementedError(
            "Cross-currency spot FX conversion is not yet implemented. "
            f"from_currency={from_currency!r}, "
            f"to_currency={to_currency!r}, "
            f"timestamp={timestamp!r}"
        )

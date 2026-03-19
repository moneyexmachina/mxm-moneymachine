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
from typing import Any

import pandas as pd


def _normalize_currency_code(currency: Any) -> str:
    """
    Normalize a currency-like object to a canonical uppercase code.

    Accepted inputs for current MXM usage:
    - plain ISO code strings, e.g. "USD"
    - enum members whose `.name` is the ISO code, e.g. Currency.USD
    - objects exposing a `.code` attribute equal to the ISO code

    This keeps the FX boundary tolerant to mixed upstream representations
    while preserving strict behaviour for unknown shapes.
    """
    if isinstance(currency, str):
        code = currency.strip().upper()
        if code == "":
            raise ValueError("currency string must be non-empty")
        return code

    code_attr = getattr(currency, "code", None)
    if isinstance(code_attr, str):
        code = code_attr.strip().upper()
        if code == "":
            raise ValueError("currency.code must be non-empty")
        return code

    name_attr = getattr(currency, "name", None)
    if isinstance(name_attr, str):
        code = name_attr.strip().upper()
        if code == "":
            raise ValueError("currency.name must be non-empty")
        return code

    raise TypeError(
        "Unsupported currency representation. "
        f"currency={currency!r}, type={type(currency).__name__}"
    )


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
        from_currency: Any,
        to_currency: Any,
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
    - returns 1.0 if normalized from_currency == normalized to_currency
    - otherwise raises NotImplementedError
    """

    def get_fx_multiplier(
        self,
        *,
        from_currency: Any,
        to_currency: Any,
        timestamp: pd.Timestamp,
    ) -> float:
        from_code = _normalize_currency_code(from_currency)
        to_code = _normalize_currency_code(to_currency)

        if from_code == to_code:
            return 1.0

        raise NotImplementedError(
            "Cross-currency spot FX conversion is not yet implemented. "
            f"from_currency={from_currency!r} ({from_code}), "
            f"to_currency={to_currency!r} ({to_code}), "
            f"timestamp={timestamp!r}"
        )

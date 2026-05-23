"""
MXM V1 — Session-scoped spot FX conversion boundary.

This module defines the interface for converting native-currency economic
values into a target currency using spot FX rates.

Architectural role
------------------
The PnL layer computes economic value changes at contract level and may
need to express those values in a target currency different from the
native contract currency.

The SpotFXConverter provides the boundary for that conversion.

The current MXM PnL pipeline operates in the session domain rather than
the timeline domain. Holdings, marks, and PnL are currently indexed by
trading-session labels rather than UTC instants.

Accordingly, FX conversion is presently defined at session granularity.

At the current stage of Session 29/30, the converter is included so that
PnL construction can depend on an explicit FX interface without yet
requiring real FX market-data ingestion.

Current scope
-------------
Session 29/30 currently supports only session-scoped identity conversion:

    from_currency == to_currency  ->  1.0

If currencies differ, conversion is not yet implemented and the
converter raises NotImplementedError.

Future direction
----------------
Later implementations will need to support:

- lookup of FX spot or equivalent translation surfaces
- session-indexed conversion factors
- inversion logic (for example USD/EUR vs EUR/USD storage)
- deterministic failure on missing FX data
- attribution of PnL into:
    - native price effect
    - FX effect
    - price-FX interaction

Future higher-frequency execution workflows may additionally introduce:

- timestamp-indexed FX conversion
- intraday FX translation surfaces
- execution-time FX attribution
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from mxm.refdata.models.currencies import Currency


def _normalize_currency_code(currency: str | Currency) -> str:
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
    Abstract session-indexed spot FX conversion interface.

    Implementations return the multiplier used to convert a native-currency
    amount into a target-currency amount for a given trading session.

    Conceptually:

        amount_target =
            amount_native
            * get_fx_multiplier(from_currency, to_currency, session)

    The session is a calendar-domain session label, not a UTC instant.
    """

    @abstractmethod
    def get_fx_multiplier(
        self,
        *,
        from_currency: str | Currency,
        to_currency: str | Currency,
        session: np.datetime64,
    ) -> float:
        """
        Return the FX multiplier converting from one currency into another
        for a given session label.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class IdentitySpotFXConverter(SpotFXConverter):
    """
    Minimal Session-29/30 spot FX converter.

    Behaviour
    ---------
    - returns 1.0 if normalized from_currency == normalized to_currency
    - otherwise raises NotImplementedError
    """

    def get_fx_multiplier(
        self,
        *,
        from_currency: str | Currency,
        to_currency: str | Currency,
        session: np.datetime64,
    ) -> float:
        from_code = _normalize_currency_code(from_currency)
        to_code = _normalize_currency_code(to_currency)

        if from_code == to_code:
            return 1.0

        raise NotImplementedError(
            "Cross-currency spot FX conversion is not yet implemented. "
            f"from_currency={from_currency!r} ({from_code}), "
            f"to_currency={to_currency!r} ({to_code}), "
            f"session={session!r}"
        )

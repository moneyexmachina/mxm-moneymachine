"""
Explicit unit conversion utilities for synthetic asset construction.

This module provides:

- scalar conversion factors
- scalar value conversion
- vectorised conversion across arrays of values / units

Inputs may be provided either as ProductUnit or as strings that resolve
unambiguously to ProductUnit enum members.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from mxm.refdata.models import ProductUnit


class UnsupportedUnitConversion(ValueError):
    pass


class UnknownProductUnit(ValueError):
    pass


UnitLike = ProductUnit | str


_PRODUCT_UNIT_BY_NAME: dict[str, ProductUnit] = {u.name: u for u in ProductUnit}
_PRODUCT_UNIT_BY_VALUE: dict[str, ProductUnit] = {u.value: u for u in ProductUnit}


def coerce_product_unit(unit: UnitLike) -> ProductUnit:
    """
    Coerce a ProductUnit-like input into a ProductUnit.

    Accepted inputs:
    - ProductUnit enum member
    - enum member name, e.g. "TROY_OUNCE"
    - enum member value, e.g. "Troy Ounce"

    Raises
    ------
    UnknownProductUnit
        If the input cannot be resolved to a ProductUnit.
    """
    if isinstance(unit, ProductUnit):
        return unit

    if unit in _PRODUCT_UNIT_BY_NAME:
        return _PRODUCT_UNIT_BY_NAME[unit]
    if unit in _PRODUCT_UNIT_BY_VALUE:
        return _PRODUCT_UNIT_BY_VALUE[unit]

    raise UnknownProductUnit(f"Unknown ProductUnit: {unit!r}")


def _empty_conversion_table() -> dict[tuple[ProductUnit, ProductUnit], float]:
    return {}


@dataclass(frozen=True, slots=True)
class UnitConverter:
    """
    Explicit unit conversion table.

    conversion_factors maps:

        (from_unit, to_unit) -> factor

    with the interpretation:

        value_in_to_unit = value_in_from_unit * factor
    """

    conversion_factors: dict[tuple[ProductUnit, ProductUnit], float] = field(
        default_factory=_empty_conversion_table
    )

    def conversion_factor(
        self,
        *,
        from_unit: UnitLike,
        to_unit: UnitLike,
    ) -> float:
        """
        Return the multiplicative factor converting from `from_unit` to `to_unit`.

        Raises
        ------
        UnknownProductUnit
            If either unit cannot be resolved to ProductUnit.
        UnsupportedUnitConversion
            If the conversion pair is not explicitly supported.
        """
        u_from = coerce_product_unit(from_unit)
        u_to = coerce_product_unit(to_unit)

        if u_from == u_to:
            return 1.0

        key = (u_from, u_to)
        if key in self.conversion_factors:
            return self.conversion_factors[key]

        raise UnsupportedUnitConversion(
            f"Unsupported unit conversion: {u_from.name} -> {u_to.name}"
        )

    def convert_value(
        self,
        *,
        value: float,
        from_unit: UnitLike,
        to_unit: UnitLike,
    ) -> float:
        """
        Convert a scalar value from `from_unit` to `to_unit`.
        """
        factor = self.conversion_factor(from_unit=from_unit, to_unit=to_unit)
        return float(value) * factor

    def conversion_factors_vectorized(
        self,
        *,
        from_units: NDArray[np.object_],
        to_units: NDArray[np.object_],
    ) -> NDArray[np.float64]:
        """
        Return conversion factors elementwise for aligned unit arrays.

        Inputs may contain ProductUnit or str values.

        Raises
        ------
        ValueError
            If array shapes differ.
        UnknownProductUnit
            If any unit cannot be resolved to ProductUnit.
        UnsupportedUnitConversion
            If any conversion pair is unsupported.
        """
        if from_units.shape != to_units.shape:
            raise ValueError(
                f"from_units.shape {from_units.shape!r} does not match "
                f"to_units.shape {to_units.shape!r}"
            )

        out = np.empty(from_units.shape, dtype=np.float64)

        flat_from = from_units.ravel()
        flat_to = to_units.ravel()
        flat_out = out.ravel()

        for i in range(flat_from.size):
            flat_out[i] = self.conversion_factor(
                from_unit=flat_from[i],
                to_unit=flat_to[i],
            )

        return out

    def convert_values_vectorized(
        self,
        *,
        values: NDArray[np.float64],
        from_units: NDArray[np.object_],
        to_units: NDArray[np.object_],
    ) -> NDArray[np.float64]:
        """
        Convert aligned arrays of values from elementwise source units to
        elementwise target units.

        Inputs may contain ProductUnit or str values.
        """
        if values.shape != from_units.shape or values.shape != to_units.shape:
            raise ValueError(
                "values, from_units, and to_units must have identical shapes"
            )

        factors = self.conversion_factors_vectorized(
            from_units=from_units,
            to_units=to_units,
        )
        return values.astype(np.float64, copy=False) * factors


def build_default_unit_converter() -> UnitConverter:
    """
    Build the default explicit unit converter for currently supported MXM units.

    Only dimensionally explicit, non-commodity-specific conversions are
    included here.
    """
    g_per_oz = 28.349523125
    g_per_troy_oz = 31.1034768
    g_per_tonne = 1_000_000.0
    liters_per_gallon = 3.785411784
    liters_per_cubic_meter = 1000.0

    factors: dict[tuple[ProductUnit, ProductUnit], float] = {
        # Exact aliases
        (ProductUnit.TONNE, ProductUnit.METRIC_TON): 1.0,
        (ProductUnit.METRIC_TON, ProductUnit.TONNE): 1.0,
        # Mass
        (ProductUnit.OUNCE, ProductUnit.GRAM): g_per_oz,
        (ProductUnit.GRAM, ProductUnit.OUNCE): 1.0 / g_per_oz,
        (ProductUnit.TROY_OUNCE, ProductUnit.GRAM): g_per_troy_oz,
        (ProductUnit.GRAM, ProductUnit.TROY_OUNCE): 1.0 / g_per_troy_oz,
        (ProductUnit.GRAM, ProductUnit.TONNE): 1.0 / g_per_tonne,
        (ProductUnit.TONNE, ProductUnit.GRAM): g_per_tonne,
        (ProductUnit.OUNCE, ProductUnit.TONNE): g_per_oz / g_per_tonne,
        (ProductUnit.TONNE, ProductUnit.OUNCE): g_per_tonne / g_per_oz,
        (ProductUnit.TROY_OUNCE, ProductUnit.TONNE): g_per_troy_oz / g_per_tonne,
        (ProductUnit.TONNE, ProductUnit.TROY_OUNCE): g_per_tonne / g_per_troy_oz,
        (ProductUnit.TROY_OUNCE, ProductUnit.OUNCE): g_per_troy_oz / g_per_oz,
        (ProductUnit.OUNCE, ProductUnit.TROY_OUNCE): g_per_oz / g_per_troy_oz,
        # Volume
        (ProductUnit.GALLON, ProductUnit.LITER): liters_per_gallon,
        (ProductUnit.LITER, ProductUnit.GALLON): 1.0 / liters_per_gallon,
        (ProductUnit.CUBIC_METER, ProductUnit.LITER): liters_per_cubic_meter,
        (ProductUnit.LITER, ProductUnit.CUBIC_METER): 1.0 / liters_per_cubic_meter,
    }

    return UnitConverter(conversion_factors=factors)

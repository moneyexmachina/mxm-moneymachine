from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Self

import pandas as pd


@dataclass(frozen=True, init=False, eq=False)
class AbstractContractBundle(ABC):
    """
    Sparse signed bundle of contracts.

    Conceptually, a contract bundle is a mapping:

        contract_id -> signed quantity

    with the following semantics:

    - missing contract_id implies zero quantity
    - bundle arithmetic aligns on the union of contract_ids
    - canonical storage is sparse: zero entries are removed
    - canonical storage is deterministic: index is sorted
    - the index must be a single-level contract_id index
    """

    _quantities: pd.Series

    def __init__(self, quantities: pd.Series) -> None:
        canonical = self._canonicalize(quantities)
        self._validate_series(canonical)
        object.__setattr__(self, "_quantities", canonical)

    @property
    def quantities(self) -> pd.Series:
        """
        Return a defensive copy of the canonical contract quantities.
        """
        return self._quantities.copy()

    @classmethod
    def empty(cls) -> Self:
        series = pd.Series(
            dtype=cls._empty_dtype(),
            index=pd.Index([], name="contract_id"),
        )
        return cls(series)

    @classmethod
    def from_series(cls, series: pd.Series) -> Self:
        return cls(series)

    @classmethod
    def from_dict(cls, data: Mapping[str, int | float]) -> Self:
        series = pd.Series(data)
        return cls(series)

    @classmethod
    @abstractmethod
    def _empty_dtype(cls) -> str:
        """
        Pandas dtype string to use for empty construction.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _coerce_numeric(cls, series: pd.Series) -> pd.Series:
        """
        Coerce a numeric series into the subclass numeric regime.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _validate_numeric(cls, series: pd.Series) -> None:
        """
        Validate subclass-specific numeric constraints.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def _zero_value(cls) -> int | float:
        """
        Return the numeric zero value appropriate to the subclass regime.
        """
        raise NotImplementedError

    @classmethod
    def _canonicalize(cls, series: pd.Series) -> pd.Series:
        """
        Return canonical sparse deterministic form.

        Canonicalisation rules:
        - index must be named 'contract_id'
        - values must be numeric and non-missing
        - subclass coercion is applied
        - zero entries are removed
        - index is sorted
        """
        if series.ndim != 1:
            raise ValueError(
                f"{cls.__name__} requires a 1D Series, got ndim={series.ndim}."
            )

        out = series.copy()

        if out.index.nlevels != 1:
            raise ValueError(
                f"{cls.__name__} requires a single-level index of contract_id."
            )

        out.index = pd.Index(out.index, name="contract_id")

        if out.isna().any():
            missing = list(out.index[out.isna()])
            raise ValueError(
                f"{cls.__name__} does not allow missing quantities. "
                f"Missing values for contract_ids: {missing!r}"
            )

        if not pd.api.types.is_numeric_dtype(out):
            raise TypeError(
                f"{cls.__name__} requires numeric quantities, got dtype={out.dtype!r}."
            )

        out = cls._coerce_numeric(out)

        zero_mask = out == 0
        if zero_mask.any():
            out = out.loc[~zero_mask]

        out = out.sort_index()

        return out

    @classmethod
    def _validate_series(cls, series: pd.Series) -> None:
        """
        Validate canonical series invariants.
        """
        if series.index.name != "contract_id":
            raise ValueError(
                f"{cls.__name__} index must be named 'contract_id', "
                f"got {series.index.name!r}."
            )

        if series.index.has_duplicates:
            duplicates = series.index[series.index.duplicated()].tolist()
            raise ValueError(
                f"{cls.__name__} does not allow duplicate contract_id entries: "
                f"{duplicates!r}"
            )

        if series.isna().any():
            raise ValueError(f"{cls.__name__} does not allow missing values.")

        cls._validate_numeric(series)

    @property
    def contract_ids(self) -> pd.Index:
        """
        Contract ids present in the sparse canonical bundle.
        """
        return self._quantities.index.copy()

    def quantity(self, contract_id: str) -> int | float:
        """
        Return quantity for contract_id, defaulting to zero if absent.
        """
        if contract_id in self._quantities.index:
            return self._quantities.loc[contract_id]
        return self._zero_value()

    def is_empty(self) -> bool:
        """
        Return True if the bundle has no non-zero entries.
        """
        return self._quantities.empty

    def __len__(self) -> int:
        return len(self._quantities)

    def __neg__(self) -> Self:
        return self.__class__.from_series(-self._quantities)

    def _binary_op(
        self,
        other: AbstractContractBundle,
        op: str,
    ) -> Self:
        if self.__class__ is not other.__class__:
            raise TypeError(
                f"Bundle arithmetic requires matching bundle types, got "
                f"{self.__class__.__name__} and {other.__class__.__name__}."
            )

        left = self._quantities
        right = other._quantities

        if op == "add":
            result = left.add(right, fill_value=self._zero_value())
        elif op == "sub":
            result = left.sub(right, fill_value=self._zero_value())
        else:
            raise ValueError(f"Unknown binary op: {op!r}")

        return self.__class__.from_series(result)

    def __add__(self, other: AbstractContractBundle) -> Self:
        return self._binary_op(other, "add")

    def __sub__(self, other: AbstractContractBundle) -> Self:
        return self._binary_op(other, "sub")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AbstractContractBundle):
            return False
        if self.__class__ is not other.__class__:
            return False
        return self._quantities.equals(other._quantities)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"n_contracts={len(self._quantities)}, "
            f"quantities=\n{self._quantities!r}\n)"
        )


@dataclass(frozen=True, init=False, eq=False)
class ContractBundle(AbstractContractBundle):
    """
    Sparse signed integer bundle of contracts.

    A ContractBundle represents realised or executable contract quantities:

        contract_id -> signed integer lots

    Typical semantic subclasses include realised holdings and executed trades.

    Invariants
    ----------
    - quantities must be integer-valued
    - canonical storage uses sparse non-zero entries only
    - missing contract_id implies zero lots
    """

    @classmethod
    def _empty_dtype(cls) -> str:
        return "int64"

    @classmethod
    def _coerce_numeric(cls, series: pd.Series) -> pd.Series:
        if pd.api.types.is_integer_dtype(series):
            return series.astype("int64")

        numeric = pd.to_numeric(series, errors="raise")

        if ((numeric % 1) != 0).any():
            bad = numeric[(numeric % 1) != 0]
            raise ValueError(
                "ContractBundle requires integer lot quantities. "
                f"Found non-integer entries: {bad.to_dict()!r}"
            )

        return numeric.astype("int64")

    @classmethod
    def _validate_numeric(cls, series: pd.Series) -> None:
        if not pd.api.types.is_integer_dtype(series):
            raise TypeError(
                f"ContractBundle requires integer dtype, got {series.dtype!r}."
            )

    @classmethod
    def _zero_value(cls) -> int:
        return 0


@dataclass(frozen=True, init=False, eq=False)
class TargetContractBundle(AbstractContractBundle):
    """
    Sparse signed real-valued target bundle of contracts.

    A TargetContractBundle represents ideal or intended contract quantities:

        contract_id -> signed float quantity

    This is the natural carrier for target-side objects such as target
    holdings and target trades, where fractional desired quantities are
    allowed.

    Invariants
    ----------
    - quantities must be numeric
    - float-valued quantities are allowed
    - canonical storage uses sparse non-zero entries only
    - missing contract_id implies zero quantity
    """

    @classmethod
    def _empty_dtype(cls) -> str:
        return "float64"

    @classmethod
    def _coerce_numeric(cls, series: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(series, errors="raise")
        return numeric.astype("float64")

    @classmethod
    def _validate_numeric(cls, series: pd.Series) -> None:
        if not pd.api.types.is_float_dtype(series):
            raise TypeError(
                f"TargetContractBundle requires float dtype, got {series.dtype!r}."
            )

    @classmethod
    def _zero_value(cls) -> float:
        return 0.0

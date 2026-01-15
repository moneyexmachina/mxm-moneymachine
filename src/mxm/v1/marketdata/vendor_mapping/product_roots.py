from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DatabentoProductRoot:
    product_id: str
    dataset: str
    parent: str  # e.g. ES.FUT
    stype_in: str = "parent"


_DATABENTO_PRODUCT_ROOTS: Mapping[str, DatabentoProductRoot] = {
    # MVP: ES
    "cme_emini_snp500_futures": DatabentoProductRoot(
        product_id="cme_emini_snp500_futures",
        dataset="GLBX.MDP3",
        parent="ES.FUT",
    ),
    # Add more products here...
}


def get_databento_product_root(product_id: str) -> DatabentoProductRoot:
    try:
        return _DATABENTO_PRODUCT_ROOTS[product_id]
    except KeyError as e:
        raise KeyError(
            f"No Databento product root mapping for product_id={product_id!r}. "
            f"Add it to _DATABENTO_PRODUCT_ROOTS in product_roots.py."
        ) from e

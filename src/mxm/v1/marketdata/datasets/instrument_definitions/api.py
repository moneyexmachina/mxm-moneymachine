# mxm/v1/marketdata/datasets/instrument_definitions/api.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    CoverageCheck,
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)

# ---------------------------------------------------------------------------
# Feed identity (vendor-scoped)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentDefinitionFeed:
    """
    Vendor-internal identity for an instrument-definition ingestion scope.

    This is the unit of watermarking and provenance. It must be stable under
    changes to internal MXM mappings (e.g. product_id -> product_root).
    """

    source: str  # e.g. "databento"
    dataset: str  # e.g. "GLBX.MDP3"
    schema: str  # "definition"
    stype_in: str  # e.g. "parent"
    symbol: str  # e.g. "ES.FUT" (the actual symbol passed to the vendor)

    def key(self) -> str:
        """
        Deterministic feed key used as the watermark identity.

        Keep this stable and purely vendor-scoped.
        """
        return (
            f"{self.source}:"
            f"dataset={self.dataset}:"
            f"schema={self.schema}:"
            f"stype_in={self.stype_in}:"
            f"symbol={self.symbol}"
        )


def make_instrument_definition_feed(
    *,
    source: str,
    dataset: str,
    symbol: str,
    stype_in: str = "parent",
    schema: str = "definition",
) -> InstrumentDefinitionFeed:
    """
    Construct the canonical vendor-scoped feed identity for instrument definitions.
    """
    if not source:
        raise ValueError("source must be non-empty")
    if not dataset:
        raise ValueError("dataset must be non-empty")
    if not symbol:
        raise ValueError("symbol must be non-empty")
    if not stype_in:
        raise ValueError("stype_in must be non-empty")
    if not schema:
        raise ValueError("schema must be non-empty")

    return InstrumentDefinitionFeed(
        source=source,
        dataset=dataset,
        schema=schema,
        stype_in=stype_in,
        symbol=symbol,
    )


# ---------------------------------------------------------------------------
# Ingestion helper (pure; used by orchestrators)
# ---------------------------------------------------------------------------


def get_start_from_watermark(
    *,
    watermark: str | None,
    default_start: str,
    overlap: str = "0s",
) -> str:
    """
    Compute the next pull 'start' for a given feed watermark.

    Semantics:
    - If watermark is None: this feed has never been ingested -> return default_start.
    - If watermark exists: return (watermark - overlap), expressed as ISO8601 UTC with Z.

    Notes:
    - overlap exists to safely handle vendor-side boundary conditions and to allow
      idempotent re-fetching across the last seen boundary.
    - The store enforces idempotency via event_uid, so overlaps are safe.
    """
    if watermark is None:
        ts = pd.Timestamp(default_start)
    else:
        ts = pd.Timestamp(watermark)

    # Normalize to UTC
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    td = pd.Timedelta(overlap)

    ts_start = ts - td if watermark is not None else ts

    # Canonical ISO8601 UTC with Z
    return ts_start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Read-only dataset API (no SQL; delegates to store)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentDefinitionsScope:
    """
    A resolved scope for instrument definitions for a product_id.

    This is a convenience structure so callers can access both:
    - the vendor root inputs (dataset, parent, stype_in)
    - the canonical feed key used across tables
    """

    product_id: str
    source: str
    dataset: str
    symbol: str
    stype_in: str
    feed: str


def resolve_scope_for_product(*, product_id: str) -> InstrumentDefinitionsScope:
    """
    Resolve product_id into the Databento product-root and canonical feed identity.
    """
    root = get_databento_product_root(product_id)
    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    return InstrumentDefinitionsScope(
        product_id=product_id,
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        feed=feed,
    )


def get_watermark_for_product(
    *, store: InstrumentDefinitionsStore, product_id: str
) -> Optional[str]:
    """
    Read-only watermark lookup for the product's instrument definition feed.
    """
    scope = resolve_scope_for_product(product_id=product_id)
    return store.get_watermark(feed=scope.feed)


def check_coverage_for_product(
    *, store: InstrumentDefinitionsStore, product_id: str, required_end: str
) -> CoverageCheck:
    """
    Read-only coverage gate for downstream datasets.

    required_end should be canonical ISO8601Z string.
    """
    scope = resolve_scope_for_product(product_id=product_id)
    return store.check_coverage(feed=scope.feed, required_end=required_end)


def count_events_for_product(
    *, store: InstrumentDefinitionsStore, product_id: str
) -> int:
    scope = resolve_scope_for_product(product_id=product_id)
    return store.count_events_by_feed(feed=scope.feed)


def count_current_for_product(
    *, store: InstrumentDefinitionsStore, product_id: str
) -> int:
    scope = resolve_scope_for_product(product_id=product_id)
    return store.count_current_by_feed(feed=scope.feed)


def list_current_outright_maturities_for_product(
    *, store: InstrumentDefinitionsStore, product_id: str
) -> set[tuple[int, int]]:
    """
    Read-only helper for mapping gates/audits:
    returns the set of outright futures maturities present in current view for this product.
    """
    scope = resolve_scope_for_product(product_id=product_id)
    return store.list_current_outright_maturities_by_feed(feed=scope.feed)


def read_current_for_product(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    limit: int = 1000,
    newest_first: bool = True,
) -> list[dict]:
    """
    Bounded read of current rows for operational diagnostics. No SQL here.
    """
    scope = resolve_scope_for_product(product_id=product_id)
    return store.read_current_by_feed(
        feed=scope.feed,
        limit=limit,
        newest_first=newest_first,
    )

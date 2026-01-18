# mxm/v1/marketdata/datasets/instrument_definitions/api.py
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


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

    Parameters:
    - watermark: the stored ts_recv_last for this feed (ISO8601 UTC with Z).
    - default_start: earliest desired start when no watermark exists (string accepted by pd.Timestamp).
    - overlap: pandas Timedelta-compatible string, e.g. "0s", "1s", "1h", "1d".

    Returns:
    - start string in ISO8601 UTC with Z, including microseconds for stability.
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

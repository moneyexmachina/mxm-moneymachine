from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.daily_mark import (
    DailyMarkWriteResult,
    read_daily_mark,
    read_daily_mark_meta,
    write_daily_mark,
)


@dataclass(frozen=True)
class StoreCoverageSnapshot:
    """
    Observed coverage snapshot in the local parquet store for a single
    `daily_mark` dataset identity.

    Identity:
    - calendar_id
    - contract_id

    Coverage semantics:
    - min_session_id / max_session_id are observed min/max of session_id
    - content_sha256 is the semantic, order-invariant hash of canonicalised content
    - artifact_sha256 is the sha256 of parquet bytes (integrity/debug)
    - exists indicates whether the daily_mark parquet file exists
    """

    mark_path: Path
    exists: bool
    row_count: int
    min_session_id: int | None
    max_session_id: int | None

    meta_path: Path | None = None
    content_sha256: str | None = None
    artifact_sha256: str | None = None
    source_content_sha256: str | None = None


class DailyMarkStore:
    """
    Dataset-domain store for curated `daily_mark` surfaces.

    Responsibilities:
    - Provide stable local persistence operations
      (delegating to stores/parquet/daily_mark.py)
    - Provide local coverage introspection
      (session_id range / rowcount / hashes) for gating and diagnostics

    Non-responsibilities:
    - No calendar construction logic
    - No business->trading mapping logic
    - No mark selection / carry policy logic
    """

    def __init__(self, *, layout: MarketdataLayout) -> None:
        self._layout = layout

    # -------------------------
    # Local persistence API
    # -------------------------

    def mark_path(self, *, calendar_id: str, contract_id: str) -> Path:
        return self._layout.daily_mark_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )

    def meta_path(self, *, calendar_id: str, contract_id: str) -> Path:
        # Must match stores/parquet/daily_mark.py naming.
        return self.mark_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        ).with_name("daily_mark.meta.json")

    def write(
        self,
        *,
        calendar_id: str,
        contract_id: str,
        df_new: pd.DataFrame,
        source_content_sha256: str | None = None,
        skip_if_unchanged: bool = True,
    ) -> DailyMarkWriteResult:
        return write_daily_mark(
            layout=self._layout,
            calendar_id=calendar_id,
            contract_id=contract_id,
            df_new=df_new,
            source_content_sha256=source_content_sha256,
            skip_if_unchanged=skip_if_unchanged,
        )

    def read(
        self,
        *,
        calendar_id: str,
        contract_id: str,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return read_daily_mark(
            layout=self._layout,
            calendar_id=calendar_id,
            contract_id=contract_id,
            start_session_id=start_session_id,
            end_session_id=end_session_id,
        )

    def read_meta(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> dict[str, object] | None:
        m = read_daily_mark_meta(
            layout=self._layout,
            calendar_id=calendar_id,
            contract_id=contract_id,
        )
        if m is None:
            return None
        return m  # type: ignore[return-value]

    # -------------------------
    # Coverage / introspection
    # -------------------------

    def scan_coverage(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> StoreCoverageSnapshot:
        mark_path = self.mark_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )
        meta_path = self.meta_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )

        if not mark_path.exists():
            return StoreCoverageSnapshot(
                mark_path=mark_path,
                exists=False,
                row_count=0,
                min_session_id=None,
                max_session_id=None,
                meta_path=meta_path if meta_path.exists() else None,
            )

        # Meta-first path (fast, preferred)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

                row_count = int(meta["row_count"])
                min_session_id_raw = meta.get("min_session_id")
                max_session_id_raw = meta.get("max_session_id")

                min_session_id = (
                    int(min_session_id_raw) if min_session_id_raw is not None else None
                )
                max_session_id = (
                    int(max_session_id_raw) if max_session_id_raw is not None else None
                )

                return StoreCoverageSnapshot(
                    mark_path=mark_path,
                    exists=True,
                    row_count=row_count,
                    min_session_id=min_session_id,
                    max_session_id=max_session_id,
                    meta_path=meta_path,
                    content_sha256=meta.get("content_sha256"),
                    artifact_sha256=meta.get("artifact_sha256"),
                    source_content_sha256=meta.get("source_content_sha256"),
                )
            except Exception:
                # Corrupt / partial meta -> fall back to parquet scan
                pass

        # Fallback: read parquet (MVP acceptable) and compute
        # min/max session_id / rowcount only.
        df = pd.read_parquet(mark_path)
        if df.empty:
            return StoreCoverageSnapshot(
                mark_path=mark_path,
                exists=True,
                row_count=0,
                min_session_id=None,
                max_session_id=None,
                meta_path=meta_path if meta_path.exists() else None,
            )

        session_min = int(df["session_id"].min())
        session_max = int(df["session_id"].max())

        return StoreCoverageSnapshot(
            mark_path=mark_path,
            exists=True,
            row_count=len(df),
            min_session_id=session_min,
            max_session_id=session_max,
            meta_path=meta_path if meta_path.exists() else None,
        )

    def delete(self, *, calendar_id: str, contract_id: str) -> bool:
        """
        Identity-scoped destructive reset for local parquet + meta sidecar.

        Returns:
            True if the parquet file existed and was deleted.
        """
        mark_path = self.mark_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )
        meta_path = self.meta_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )

        existed = mark_path.exists()
        if existed:
            mark_path.unlink()

        # Best-effort meta removal
        if meta_path.exists():
            meta_path.unlink()

        return existed

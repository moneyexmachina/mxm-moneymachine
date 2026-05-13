from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import pandas as pd

from mxm.v1.marketdata.schema.statistics_1d import (
    STATISTICS_1D,
    coerce_statistics_1d,
    hash_statistics_1d_content,
    validate_statistics_1d,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.utils.hashing import sha256_file
from mxm.v1.utils.time_utils import fmt_run_ts, to_utc_ts, utc_now_run_ts


class Statistics1DMetaDict(TypedDict):
    schema: str
    schema_version: str
    mxm_schema_columns: list[str]
    dataset: str
    publisher_id: int
    instrument_id: int
    row_count: int
    min_ts_event: str | None
    max_ts_event: str | None
    content_sha256: str
    artifact_sha256: str
    updated_at: str
    meta_origin: str  # "ingest" | "backfill_from_parquet"
    # Optional human/operator note (for migrations / backfills / debugging)
    extra_note: NotRequired[str]


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _stats_paths(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
) -> tuple[Path, Path, Path, Path]:
    """
    Return (stats_path, tmp_stats_path, meta_path, tmp_meta_path).
    """
    stats_path = layout.statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    tmp_stats_path = layout.tmp_statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )

    # Sidecar meta lives next to the parquet.
    meta_path = stats_path.with_name("statistics.meta.json")
    tmp_meta_path = stats_path.with_name("statistics.meta.tmp.json")
    return stats_path, tmp_stats_path, meta_path, tmp_meta_path


def _atomic_write_json(
    path: Path, tmp_path: Path, payload: Statistics1DMetaDict
) -> None:
    _ensure_parent_dir(path)
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


# Stable *event* identity key for statistics (rtype=24).
# NOTE: we intentionally do NOT use ts_ref here because it is nullable (NaT) for session stats.
_STAT_EVENT_KEY = ["instrument_id", "stat_type", "ts_event", "sequence"]


def write_statistics_1d(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    df_new: pd.DataFrame,
) -> None:
    """
    Idempotently merge and persist statistics events for a single instrument key,
    and write a sidecar metadata file containing a stable content hash.

    Statistics is an event stream:
    - multiple messages for the same trading session/statistic are expected
      (e.g. preliminary -> final settlements)
    - ts_ref is nullable for session stats and must not be used for event identity

    Rules:
    - event key: (instrument_id, stat_type, ts_event, sequence)
      (prevents uncontrolled duplication across reruns)
    - deduplicate on event key (keep last; latest write wins)
    - stable sort by (ts_event, stat_type, sequence)
    - atomic write (tmp file then os.replace)
    - write meta sidecar with:
        * content_sha256 (semantic hash of canonicalised frame)
        * artifact_sha256 (sha256 of parquet bytes)
    """
    # Coerce + validate incoming frame (loudly)
    df_new = coerce_statistics_1d(
        df_new, dataset=dataset, schema="statistics", ensure_column_order=True
    )

    stats_path, tmp_path, meta_path, tmp_meta_path = _stats_paths(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    _ensure_parent_dir(stats_path)

    if stats_path.exists():
        df_old = pd.read_parquet(stats_path)
        # Ensure old is still valid; catches drift/corruption early
        df_old = coerce_statistics_1d(
            df_old, dataset=dataset, schema="statistics", ensure_column_order=True
        )
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new.copy()

    # Deduplicate on stable event identity key
    df_all = df_all.drop_duplicates(subset=_STAT_EVENT_KEY, keep="last")

    # Sort to keep file stable and query-friendly
    # Primary time axis for an event stream is ts_event (not ts_ref).
    df_all = df_all.sort_values(["ts_event", "stat_type", "sequence"]).reset_index(
        drop=True
    )

    # Final validation before persist
    validate_statistics_1d(df_all)

    # Atomic parquet write
    df_all.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, stats_path)

    # ---- Meta sidecar (post-write) ----
    # Content hash is defined over canonicalised *content*, not parquet bytes.
    # Use coerce function to normalise any minor drift before hashing.
    content_sha256 = hash_statistics_1d_content(df_all)
    artifact_sha256 = sha256_file(stats_path)

    # Coverage convenience
    if len(df_all) == 0:
        min_ts_event = None
        max_ts_event = None
    else:
        min_ts_event = fmt_run_ts(to_utc_ts(df_all["ts_event"].min()))
        max_ts_event = fmt_run_ts(to_utc_ts(df_all["ts_event"].max()))

    meta: Statistics1DMetaDict = {
        "schema": "statistics",
        "schema_version": "1",
        "mxm_schema_columns": list(STATISTICS_1D.columns),
        "dataset": dataset,
        "publisher_id": int(publisher_id),
        "instrument_id": int(instrument_id),
        "row_count": len(df_all),
        "min_ts_event": min_ts_event,
        "max_ts_event": max_ts_event,
        "content_sha256": content_sha256,
        "artifact_sha256": artifact_sha256,
        "meta_origin": "ingest",
        "updated_at": utc_now_run_ts(),
    }
    _atomic_write_json(meta_path, tmp_meta_path, meta)


def read_statistics_1d(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read statistics events from the local store only.

    start/end are interpreted as [start, end), and are applied on `ts_event`
    (the event timestamp).
    """
    stats_path = layout.statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if not stats_path.exists():
        raise FileNotFoundError(f"statistics not found: {stats_path}")

    df = pd.read_parquet(stats_path)
    df = coerce_statistics_1d(
        df, dataset=dataset, schema="statistics", ensure_column_order=True
    )

    if start is not None:
        start = to_utc_ts(start)
        df = df[df["ts_event"] >= start]

    if end is not None:
        end = to_utc_ts(end)
        df = df[df["ts_event"] < end]

    return df.reset_index(drop=True)


def read_statistics_1d_meta(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
) -> Statistics1DMetaDict | None:
    """
    Read the sidecar meta file for statistics_1d, if present.
    Returns None if missing.
    """
    stats_path = layout.statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    meta_path = stats_path.with_name("statistics.meta.json")
    if not meta_path.exists():
        return None
    meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta_raw, dict):
        raise ValueError("statistics meta is not a dict")

    meta = cast(Statistics1DMetaDict, meta_raw)
    # Minimal required keys check (fast, explicit)
    required = (
        "schema",
        "schema_version",
        "row_count",
        "artifact_sha256",
        "content_sha256",
        "updated_at",
    )
    for k in required:
        if k not in meta_raw:
            raise ValueError(f"statistics meta missing required key: {k}")
    return meta


def ensure_statistics_1d_meta(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    force: bool = False,
) -> bool:
    """
    Ensure the statistics_1d meta sidecar exists and is up-to-date.

    Use-cases:
    - Backfill meta for already-collected parquet files (no re-pull required).
    - Repair missing/corrupt meta.
    - Optional force rewrite.

    Semantics:
    - If parquet does not exist: raises FileNotFoundError.
    - If meta exists and force=False: validates it *lightly* against the parquet
      artifact hash; if consistent, returns False (no change). If inconsistent
      or missing keys/corrupt JSON, it is regenerated.
    - If regenerated/written: returns True.

    Notes:
    - This function computes:
        * content_sha256 (semantic hash of canonicalised dataframe)
        * artifact_sha256 (sha256 of parquet bytes)
      and stores coverage convenience fields.
    """
    stats_path, _, meta_path, tmp_meta_path = _stats_paths(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    if not stats_path.exists():
        raise FileNotFoundError(f"statistics not found: {stats_path}")

    # Fast path: meta exists, not forced
    if meta_path.exists() and not force:
        try:
            meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))

            if not isinstance(meta_raw, dict):
                raise ValueError("statistics meta is not a dict")

            meta = cast(Statistics1DMetaDict, meta_raw)

            artifact_now = sha256_file(stats_path)
            artifact_old = meta["artifact_sha256"]

            if artifact_old == artifact_now:
                origin = meta.get("meta_origin")

                # Case 1: modern meta with explicit origin
                if origin in {"ingest", "backfill_from_parquet"}:
                    return False  # meta is valid and up-to-date

                # Case 2: legacy meta without origin → upgrade in-place
                meta["meta_origin"] = "backfill_from_parquet"
                meta["updated_at"] = utc_now_run_ts()
                _atomic_write_json(meta_path, tmp_meta_path, meta)
                return True  # upgraded

            # If structure is unexpected, fall through to regenerate

        except Exception:
            # Corrupt meta -> regenerate
            pass
    # Recompute from parquet
    df = pd.read_parquet(stats_path)
    df = coerce_statistics_1d(
        df, dataset=dataset, schema="statistics", ensure_column_order=True
    )
    validate_statistics_1d(df)

    content_sha256 = hash_statistics_1d_content(df)
    artifact_sha256 = sha256_file(stats_path)

    if len(df) == 0:
        min_ts_event = None
        max_ts_event = None
    else:
        min_ts_event = fmt_run_ts(to_utc_ts(df["ts_event"].min()))
        max_ts_event = fmt_run_ts(to_utc_ts(df["ts_event"].max()))

    meta_out: Statistics1DMetaDict = {
        "schema": "statistics",
        "schema_version": "1",
        "mxm_schema_columns": list(STATISTICS_1D.columns),
        "dataset": dataset,
        "publisher_id": int(publisher_id),
        "instrument_id": int(instrument_id),
        "row_count": len(df),
        "min_ts_event": min_ts_event,
        "max_ts_event": max_ts_event,
        "content_sha256": content_sha256,
        "artifact_sha256": artifact_sha256,
        "meta_origin": "backfill_from_parquet",
        "updated_at": utc_now_run_ts(),
    }

    _atomic_write_json(meta_path, tmp_meta_path, meta_out)
    return True

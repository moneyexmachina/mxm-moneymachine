from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from mxm.v1.marketdata.schema.daily_stats import (
    DAILY_STATS,
    coerce_daily_stats,
    hash_daily_stats_content,
    validate_daily_stats,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.utils.hashing import sha256_file
from mxm.v1.utils.time_utils import fmt_day_ts, to_utc_ts, utc_now_run_ts


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _daily_stats_paths(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
) -> tuple[Path, Path, Path, Path]:
    """
    Return (out_path, tmp_path, meta_path, tmp_meta_path).
    """
    out_path = layout.daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    tmp_path = layout.tmp_daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )

    meta_path = out_path.with_name("daily_stats.meta.json")
    tmp_meta_path = out_path.with_name("daily_stats.meta.tmp.json")
    return out_path, tmp_path, meta_path, tmp_meta_path


def _atomic_write_json(path: Path, tmp_path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _build_daily_stats_meta(
    *,
    df: pd.DataFrame,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    artifact_sha256: str,
    source_content_sha256: str | None,
) -> dict[str, Any]:
    """
    Build canonical daily_stats meta payload from an already-coerced/validated dataframe.
    """
    content_sha256 = hash_daily_stats_content(df)

    if df.empty:
        min_session_date = None
        max_session_date = None
    else:
        # session_date is tz-aware UTC midnight; persist in canonical day timestamp string.
        min_session_date = fmt_day_ts(to_utc_ts(df["session_date"].min()).normalize())
        max_session_date = fmt_day_ts(to_utc_ts(df["session_date"].max()).normalize())

    meta: dict[str, Any] = {
        "schema": "daily_stats",
        "schema_version": "1",
        "mxm_schema_columns": list(DAILY_STATS.columns),
        "dataset": dataset,
        "publisher_id": int(publisher_id),
        "instrument_id": int(instrument_id),
        "row_count": len(df),
        "min_session_date": min_session_date,
        "max_session_date": max_session_date,
        "content_sha256": content_sha256,
        "artifact_sha256": artifact_sha256,
        "updated_at": utc_now_run_ts(),
    }

    if source_content_sha256 is not None:
        meta["source_schema"] = "statistics"
        meta["source_content_sha256"] = str(source_content_sha256)

    return meta


def read_daily_stats_meta(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
) -> dict[str, Any] | None:
    """
    Read the sidecar meta file for daily_stats, if present.
    Returns None if missing.
    """
    out_path = layout.daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    meta_path = out_path.with_name("daily_stats.meta.json")
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def ensure_daily_stats_meta(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    source_content_sha256: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure a valid daily_stats meta sidecar exists for an existing parquet.

    Idempotency rules:
    - If meta exists and its artifact_sha256 matches the current parquet bytes, and
      (if provided) source_content_sha256 matches, then do nothing.
    - Otherwise: read parquet, coerce+validate, compute content hash, and rewrite meta.

    Returns:
        The meta dict that is present on disk after this call.
    """
    out_path, _tmp_path, meta_path, tmp_meta_path = _daily_stats_paths(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    if not out_path.exists():
        raise FileNotFoundError(f"daily_stats not found: {out_path}")

    artifact_sha = sha256_file(out_path)

    if not force and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_artifact = meta.get("artifact_sha256")
            meta_source = meta.get("source_content_sha256")

            artifact_ok = (
                isinstance(meta_artifact, str) and meta_artifact == artifact_sha
            )
            source_ok = source_content_sha256 is None or (
                isinstance(meta_source, str) and meta_source == source_content_sha256
            )

            if artifact_ok and source_ok:
                return meta
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            # malformed meta -> fall through and rebuild
            pass

    # Rebuild from parquet content
    df = pd.read_parquet(out_path)
    df = coerce_daily_stats(df, ensure_column_order=True)
    validate_daily_stats(df)

    meta_new = _build_daily_stats_meta(
        df=df,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        artifact_sha256=artifact_sha,
        source_content_sha256=source_content_sha256,
    )
    _atomic_write_json(meta_path, tmp_meta_path, meta_new)
    return meta_new


def write_daily_stats(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    df_new: pd.DataFrame,
    source_content_sha256: str | None = None,
    skip_if_unchanged: bool = True,
) -> dict[str, Any]:
    """
    Persist derived daily_stats surface for a single instrument, and write a meta sidecar.

    Semantics (derived dataset):
    - full overwrite (no merge)
    - canonical sort by session_date
    - atomic write (tmp then replace)
    - optional idempotency: if content hash unchanged, do not rewrite parquet
      (but meta is ensured)

    Meta sidecar includes:
      - content_sha256 (semantic hash of canonicalised daily_stats)
      - artifact_sha256 (sha256 of parquet bytes)
      - (optional) source_content_sha256 (upstream statistics content hash)

    Returns metadata useful for orchestration/ledger.
    """
    out_path, tmp_path, meta_path, tmp_meta_path = _daily_stats_paths(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    _ensure_parent_dir(out_path)

    df_new = coerce_daily_stats(df_new, ensure_column_order=True)
    validate_daily_stats(df_new)

    sha_new = hash_daily_stats_content(df_new)

    if skip_if_unchanged and out_path.exists():
        df_old = pd.read_parquet(out_path)
        df_old = coerce_daily_stats(df_old, ensure_column_order=True)
        validate_daily_stats(df_old)

        sha_old = hash_daily_stats_content(df_old)
        if sha_old == sha_new:
            # Ensure meta is present and consistent with current parquet bytes.
            meta = ensure_daily_stats_meta(
                layout=layout,
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                source_content_sha256=source_content_sha256,
                force=False,
            )

            smin = (
                to_utc_ts(df_old["session_date"].min()).normalize()
                if not df_old.empty
                else None
            )
            smax = (
                to_utc_ts(df_old["session_date"].max()).normalize()
                if not df_old.empty
                else None
            )
            return {
                "wrote": False,
                "rows": len(df_old),
                "session_start": smin,
                "session_end": smax,
                "content_sha256": sha_old,
                "artifact_sha256": meta.get("artifact_sha256"),
                "meta_path": meta_path,
                "path": out_path,
            }

    # Atomic parquet write
    df_new.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)

    artifact_sha256 = sha256_file(out_path)
    meta = _build_daily_stats_meta(
        df=df_new,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        artifact_sha256=artifact_sha256,
        source_content_sha256=source_content_sha256,
    )
    _atomic_write_json(meta_path, tmp_meta_path, meta)

    smin = (
        to_utc_ts(df_new["session_date"].min()).normalize()
        if not df_new.empty
        else None
    )
    smax = (
        to_utc_ts(df_new["session_date"].max()).normalize()
        if not df_new.empty
        else None
    )
    return {
        "wrote": True,
        "rows": len(df_new),
        "session_start": smin,
        "session_end": smax,
        "content_sha256": meta["content_sha256"],
        "artifact_sha256": meta["artifact_sha256"],
        "meta_path": meta_path,
        "path": out_path,
    }


def read_daily_stats(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read derived daily_stats surface from the local store only.

    start/end are interpreted as [start, end) and applied on session_date.
    session_date is tz-aware UTC midnight timestamps.
    """
    out_path = layout.daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if not out_path.exists():
        raise FileNotFoundError(f"daily_stats not found: {out_path}")

    df = pd.read_parquet(out_path)
    df = coerce_daily_stats(df, ensure_column_order=True)
    validate_daily_stats(df)

    if start is not None:
        start = to_utc_ts(start).normalize()
        df = df[df["session_date"] >= start]

    if end is not None:
        end = to_utc_ts(end).normalize()
        df = df[df["session_date"] < end]

    return df.reset_index(drop=True)

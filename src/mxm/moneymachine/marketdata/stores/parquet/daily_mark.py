from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

from mxm.moneymachine.marketdata.schema.daily_mark import (
    DAILY_MARK,
    coerce_daily_mark,
    hash_daily_mark_content,
    validate_daily_mark,
)
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.utils.hashing import sha256_file
from mxm.moneymachine.utils.time_utils import utc_now_run_ts


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _daily_mark_paths(
    *,
    layout: MarketdataLayout,
    calendar_id: str,
    contract_id: str,
) -> tuple[Path, Path, Path, Path]:
    """
    Return (out_path, tmp_path, meta_path, tmp_meta_path).

    Storage granularity:
    - one daily_mark parquet surface per (calendar_id, contract_id)

    Identity semantics:
    - `calendar_id` is part of the dataset identity, not just sidecar metadata
    - `contract_id` identifies the contract-level valuation surface
    """
    out_path = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    tmp_path = layout.tmp_daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    meta_path = out_path.with_name("daily_mark.meta.json")
    tmp_meta_path = out_path.with_name("daily_mark.meta.tmp.json")
    return out_path, tmp_path, meta_path, tmp_meta_path


def _atomic_write_json(path: Path, tmp_path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _build_daily_mark_meta(
    *,
    df: pd.DataFrame,
    contract_id: str,
    calendar_id: str,
    artifact_sha256: str,
    source_content_sha256: str | None,
) -> dict[str, Any]:
    """
    Build canonical daily_mark meta payload from an already-coerced/validated dataframe.
    """
    content_sha256 = hash_daily_mark_content(df)
    if df.empty:
        min_session_id = None
        max_session_id = None
    else:
        min_session_id = int(df["session_id"].min())
        max_session_id = int(df["session_id"].max())
    quality_counts = {
        str(k): int(v)
        for k, v in df["mark_quality"].value_counts(dropna=False).sort_index().items()
    }

    meta: dict[str, Any] = {
        "schema": "daily_mark",
        "schema_version": "1",
        "mxm_schema_columns": list(DAILY_MARK.columns),
        "contract_id": str(contract_id),
        "calendar_id": str(calendar_id),
        "row_count": len(df),
        "min_session_id": min_session_id,
        "max_session_id": max_session_id,
        "content_sha256": content_sha256,
        "artifact_sha256": artifact_sha256,
        "updated_at": utc_now_run_ts(),
        "quality_counts": quality_counts,
    }

    if source_content_sha256 is not None:
        meta["source_schema"] = "daily_stats"
        meta["source_content_sha256"] = str(source_content_sha256)

    return meta


def read_daily_mark_meta(
    *,
    layout: MarketdataLayout,
    calendar_id: str,
    contract_id: str,
) -> dict[str, Any] | None:
    """
    Read the sidecar meta file for daily_mark, if present.

    Returns:
        Parsed meta dict, or None if missing.
    """
    out_path = layout.daily_mark_path(calendar_id=calendar_id, contract_id=contract_id)
    meta_path = out_path.with_name("daily_mark.meta.json")
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def ensure_daily_mark_meta(
    *,
    layout: MarketdataLayout,
    contract_id: str,
    calendar_id: str,
    source_content_sha256: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure a valid daily_mark meta sidecar exists for an existing parquet.

    Idempotency rules:
    - If meta exists and its artifact_sha256 matches the current parquet bytes, and
      (if provided) source_content_sha256 matches, and calendar_id matches,
      then do nothing.
    - Otherwise: read parquet, coerce+validate, compute content hash, and rewrite meta.

    Returns:
        The meta dict that is present on disk after this call.
    """
    out_path, _, meta_path, tmp_meta_path = _daily_mark_paths(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    if not out_path.exists():
        raise FileNotFoundError(f"daily_mark not found: {out_path}")

    artifact_sha = sha256_file(out_path)

    if not force and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_artifact = meta.get("artifact_sha256")
            meta_source = meta.get("source_content_sha256")
            meta_calendar_id = meta.get("calendar_id")

            artifact_ok = (
                isinstance(meta_artifact, str) and meta_artifact == artifact_sha
            )
            source_ok = source_content_sha256 is None or (
                isinstance(meta_source, str) and meta_source == source_content_sha256
            )
            calendar_ok = (
                isinstance(meta_calendar_id, str) and meta_calendar_id == calendar_id
            )

            if artifact_ok and source_ok and calendar_ok:
                return meta
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            # malformed meta -> fall through and rebuild
            pass

    df = pd.read_parquet(out_path)
    df = coerce_daily_mark(df, ensure_column_order=True)
    validate_daily_mark(df)

    meta_new = _build_daily_mark_meta(
        df=df,
        contract_id=contract_id,
        calendar_id=calendar_id,
        artifact_sha256=artifact_sha,
        source_content_sha256=source_content_sha256,
    )
    _atomic_write_json(meta_path, tmp_meta_path, meta_new)
    return meta_new


class DailyMarkWriteResult(TypedDict):
    wrote: bool
    rows: int
    min_session_id: int | None
    max_session_id: int | None
    content_sha256: str
    artifact_sha256: str | None
    meta_path: Path
    path: Path
    calendar_id: str


def write_daily_mark(
    *,
    layout: MarketdataLayout,
    contract_id: str,
    calendar_id: str,
    df_new: pd.DataFrame,
    source_content_sha256: str | None = None,
    skip_if_unchanged: bool = True,
) -> DailyMarkWriteResult:
    """
    Persist curated daily_mark surface for a single contract, and write a meta sidecar.

    Semantics (curated dataset):
    - full overwrite (no merge)
    - canonical sort by session_id
    - atomic write (tmp then replace)
    - optional idempotency: if content hash unchanged, do not rewrite parquet
      (but meta is ensured)

    Meta sidecar includes:
      - calendar identity
      - content_sha256 (semantic hash of canonicalised daily_mark)
      - artifact_sha256 (sha256 of parquet bytes)
      - (optional) source_content_sha256 (upstream source surface hash)

    Returns metadata useful for orchestration/ledger.
    """
    out_path, tmp_path, meta_path, _ = _daily_mark_paths(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    _ensure_parent_dir(out_path)

    df_new = coerce_daily_mark(df_new, ensure_column_order=True)
    validate_daily_mark(df_new)

    unique_contract_ids = df_new["contract_id"].dropna().unique().tolist()
    if len(unique_contract_ids) != 1 or str(unique_contract_ids[0]) != contract_id:
        raise ValueError(
            "write_daily_mark requires dataframe content to match requested contract_id: "
            f"expected {contract_id!r}, got {unique_contract_ids!r}"
        )

    sha_new = hash_daily_mark_content(df_new)

    if skip_if_unchanged and out_path.exists():
        df_old = pd.read_parquet(out_path)
        df_old = coerce_daily_mark(df_old, ensure_column_order=True)
        validate_daily_mark(df_old)

        sha_old = hash_daily_mark_content(df_old)
        if sha_old == sha_new:
            meta = ensure_daily_mark_meta(
                layout=layout,
                contract_id=contract_id,
                calendar_id=calendar_id,
                source_content_sha256=source_content_sha256,
                force=False,
            )

            smin = df_old["session_id"].min() if not df_old.empty else None
            smax = df_old["session_id"].max() if not df_old.empty else None

            return {
                "wrote": False,
                "rows": len(df_old),
                "min_session_id": smin,
                "max_session_id": smax,
                "content_sha256": sha_old,
                "artifact_sha256": meta.get("artifact_sha256"),
                "meta_path": meta_path,
                "path": out_path,
                "calendar_id": calendar_id,
            }

    df_new.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)

    artifact_sha256 = sha256_file(out_path)
    meta = _build_daily_mark_meta(
        df=df_new,
        contract_id=contract_id,
        calendar_id=calendar_id,
        artifact_sha256=artifact_sha256,
        source_content_sha256=source_content_sha256,
    )

    meta_path = out_path.with_name("daily_mark.meta.json")
    tmp_meta_path = out_path.with_name("daily_mark.meta.tmp.json")
    _atomic_write_json(meta_path, tmp_meta_path, meta)

    smin = df_new["session_id"].min() if not df_new.empty else None
    smax = df_new["session_id"].max() if not df_new.empty else None

    return {
        "wrote": True,
        "rows": len(df_new),
        "min_session_id": smin,
        "max_session_id": smax,
        "content_sha256": meta["content_sha256"],
        "artifact_sha256": meta["artifact_sha256"],
        "meta_path": meta_path,
        "path": out_path,
        "calendar_id": calendar_id,
    }


def read_daily_mark(
    *,
    layout: MarketdataLayout,
    calendar_id: str,
    contract_id: str,
    start_session_id: int | None = None,
    end_session_id: int | None = None,
) -> pd.DataFrame:
    """
    Read curated daily_mark surface from the local store only.

    start_session_id / end_session_id are interpreted as [start, end) and
    applied on `session_id`.

    Semantics:
    - `session_id` is the primary MXM business-session coordinate
    """
    out_path = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    if not out_path.exists():
        raise FileNotFoundError(f"daily_mark not found: {out_path}")

    df = pd.read_parquet(out_path)
    df = coerce_daily_mark(df, ensure_column_order=True)
    validate_daily_mark(df)

    if start_session_id is not None:
        df = df[df["session_id"] >= start_session_id]

    if end_session_id is not None:
        df = df[df["session_id"] < end_session_id]

    return df.reset_index(drop=True)

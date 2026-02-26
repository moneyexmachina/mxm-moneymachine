from __future__ import annotations

"""
MXM V1 — Canonical hashing utilities.

Intent
------
Provide a single, explicit hashing authority for V1.

We distinguish clearly between:

1) Artifact hashing (file bytes)
2) Canonical structured hashing (JSON payloads)
3) DataFrame content hashing (order-invariant idempotency)
4) Deterministic row hashing (tie-breakers)

No other module in V1 should import hashlib directly.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

# ============================================================================
# Low-level primitives
# ============================================================================


def sha256_bytes(data: bytes) -> str:
    """
    SHA256 of raw bytes.
    """
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """
    SHA256 of UTF-8 encoded text.
    """
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """
    Compute SHA256 hex digest for a file (artifact hash).

    Notes
    -----
    This hashes file bytes exactly. It is sensitive to encoding,
    compression, parquet row-groups, etc.

    Suitable for:
        - artifact integrity
        - store-level fingerprinting

    Not suitable for:
        - logical content equality across re-encodings
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_bytes), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================================
# Canonical structured hashing
# ============================================================================


def _canonical_json_dumps(obj: Any) -> str:
    """
    Deterministic JSON encoding.

    - Sorted keys
    - Compact separators
    - UTF-8 safe
    - No whitespace variance
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,  # fallback for e.g. pd.Timestamp (explicit choice)
    )


def sha256_json(obj: Any) -> str:
    """
    SHA256 of canonical JSON encoding of a Python object.

    Intended for:
        - request hashes
        - migration hashes
        - event UIDs
        - canonical payload hashing
    """
    return sha256_text(_canonical_json_dumps(obj))


# ============================================================================
# DataFrame content hashing (idempotency)
# ============================================================================


def sha256_df_content(
    df: pd.DataFrame,
    *,
    coerce: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> str:
    """
    Stable content hash of a DataFrame.

    Guarantees:
    - Column-order invariant
    - Row-order invariant
    - Index ignored
    - Depends only on values + column names

    Parameters
    ----------
    df:
        Input dataframe.
    coerce:
        Optional canonicalisation function applied before hashing
        (e.g. coerce_daily_stats, coerce_statistics_1d).

    Returns
    -------
    str
        SHA256 hex digest.
    """
    if coerce is not None:
        df = coerce(df)

    if df.empty:
        # Stable empty-frame fingerprint
        return sha256_text("mxm-empty-dataframe")

    # Canonical column order (sorted by name)
    df2 = df.copy()
    df2 = df2.reindex(sorted(df2.columns), axis=1)

    # Canonical row order (lexicographic by all columns)
    df2 = df2.sort_values(list(df2.columns), kind="mergesort").reset_index(drop=True)

    # pandas produces stable uint64 per-row hashes
    row_hashes = pd.util.hash_pandas_object(df2, index=False).to_numpy(dtype=np.uint64)

    return sha256_bytes(row_hashes.tobytes())


# ============================================================================
# Deterministic per-row hashing (tie-breakers)
# ============================================================================


def sha256_df_rows(
    df: pd.DataFrame,
    *,
    cols: list[str],
) -> pd.Series:
    """
    Deterministic per-row hash (uint64) for selected columns.

    Intended for:
        - final tie-break in selection logic
        - deterministic ordering when timestamps identical

    Notes
    -----
    - Returns uint64 (fast, compact)
    - Column order is respected exactly as provided
    - Does NOT sort rows
    """
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns for row hash: {missing}")

    sub = df[cols]

    return pd.util.hash_pandas_object(sub, index=False)

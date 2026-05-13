from __future__ import annotations

import pandas as pd

from mxm.v1.utils.time_utils import ensure_utc_datetime_series


def normalize_instrument_definitions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize Databento instrument definition frames (schema="definition").

    Contract:
    - This function is column-only and must not rely on / manipulate index semantics.
    - The Databento fetcher must have materialised any meaningful index into columns
      prior to DataIO serialisation. In particular, 'ts_recv' must already be a column.

    Output guarantees:
    - 'ts_recv' column exists, tz-aware UTC
    - 'ts_event' column exists, tz-aware UTC
    - DataFrame returned with RangeIndex semantics (we reset to RangeIndex defensively)
    """
    out = df.copy()

    # Empty: still enforce presence/dtypes for downstream code paths
    if out.empty:
        if "ts_recv" not in out.columns:
            out["ts_recv"] = pd.Series(dtype="datetime64[ns, UTC]")
        if "ts_event" not in out.columns:
            out["ts_event"] = pd.Series(dtype="datetime64[ns, UTC]")
        return out.reset_index(drop=True)

    # Required columns
    if "ts_event" not in out.columns:
        raise ValueError(
            "Missing required column 'ts_event' in instrument definitions."
        )
    if "ts_recv" not in out.columns:
        raise ValueError(
            "Missing required column 'ts_recv' in instrument definitions. "
            "Fetcher must materialise the vendor index into a 'ts_recv' column."
        )

    # Coerce to tz-aware UTC
    out["ts_event"] = ensure_utc_datetime_series(out["ts_event"])
    out["ts_recv"] = ensure_utc_datetime_series(out["ts_recv"])

    # Do not allow callers to accidentally depend on index semantics
    return out.reset_index(drop=True)

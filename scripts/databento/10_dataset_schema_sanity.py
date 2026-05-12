"""
Proof 1 — Dataset + schema sanity (metadata-only; no billable time-series pulls)

Goal:
- Confirm Databento auth via mxm_secrets works.
- Confirm GLBX.MDP3 is visible.
- Confirm ohlcv-1d is available for GLBX.MDP3 via metadata.list_schemas().
- Record entitled dataset range via metadata.get_dataset_range().
- Record canonical field list for ohlcv-1d via metadata.list_fields(schema, encoding).
- (Optional) Capture publisher mapping via metadata.list_publishers() filtered for GLBX.MDP3.

Non-goals:
- No symbol discovery.
- No time-series requests.
- No persistence.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import databento as db
from mxm_secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1d"
FIELDS_ENCODING = "csv"  # choose: "csv", "json", or "dbn"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    # --- Auth ---
    try:
        api_key = get_secret(API_KEY_SECRET)
    except Exception as e:
        print(f"ERROR: failed to load secret '{API_KEY_SECRET}': {e}", file=sys.stderr)
        return 1

    if not api_key or not isinstance(api_key, str):
        print(
            f"ERROR: secret '{API_KEY_SECRET}' was empty or not a string",
            file=sys.stderr,
        )
        return 1

    client = db.Historical(api_key)

    # --- Dataset visibility ---
    try:
        datasets = client.metadata.list_datasets()
    except Exception as e:
        print(f"ERROR: metadata.list_datasets failed: {e}", file=sys.stderr)
        return 1

    dataset_visible = DATASET in set(datasets)
    if not dataset_visible:
        print("=" * 80)
        print("MXM V1 — Databento Proof 1: Dataset + schema sanity")
        print("=" * 80)
        print(f"Timestamp (UTC): {_utc_now_iso()}")
        print(f"Auth:            mxm_secrets.get_secret('{API_KEY_SECRET}')")
        print(f"Dataset target:  {DATASET}")
        print("Result:          DATASET NOT VISIBLE TO ACCOUNT")
        print("-" * 80)
        print("Visible dataset IDs:")
        print(json.dumps(sorted(datasets), indent=2))
        print("=" * 80)
        return 2

    # --- List schemas available for dataset ---
    try:
        schemas = client.metadata.list_schemas(DATASET)
    except Exception as e:
        print(f"ERROR: metadata.list_schemas({DATASET}) failed: {e}", file=sys.stderr)
        return 1

    schema_available = SCHEMA in set(schemas)

    # --- List fields for schema + encoding (schema-scoped, not dataset-scoped) ---
    try:
        fields = client.metadata.list_fields(schema=SCHEMA, encoding=FIELDS_ENCODING)
    except Exception as e:
        print(
            f"ERROR: metadata.list_fields(schema={SCHEMA}, encoding={FIELDS_ENCODING}) failed: {e}",
            file=sys.stderr,
        )
        return 1

    # --- Dataset entitled range ---
    dataset_range = None
    try:
        dataset_range = client.metadata.get_dataset_range(DATASET)
    except Exception as e:
        dataset_range = {
            "warning": f"metadata.get_dataset_range({DATASET}) failed: {e}"
        }

    # --- Optional: publisher mapping (can be noisy; we filter to matching dataset code if present) ---
    publishers_filtered = None
    try:
        publishers = client.metadata.list_publishers()
        # publishers are dicts; they typically include dataset/venue mapping keys.
        # We filter by any field value matching DATASET.
        publishers_filtered = [
            p for p in publishers if any(str(v) == DATASET for v in p.values())
        ]
    except Exception as e:
        publishers_filtered = [{"warning": f"metadata.list_publishers failed: {e}"}]

    # --- Output block for docs ---
    print("=" * 80)
    print("MXM V1 — Databento Proof 1: Dataset + schema sanity")
    print("=" * 80)
    print(f"Timestamp (UTC): {_utc_now_iso()}")
    print(f"Auth:            mxm_secrets.get_secret('{API_KEY_SECRET}')")
    print(f"Dataset:         {DATASET}")
    print(f"Target schema:   {SCHEMA}")
    print(f"Fields encoding: {FIELDS_ENCODING}")
    print("-" * 80)

    schemas_sorted = sorted(schemas)
    print("Schemas available for dataset (excerpt):")
    print(json.dumps(schemas_sorted[:80], indent=2))
    if len(schemas_sorted) > 80:
        print(f"... ({len(schemas_sorted)} total schemas)")
    print(f"Target schema present? {schema_available}")
    print("-" * 80)

    print("Entitled dataset range (metadata.get_dataset_range):")
    print(json.dumps(dataset_range, indent=2, sort_keys=True, default=str))
    print("-" * 80)

    print(
        f"Fields for schema={SCHEMA} encoding={FIELDS_ENCODING} (metadata.list_fields):"
    )
    print(json.dumps(fields, indent=2, ensure_ascii=False))
    print("-" * 80)

    print("Publishers filtered for dataset match (metadata.list_publishers):")
    print(json.dumps(publishers_filtered, indent=2, sort_keys=True, default=str))
    print("=" * 80)

    # Distinct return code if the schema is missing, to make it obvious in CI / logs.
    return 0 if schema_available else 3


if __name__ == "__main__":
    raise SystemExit(main())

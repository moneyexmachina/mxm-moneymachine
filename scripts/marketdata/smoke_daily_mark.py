from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from mxm.v1.calendars.mxm_business_calendar_service import MXMBusinessCalendarService
from mxm.v1.marketdata.datasets.daily_mark.store import DailyMarkStore
from mxm.v1.marketdata.orchestrators.daily_mark import derive_daily_mark_for_product
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.utils.date_utils import coerce_np_day
from mxm.v1.utils.time_utils import utc_now_run_ts


def _to_jsonable(obj: object) -> object:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, np.datetime64):
        return str(obj.astype("datetime64[D]"))
    if isinstance(obj, Path):
        return str(obj)
    return {"__repr__": repr(obj)}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="smoke_daily_marks",
        description="Smoke-test daily_mark derivation for a product.",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--calendar-id",
        default="mxm_business_days_v1",
        help="MXM business calendar identifier.",
    )
    p.add_argument(
        "--calendar-start",
        default="2010-01-01",
        help="Inclusive MXM business calendar start label (YYYY-MM-DD).",
    )
    p.add_argument(
        "--calendar-end",
        default="2050-12-31",
        help="Inclusive MXM business calendar end label (YYYY-MM-DD).",
    )
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="bootstrap",
        help="bootstrap: all contracts; update: currently same enumeration behaviour unless orchestrator changes.",
    )
    p.add_argument("--max-contracts", type=int, default=None)
    p.add_argument(
        "--contract-id",
        action="append",
        default=None,
        help="Optional explicit contract_id to restrict build to. Repeatable.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write daily_mark parquet/meta; report what would be built/skipped.",
    )
    p.add_argument(
        "--force-reset",
        action="store_true",
        help="Delete local daily_mark parquet+meta for touched identities before rebuilding.",
    )
    p.add_argument("--root", type=str, default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    now_iso = utc_now_run_ts()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    layout = MarketdataLayout(root=root)
    daily_mark_store = DailyMarkStore(layout=layout)

    calendar_service = MXMBusinessCalendarService(
        calendar_base_id=str(args.calendar_id),
        start_label=coerce_np_day(args.calendar_start),
        end_label=coerce_np_day(args.calendar_end),
    )
    business_calendar = calendar_service.get_calendar()

    contract_ids: set[str] | None
    if args.contract_id is None:
        contract_ids = None
    else:
        contract_ids = set(args.contract_id)

    print("\nMXM V1 — smoke: daily_mark")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] calendar_base_id={args.calendar_id}")
    print(f"[calendar] calendar_id={calendar_service.calendar_id}")
    print(f"[args] calendar_start={args.calendar_start}")
    print(f"[args] calendar_end={args.calendar_end}")
    print(f"[args] mode={args.mode}")
    print(f"[args] max_contracts={args.max_contracts}")
    print(f"[args] contract_ids={contract_ids if contract_ids is not None else 'ALL'}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] force_reset={bool(args.force_reset)}")
    print(f"[args] root={root}")
    print(f"[calendar] session_count={len(business_calendar.session_ids)}")

    report = derive_daily_mark_for_product(
        product_id=args.product_id,
        calendar_id=str(business_calendar.calendar_id),
        business_calendar=business_calendar,
        daily_mark_store=daily_mark_store,
        root=root,
        mode=args.mode,
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        contract_ids=contract_ids,
        dry_run=bool(args.dry_run),
        force_reset=bool(args.force_reset),
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()

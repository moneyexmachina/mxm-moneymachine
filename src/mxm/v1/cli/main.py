from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from mxm.v1.marketdata.datasets.instrument_definitions.jobs import (
    Mode,
    update_instrument_definitions_for_product,
)
from mxm.v1.utils.json_normalise import json_value_from_obj


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mxm")
    subparsers = parser.add_subparsers(dest="command_group", required=True)

    marketdata = subparsers.add_parser("marketdata")
    marketdata_subparsers = marketdata.add_subparsers(
        dest="marketdata_command", required=True
    )

    instrument_definitions = marketdata_subparsers.add_parser("instrument-definitions")
    instrument_definitions_subparsers = instrument_definitions.add_subparsers(
        dest="instrument_definitions_action",
        required=True,
    )

    update = instrument_definitions_subparsers.add_parser("update")
    update.add_argument("--product-id", required=True)
    update.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
    )
    update.add_argument("--cost-cap-usd", type=float, required=True)
    update.add_argument("--window-days", type=int, default=31)
    update.add_argument("--max-windows", type=int, default=3)
    update.add_argument("--overlap", type=str, default="1d")
    update.add_argument("--reset", action="store_true")
    update.add_argument("--end", type=str, default=None)
    update.add_argument("--root", type=Path, default=None)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if (
        args.command_group == "marketdata"
        and args.marketdata_command == "instrument-definitions"
        and args.instrument_definitions_action == "update"
    ):
        report = update_instrument_definitions_for_product(
            product_id=str(args.product_id),
            mode=cast(Mode, args.mode),
            cost_cap_usd=float(args.cost_cap_usd),
            window_days=int(args.window_days),
            overlap=str(args.overlap),
            max_windows=int(args.max_windows),
            reset=bool(args.reset),
            end=args.end,
            root=args.root,
        )
        print(json.dumps(json_value_from_obj(report), indent=2, sort_keys=False))
        return

    raise RuntimeError("Unhandled command path")


if __name__ == "__main__":
    main()

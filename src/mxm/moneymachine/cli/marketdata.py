from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from mxm.moneymachine.marketdata.datasets.instrument_definitions.ingest import Mode
from mxm.moneymachine.marketdata.ops.instrument_definitions import (
    InstrumentDefinitionsRunRequest,
    run_instrument_definitions,
)
from mxm.moneymachine.runtime.execution_context import cli_execution_context
from mxm.moneymachine.utils.json_normalise import json_value_from_obj


def add_marketdata_parser(root_parser: argparse.ArgumentParser) -> None:
    root_subparsers = root_parser.add_subparsers(
        dest="command_group",
        required=True,
    )

    marketdata = root_subparsers.add_parser("marketdata")
    _configure_marketdata_parser(marketdata)


def _configure_marketdata_parser(marketdata_parser: argparse.ArgumentParser) -> None:
    marketdata_subparsers = marketdata_parser.add_subparsers(
        dest="marketdata_command",
        required=True,
    )

    instrument_definitions = marketdata_subparsers.add_parser("instrument-definitions")
    _configure_instrument_definitions_parser(instrument_definitions)

    instrument_definition_mappings = marketdata_subparsers.add_parser(
        "instrument-definition-mappings"
    )
    _configure_instrument_definition_mappings_parser(instrument_definition_mappings)


def _configure_instrument_definitions_parser(
    parser: argparse.ArgumentParser,
) -> None:
    subparsers = parser.add_subparsers(
        dest="instrument_definitions_action",
        required=True,
    )

    update = subparsers.add_parser("update")
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
    update.add_argument(
        "--databento-api-key-secret-path",
        type=str,
        default="mxm/dev/databento/api-key",
    )


def _configure_instrument_definition_mappings_parser(
    parser: argparse.ArgumentParser,
) -> None:
    subparsers = parser.add_subparsers(
        dest="instrument_definition_mappings_action",
        required=True,
    )

    rebuild = subparsers.add_parser("rebuild")
    rebuild.add_argument("--product-id", required=True)
    rebuild.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
    )
    rebuild.add_argument("--reset", action="store_true")
    rebuild.add_argument("--root", type=Path, default=None)


def dispatch_marketdata(args: argparse.Namespace) -> None:
    if (
        args.marketdata_command == "instrument-definitions"
        and args.instrument_definitions_action == "update"
    ):
        report = run_instrument_definitions(
            request=InstrumentDefinitionsRunRequest(
                product_id=args.product_id,
                mode=cast(Mode, args.mode),
                cost_cap_usd=args.cost_cap_usd,
                window_days=args.window_days,
                overlap=args.overlap,
                max_windows=args.max_windows,
                reset=args.reset,
                end=args.end,
                databento_api_key_secret_path=args.databento_api_key_secret_path,
            ),
            execution_context=cli_execution_context(),
        )

        print(json.dumps(json_value_from_obj(report), indent=2, sort_keys=False))
        return

    raise RuntimeError("Unhandled marketdata command path")

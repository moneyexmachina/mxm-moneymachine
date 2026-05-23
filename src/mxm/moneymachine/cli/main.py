from __future__ import annotations

import argparse

from mxm.moneymachine.cli.marketdata import add_marketdata_parser, dispatch_marketdata


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mxm")
    add_marketdata_parser(parser)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command_group == "marketdata":
        dispatch_marketdata(args)
        return

    raise RuntimeError("Unhandled command group")


if __name__ == "__main__":
    main()

"""
Proof 2 — Instrument discovery (outright contract symbol resolution)

Goal:
- Determine which outright futures symbols for a chosen root (ES) resolve in GLBX.MDP3.
- Produce a short list of concrete symbols we can use in Proof 3/4.

Approach:
- Generate a small candidate set (e.g. ESH6, ESM6, ESU6, ESZ6, plus nearby years).
- Use client.symbology to resolve to instrument IDs for a date window.

Non-goals:
- No time-series pulls.
- No continuous/rolled symbols.
- No spreads/options.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import cast

import databento as db

from mxm.secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"
DATASET = "GLBX.MDP3"

ROOT = "ES"
MONTH_CODES = ["H", "M", "U", "Z"]  # quarterly cycle; expand later if needed


@dataclass(frozen=True)
class ResolutionWindow:
    today: date
    start_date: date
    end_date: date
    years: list[int]


Resolver = Callable[..., object]


def generate_candidates(root: str, years: list[int], months: list[str]) -> list[str]:
    candidates: list[str] = []

    for year in years:
        yy2 = f"{year % 100:02d}"
        yy1 = f"{year % 10:d}"

        for month_code in months:
            candidates.append(f"{root}{month_code}{yy2}")
            candidates.append(f"{root}{month_code}{yy1}")

    seen: set[str] = set()
    out: list[str] = []

    for symbol in candidates:
        if symbol in seen:
            continue
        out.append(symbol)
        seen.add(symbol)

    return out


def main() -> int:
    client = _make_client()
    window = _resolution_window()
    candidates = generate_candidates(ROOT, years=window.years, months=MONTH_CODES)

    resolver_info = _find_symbology_resolver(client)
    if resolver_info is None:
        _print_missing_resolver_error(client)
        return 2

    resolver_name, resolver = resolver_info

    try:
        result = _resolve_candidates(
            resolver=resolver,
            resolver_name=resolver_name,
            candidates=candidates,
            window=window,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    pairs = _normalize_resolution_result(result)
    resolved = _resolved_pairs(pairs)

    _print_resolution_report(
        candidates=candidates,
        resolved=resolved,
        window=window,
    )
    return 0


def _make_client() -> db.Historical:
    api_key = get_secret(API_KEY_SECRET)
    return db.Historical(api_key)


def _resolution_window() -> ResolutionWindow:
    today = date.today()
    return ResolutionWindow(
        today=today,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=365),
        years=[today.year - 1, today.year, today.year + 1],
    )


def _find_symbology_resolver(client: db.Historical) -> tuple[str, Resolver] | None:
    if not hasattr(client, "symbology"):
        return None

    for name in ("resolve", "resolve_symbols", "resolve_symbol"):
        candidate = getattr(client.symbology, name, None)
        if callable(candidate):
            return name, candidate

    return None


def _print_missing_resolver_error(client: db.Historical) -> None:
    if not hasattr(client, "symbology"):
        print(
            "ERROR: client.symbology is not available on this client.",
            file=sys.stderr,
        )
        return

    print(
        "ERROR: Could not find a symbology resolve method on client.symbology.",
        file=sys.stderr,
    )
    print(
        "Available methods:",
        [name for name in dir(client.symbology) if not name.startswith("_")],
        file=sys.stderr,
    )


def _resolve_candidates(
    *,
    resolver: Resolver,
    resolver_name: str,
    candidates: list[str],
    window: ResolutionWindow,
) -> object:
    try:
        return resolver(
            dataset=DATASET,
            symbols=candidates,
            stype_in="raw_symbol",
            stype_out="instrument_id",
            start_date=window.start_date,
            end_date=window.end_date,
        )
    except TypeError:
        return _resolve_candidates_with_as_of_fallback(
            resolver=resolver,
            resolver_name=resolver_name,
            candidates=candidates,
            today=window.today,
        )
    except Exception as e:
        raise RuntimeError(f"symbology.{resolver_name} failed: {e}") from e


def _resolve_candidates_with_as_of_fallback(
    *,
    resolver: Resolver,
    resolver_name: str,
    candidates: list[str],
    today: date,
) -> object:
    try:
        return resolver(
            dataset=DATASET,
            symbols=candidates,
            stype_in="raw_symbol",
            stype_out="instrument_id",
            as_of=today,
        )
    except Exception as e:
        raise RuntimeError(
            f"symbology.{resolver_name} failed with fallback signature: {e}\n"
            "Tip: print dir(client.symbology) and inspect help() for the method signature."
        ) from e


def _normalize_resolution_result(result: object) -> list[tuple[str, str]]:
    if isinstance(result, dict):
        result_dict = cast(dict[object, object], result)
        return _normalize_resolution_dict(result_dict)

    if isinstance(result, list):
        result_list = cast(list[object], result)
        return _normalize_resolution_list(result_list)

    print(
        f"WARNING: unexpected result type from symbology resolver: {type(result)}",
        file=sys.stderr,
    )
    return [("RAW_RESULT_REPR", repr(result)[:500])]


def _normalize_resolution_dict(result: dict[object, object]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    for key, value in result.items():
        pairs.append(_normalize_resolution_dict_item(key=key, value=value))

    return pairs


def _normalize_resolution_dict_item(*, key: object, value: object) -> tuple[str, str]:
    if isinstance(value, int):
        return str(key), str(value)

    if _is_nonempty_int_list(value):
        values = cast(list[int], value)
        return str(key), str(values[0])

    if not isinstance(value, dict):
        return str(key), f"UNPARSED:{_safe_repr(value, max_len=120)}"

    value_dict = cast(dict[object, object], value)
    if "instrument_id" in value_dict:
        return str(key), str(value_dict["instrument_id"])

    return str(key), f"UNPARSED:{_safe_repr(value_dict, max_len=120)}"


def _safe_repr(value: object, *, max_len: int) -> str:
    return repr(value)[:max_len]


def _is_nonempty_int_list(value: object) -> bool:
    if not isinstance(value, list):
        return False

    values = cast(list[object], value)
    return bool(values) and isinstance(values[0], int)


def _normalize_resolution_list(result: list[object]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    for row in result:
        pair = _normalize_resolution_list_row(row)
        if pair is not None:
            pairs.append(pair)

    return pairs


def _normalize_resolution_list_row(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None

    row_dict = cast(dict[object, object], row)

    symbol = _first_present_value(
        row_dict,
        keys=("symbol", "input_symbol", "raw_symbol"),
    )
    instrument_id = _first_present_value(
        row_dict,
        keys=("instrument_id", "output_symbol"),
    )

    if symbol is None or instrument_id is None:
        return None

    return str(symbol), str(instrument_id)


def _first_present_value(
    mapping: dict[object, object],
    *,
    keys: tuple[str, ...],
) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value

    return None


def _resolved_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (symbol, instrument_id)
        for symbol, instrument_id in pairs
        if not instrument_id.startswith("UNPARSED") and symbol != "RAW_RESULT_REPR"
    ]


def _print_resolution_report(
    *,
    candidates: list[str],
    resolved: list[tuple[str, str]],
    window: ResolutionWindow,
) -> None:
    print("=" * 80)
    print("MXM V1 — Databento Proof 2: Symbology resolution (outright candidates)")
    print("=" * 80)
    print(f"Dataset:  {DATASET}")
    print(f"Root:     {ROOT}")
    print(f"Window:   {window.start_date} -> {window.end_date}")
    print("-" * 80)
    print(f"Candidates generated: {len(candidates)}")
    print(f"Resolved candidates:  {len(resolved)}")
    print("-" * 80)

    if resolved:
        _print_resolved_pairs(resolved)
    else:
        _print_no_resolved_candidates_message()

    print("=" * 80)


def _print_resolved_pairs(resolved: list[tuple[str, str]]) -> None:
    print("Resolved symbol -> instrument_id:")
    for symbol, instrument_id in sorted(resolved)[:50]:
        print(f"{symbol:8s}  {instrument_id}")

    if len(resolved) > 50:
        print(f"... ({len(resolved)} total)")


def _print_no_resolved_candidates_message() -> None:
    print("No candidates resolved. Likely causes:")
    print("- wrong year format (1-digit vs 2-digit)")
    print("- dataset expects different symbol convention")
    print("- need to use stype_in different from raw_symbol (e.g. parent, continuous)")
    print("- the symbology resolver signature differs in this client version")


if __name__ == "__main__":
    raise SystemExit(main())

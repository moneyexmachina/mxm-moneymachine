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
from datetime import date, timedelta

import databento as db
from mxm_secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"
DATASET = "GLBX.MDP3"

ROOT = "ES"
MONTH_CODES = ["H", "M", "U", "Z"]  # quarterly cycle; expand later if needed


def generate_candidates(root: str, years: list[int], months: list[str]) -> list[str]:
    # Databento/CME common shorthand uses 1-2 digit years in many contexts.
    # We generate both 1-digit and 2-digit to see what resolves in your account.
    cands = []
    for y in years:
        yy2 = f"{y % 100:02d}"  # 2-digit
        yy1 = f"{y % 10:d}"  # 1-digit
        for m in months:
            cands.append(f"{root}{m}{yy2}")
            cands.append(f"{root}{m}{yy1}")
    # Deduplicate while preserving order
    seen = set()
    out = []
    for s in cands:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def main() -> int:
    api_key = get_secret(API_KEY_SECRET)
    client = db.Historical(api_key)

    today = date.today()
    # Symbology resolution typically needs an "as of" date; we use a conservative window.
    start_date = today - timedelta(days=30)
    end_date = today + timedelta(days=365)

    years = [today.year - 1, today.year, today.year + 1]
    candidates = generate_candidates(ROOT, years=years, months=MONTH_CODES)

    # Inspect symbology surface quickly if needed
    if not hasattr(client, "symbology"):
        print(
            "ERROR: client.symbology is not available on this client.", file=sys.stderr
        )
        return 2

    # We do not assume exact method name; we try the common ones.
    # 1) resolve()
    # 2) resolve_symbols()
    resolver = None
    for name in ("resolve", "resolve_symbols", "resolve_symbol"):
        if hasattr(client.symbology, name):
            resolver = getattr(client.symbology, name)
            resolver_name = name
            break

    if resolver is None:
        print(
            "ERROR: Could not find a symbology resolve method on client.symbology.",
            file=sys.stderr,
        )
        print(
            "Available methods:",
            [m for m in dir(client.symbology) if not m.startswith("_")],
            file=sys.stderr,
        )
        return 2

    # Attempt resolution. Different versions accept slightly different parameters.
    # We start with the most likely signature.
    try:
        result = resolver(
            dataset=DATASET,
            symbols=candidates,
            stype_in="raw_symbol",
            stype_out="instrument_id",
            start_date=start_date,
            end_date=end_date,
        )
    except TypeError:
        # Fall back to using an "as_of" date if window params are not accepted
        try:
            result = resolver(
                dataset=DATASET,
                symbols=candidates,
                stype_in="raw_symbol",
                stype_out="instrument_id",
                as_of=today,
            )
        except Exception as e:
            print(
                f"ERROR: symbology.{resolver_name} failed with fallback signature: {e}",
                file=sys.stderr,
            )
            print(
                "Tip: print dir(client.symbology) and inspect help() for the method signature.",
                file=sys.stderr,
            )
            return 1
    except Exception as e:
        print(f"ERROR: symbology.{resolver_name} failed: {e}", file=sys.stderr)
        return 1

    # The result shape varies: sometimes dict[symbol] -> instrument_id(s), sometimes list of mappings.
    # We normalize best-effort into a list of (symbol, instrument_id) pairs.
    pairs: list[tuple[str, str]] = []

    if isinstance(result, dict):
        for k, v in result.items():
            # v may be int, list[int], dict, etc.
            if isinstance(v, int):
                pairs.append((str(k), str(v)))
            elif isinstance(v, list) and v and isinstance(v[0], int):
                pairs.append((str(k), str(v[0])))
            elif isinstance(v, dict) and "instrument_id" in v:
                pairs.append((str(k), str(v["instrument_id"])))
            else:
                # keep a repr for debugging
                pairs.append((str(k), f"UNPARSED:{repr(v)[:120]}"))
    elif isinstance(result, list):
        # list of dict mappings
        for row in result:
            if isinstance(row, dict):
                sym = (
                    row.get("symbol")
                    or row.get("input_symbol")
                    or row.get("raw_symbol")
                )
                iid = row.get("instrument_id") or row.get("output_symbol")
                if sym is not None and iid is not None:
                    pairs.append((str(sym), str(iid)))
    else:
        print(
            f"WARNING: unexpected result type from symbology resolver: {type(result)}",
            file=sys.stderr,
        )
        pairs = [("RAW_RESULT_REPR", repr(result)[:500])]

    resolved = [
        (s, iid)
        for (s, iid) in pairs
        if not iid.startswith("UNPARSED") and s != "RAW_RESULT_REPR"
    ]
    resolved_symbols = sorted({s for s, _ in resolved})

    print("=" * 80)
    print("MXM V1 — Databento Proof 2: Symbology resolution (outright candidates)")
    print("=" * 80)
    print(f"Dataset:  {DATASET}")
    print(f"Root:     {ROOT}")
    print(f"Window:   {start_date} -> {end_date}")
    print(f"Resolver: symbology.{resolver_name}")
    print("-" * 80)
    print(f"Candidates generated: {len(candidates)}")
    print(f"Resolved candidates:  {len(resolved)}")
    print("-" * 80)

    if resolved:
        print("Resolved symbol -> instrument_id:")
        for sym, iid in sorted(resolved)[:50]:
            print(f"{sym:8s}  {iid}")
        if len(resolved) > 50:
            print(f"... ({len(resolved)} total)")
    else:
        print("No candidates resolved. Likely causes:")
        print("- wrong year format (1-digit vs 2-digit)")
        print("- dataset expects different symbol convention")
        print(
            "- need to use stype_in different from raw_symbol (e.g. parent, continuous)"
        )
        print("- the symbology resolver signature differs in this client version")

    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

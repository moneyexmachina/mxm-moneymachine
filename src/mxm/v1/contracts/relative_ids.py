from __future__ import annotations

import re

from mxm_refdata.models.periods import PeriodType

from .selectors import PeriodFilter, SelectorRule

_RC_PREFIX = "RC::"

# CYCLE forms:
#   NONE
#   <cycle_id>[1,2,3]
_CYCLE_RE = re.compile(r"^(?P<cycle_id>[A-Za-z0-9_]+)\[(?P<elems>[0-9,\s]+)\]$")

_MONTH_ABBREV: dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

_MONTH_TO_FUTURES_CODE: dict[int, str] = {
    1: "F",  # Jan
    2: "G",  # Feb
    3: "H",  # Mar
    4: "J",  # Apr
    5: "K",  # May
    6: "M",  # Jun
    7: "N",  # Jul
    8: "Q",  # Aug
    9: "U",  # Sep
    10: "V",  # Oct
    11: "X",  # Nov
    12: "Z",  # Dec
}

_ALL_CALENDAR_MONTHS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)


def canonical_relative_id(rule: SelectorRule) -> str:
    """
    Fully explicit, parseable, canonical identifier for a SelectorRule.

    This form is intended for stable machine use and roundtrips via
    parse_canonical_relative_id().
    """
    pf = rule.period_filter

    pt = pf.period_type.name
    cycle = _cycle_repr(pf.cycle_id, pf.cycle_elements)

    rank = "LTD"  # engine-locked in Session 18
    n = rule.n

    return f"RC::PT={pt}::CYCLE={cycle}::RANK={rank}::N={n}"


def short_rel_id(rule: SelectorRule) -> str:
    """
    Deterministic ergonomic label describing selection intent.

    Rules
    -----
    1) Legacy fallback:
       - cycle_elements is None:
           L{n}

    2) CALENDAR_MONTHS:
       - all 12 months:
           M{n}
       - one month:
           <MonAbbrev>{n}
           e.g. Mar1
       - two months:
           <MonAbbrevA><MonAbbrevB>{n}
           e.g. JunDec1
       - three or more months (but not all 12):
           <FuturesMonthCodes>{n}
           e.g. HMUZ1, HKNUZ1

    3) Other/custom cycle ids:
       - one element:
           <CycleAbbrev><elem>-{n}
       - multiple elements:
           <CycleAbbrev>[e1,e2,...]{n}

    Notes
    -----
    - This function is an ergonomic projection only.
    - canonical_relative_id() remains the authoritative machine form.
    """
    pf = rule.period_filter
    n = rule.n

    if pf.cycle_elements is None:
        return f"L{n}"

    # By PeriodFilter invariants:
    assert pf.cycle_id is not None and pf.cycle_id != ""

    elems = tuple(sorted(int(x) for x in pf.cycle_elements))
    cycle_id = pf.cycle_id

    if cycle_id == "CALENDAR_MONTHS":
        return _short_calendar_months_id(elems=elems, n=n)

    abbr = _abbrev_cycle_id(cycle_id)

    if len(elems) == 1:
        return f"{abbr}{elems[0]}-{n}"

    inner = ",".join(str(x) for x in elems)
    return f"{abbr}[{inner}]{n}"


def _short_calendar_months_id(*, elems: tuple[int, ...], n: int) -> str:
    """
    Ergonomic short id for CALENDAR_MONTHS cycle subsets.
    """
    _validate_calendar_months(elems)

    if elems == _ALL_CALENDAR_MONTHS:
        return f"M{n}"

    if len(elems) == 1:
        return f"{_month_abbrev(elems[0])}{n}"

    if len(elems) == 2:
        head = "".join(_month_abbrev(m) for m in elems)
        return f"{head}{n}"

    head = "".join(_month_futures_code(m) for m in elems)
    return f"{head}{n}"


def _month_abbrev(month: int) -> str:
    try:
        return _MONTH_ABBREV[month]
    except KeyError as e:
        raise ValueError(f"Invalid calendar month element: {month}") from e


def _month_futures_code(month: int) -> str:
    try:
        return _MONTH_TO_FUTURES_CODE[month]
    except KeyError as e:
        raise ValueError(f"Invalid calendar month element: {month}") from e


def _validate_calendar_months(elems: tuple[int, ...]) -> None:
    bad = [m for m in elems if m < 1 or m > 12]
    if bad:
        raise ValueError(f"Invalid calendar month elements: {bad}")


def _cycle_repr(cycle_id: str | None, cycle_elements: frozenset[int] | None) -> str:
    if cycle_elements is None:
        return "NONE"

    elems = sorted(int(x) for x in cycle_elements)
    assert cycle_id is not None and cycle_id != ""
    return f"{cycle_id}[{','.join(str(x) for x in elems)}]"


def _abbrev_cycle_id(cycle_id: str) -> str:
    """
    Deterministic abbreviation for unknown/custom cycle ids.

    Rule:
    - split on '_' and take first character of each token
    - uppercase
    - cap at 4 chars

    Examples:
      CALENDAR_QUARTERS -> CQ
      DELIVERY_MONTHS   -> DM
      SOME_LONG_CYCLE   -> SLC
    """
    parts = [p for p in cycle_id.split("_") if p]
    if not parts:
        return "C"  # degenerate fallback

    abbr = "".join(p[0].upper() for p in parts)
    return abbr[:4]


def parse_canonical_relative_id(s: str) -> SelectorRule:
    """
    Inverse of canonical_relative_id(rule).

    Required roundtrip invariant:
        parse_canonical_relative_id(canonical_relative_id(rule)) == rule
    """
    if not s.startswith(_RC_PREFIX):
        raise ValueError(f"Invalid relative id prefix; expected {_RC_PREFIX!r}")

    # Split tokens, ignoring the leading "RC"
    # "RC::PT=...::CYCLE=...::RANK=LTD::N=2"
    tokens = s.split("::")
    if tokens[0] != "RC":
        raise ValueError(f"Invalid relative id header; got {tokens[0]!r}")

    kv: dict[str, str] = {}
    for tok in tokens[1:]:
        if "=" not in tok:
            raise ValueError(f"Invalid token {tok!r} (expected KEY=VALUE)")
        k, v = tok.split("=", 1)
        if not k:
            raise ValueError(f"Invalid empty key in token {tok!r}")
        if k in kv:
            raise ValueError(f"Duplicate key {k!r} in canonical_relative_id")
        kv[k] = v

    required = {"PT", "CYCLE", "RANK", "N"}
    missing = required - set(kv.keys())
    extra = set(kv.keys()) - required
    if missing:
        raise ValueError(f"Missing keys in canonical_relative_id: {sorted(missing)}")
    if extra:
        raise ValueError(f"Unexpected keys in canonical_relative_id: {sorted(extra)}")

    # PT
    pt_raw = kv["PT"]
    try:
        period_type = PeriodType[pt_raw]
    except KeyError as e:
        raise ValueError(f"Unknown PeriodType name {pt_raw!r}") from e

    # RANK (Session 18 locked)
    rank = kv["RANK"]
    if rank != "LTD":
        raise ValueError(
            f"Unsupported RANK {rank!r}; Session 18 locks ranking to 'LTD'"
        )

    # N
    n_raw = kv["N"]
    try:
        n = int(n_raw)
    except ValueError as e:
        raise ValueError(f"Invalid N value {n_raw!r} (expected int)") from e
    if n < 1:
        raise ValueError(f"Invalid N value {n} (must be >= 1)")

    # CYCLE
    cycle_repr = kv["CYCLE"]
    cycle_id, cycle_elements = _parse_cycle_repr(cycle_repr, period_type=period_type)

    pf = PeriodFilter(
        period_type=period_type,
        cycle_id=cycle_id,
        cycle_elements=cycle_elements,
    )
    return SelectorRule(period_filter=pf, n=n)


def _parse_cycle_repr(
    s: str,
    *,
    period_type: PeriodType,
) -> tuple[str | None, frozenset[int] | None]:
    if s == "NONE":
        return None, None

    m = _CYCLE_RE.match(s)
    if not m:
        raise ValueError(
            f"Invalid CYCLE repr {s!r}; expected 'NONE' or '<cycle_id>[1,2,3]'"
        )

    cycle_id = m.group("cycle_id")
    elems_raw = m.group("elems")
    elems: list[int] = []
    for part in elems_raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            x = int(part)
        except ValueError as e:
            raise ValueError(f"Invalid cycle element {part!r} in {s!r}") from e
        elems.append(x)

    if not elems:
        raise ValueError(f"CYCLE repr has no elements: {s!r}")

    cycle_elements = frozenset(elems)

    # Optional safety mirrors PeriodFilter.__post_init__
    if any(x < 1 for x in cycle_elements):
        raise ValueError(
            f"CYCLE elements must be positive integers: {sorted(cycle_elements)}"
        )

    if period_type == PeriodType.MONTH and cycle_id == "CALENDAR_MONTHS":
        # This is not strictly required for reversibility, but it catches corruption early.
        if any(x > 12 for x in cycle_elements):
            raise ValueError(
                f"Monthly calendar elements must be in 1..12: {sorted(cycle_elements)}"
            )

    return cycle_id, cycle_elements

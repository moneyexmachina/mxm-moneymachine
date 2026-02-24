from __future__ import annotations

from mxm.v1.contracts.selectors import SelectorRule

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


def canonical_relative_id(rule: SelectorRule) -> str:
    pf = rule.period_filter

    pt = pf.period_type.name
    cycle = _cycle_repr(pf.cycle_id, pf.cycle_elements)

    rank = "LTD"  # engine-locked in Session 18
    n = rule.n

    return f"RC::PT={pt}::CYCLE={cycle}::RANK={rank}::N={n}"


def short_rel_id(rule: SelectorRule) -> str:
    """
    Deterministic, ergonomic label describing selection intent.

    V1 rules (intent-only, no refdata inference):

    - cycle_elements is None:
        L{n}
      (listed-universe rank)

    - cycle_elements is not None and len == 1:
        if cycle_id == CALENDAR_MONTHS: <MonAbbrev><n>
        else: <CycleAbbrev><elem>-<n>

    - cycle_elements is not None and len > 1:
        if cycle_id == CALENDAR_MONTHS: M[...]{n}
        else: <CycleAbbrev>[...]{n}
    """
    pf = rule.period_filter
    n = rule.n

    if pf.cycle_elements is None:
        return f"L{n}"

    # By PeriodFilter invariants:
    assert pf.cycle_id is not None and pf.cycle_id != ""

    elems = sorted(int(x) for x in pf.cycle_elements)
    cycle_id = pf.cycle_id

    if cycle_id == "CALENDAR_MONTHS":
        if len(elems) == 1:
            m = elems[0]
            try:
                head = _MONTH_ABBREV[m]
            except KeyError as e:
                raise ValueError(f"Invalid calendar month element: {m}") from e
            return f"{head}{n}"

        inner = ",".join(str(x) for x in elems)
        return f"M[{inner}]{n}"

    abbr = _abbrev_cycle_id(cycle_id)

    if len(elems) == 1:
        return f"{abbr}{elems[0]}-{n}"

    inner = ",".join(str(x) for x in elems)
    return f"{abbr}[{inner}]{n}"


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

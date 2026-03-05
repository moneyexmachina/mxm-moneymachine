from __future__ import annotations

import re

from mxm_refdata.models.periods import PeriodType

from mxm.v1.contracts.selectors import SelectorRule

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


def parse_canonical_relative_id(s: str) -> SelectorRule:
    """
    Inverse of canonical_relative_id(rule).

    Required roundtrip invariant:
        parse_canonical_relative_id(canonical_relative_id(rule)) == rule
    """
    if not isinstance(s, str) or not s:
        raise ValueError("canonical_relative_id must be a non-empty string")

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

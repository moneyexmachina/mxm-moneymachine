from __future__ import annotations

import re
from pathlib import Path

import pytest

from mxm.moneymachine.marketdata.datasets.ohlcv_1d.state import DerivedState
from mxm.moneymachine.marketdata.inspect.models import AttemptStatus, ProductStatus

AUTHORITATIVE_ATTEMPT_STATUSES = {
    "unmapped",
    "skipped_empty_expected_window",
    "complete",
    "dry_run",
    "skipped_cost_cap",
    "ingested",
    "incomplete",
    "error",
}

AUTHORITATIVE_PRODUCT_STATUSES = {
    "never_run",
    "done",
    "partial",
    "blocked",
    "error",
}

AUTHORITATIVE_DERIVED_STATES = {
    "done",
    "blocked_unmapped",
    "blocked_empty_expected",
    "needs_ingest",
    "retryable_error",
    "skipped_budget",
    "unknown",
}


def test_attempt_status_enum_is_authoritative() -> None:
    got = {e.value for e in AttemptStatus}
    assert got == AUTHORITATIVE_ATTEMPT_STATUSES


def test_product_status_enum_is_authoritative() -> None:
    got = {e.value for e in ProductStatus}
    assert got == AUTHORITATIVE_PRODUCT_STATUSES


def test_derived_state_enum_is_authoritative() -> None:
    got = {e.value for e in DerivedState}
    assert got == AUTHORITATIVE_DERIVED_STATES


def _repo_root() -> Path:
    """
    Heuristic: tests live in <repo>/tests/unittests/*.py
    """
    here = Path(__file__).resolve()
    return here.parents[2]


@pytest.mark.parametrize(
    "relpath",
    [
        # writer surface
        "src/mxm/v1/marketdata/orchestrators/ohlcv_1d.py",
        # if you ever move it, add the new path here
    ],
)
def test_no_unknown_attempt_status_literals_in_ohlcv_orchestrator(relpath: str) -> None:
    """
    Static proof (P0): in the OHLCV-1D orchestrator writer surface, any literal assignment
    of `status = "..."` must be from the authoritative attempt-status set.

    Notes:
    - We explicitly ignore stage_status and other fields by matching `status = "..."`
      at token boundaries.
    - This test is intentionally narrow: it does not scan the whole repo.
    """
    p = _repo_root() / relpath
    if not p.exists():
        pytest.skip(f"file not found: {p}")

    src = p.read_text(encoding="utf-8")

    # Match exactly: status = "SOMETHING"
    # (token-boundary to avoid matching stage_status, stopped_reason, etc.)
    pat = re.compile(r'(?m)^\s*status\s*=\s*"([^"]+)"\s*$')

    found = pat.findall(src)

    # If you do not use literal assignments, this may be empty (that's fine).
    for s in found:
        assert (
            s in AUTHORITATIVE_ATTEMPT_STATUSES
        ), f"unknown attempt status literal {s!r} in {relpath}"


def test_docs_do_not_reference_vendor_final_partial_done() -> None:
    repo = Path(__file__).resolve().parents[2]
    phase2 = repo / "docs" / "phase2"
    hits: list[str] = []
    for p in phase2.rglob("*.md"):
        s = p.read_text("utf-8")
        if "vendor_final_partial_done" in s:
            hits.append(str(p))
    assert hits == [], f"deprecated status_detail found in: {hits}"

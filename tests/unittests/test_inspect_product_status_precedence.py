from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from mxm.v1.marketdata.inspect.models import AttemptStatus, ProductStatus
from mxm.v1.marketdata.inspect.product import compute_product_status


@dataclass(frozen=True)
class _FakeLastAttempt:
    status: AttemptStatus
    vendor_final: bool = False


@dataclass(frozen=True)
class _FakeContractCoverage:
    windows: object
    last_attempt: _FakeLastAttempt


def _cc(
    *, complete: bool, status: AttemptStatus, vendor_final: bool = False
) -> _FakeContractCoverage:
    windows = SimpleNamespace(complete=bool(complete))
    return _FakeContractCoverage(
        windows=windows,
        last_attempt=_FakeLastAttempt(status=status, vendor_final=bool(vendor_final)),
    )


def test_product_status_never_run() -> None:
    assert compute_product_status([]) == ProductStatus.never_run


def test_product_status_done_requires_all_windows_complete_and_no_blockers() -> None:
    cs = [
        _cc(complete=True, status=AttemptStatus.complete, vendor_final=False),
        _cc(complete=True, status=AttemptStatus.ingested, vendor_final=False),
    ]
    assert compute_product_status(cs) == ProductStatus.done


def test_product_status_error_on_any_error_status() -> None:
    cs = [
        _cc(complete=True, status=AttemptStatus.ingested),
        _cc(complete=False, status=AttemptStatus.error),
    ]
    assert compute_product_status(cs) == ProductStatus.error


def test_product_status_error_on_contradiction_complete_but_windows_incomplete_without_vendor_final() -> (
    None
):
    cs = [
        _cc(complete=False, status=AttemptStatus.complete, vendor_final=False),
    ]
    assert compute_product_status(cs) == ProductStatus.error


def test_product_status_not_error_on_vendor_final_noop_partial() -> None:
    """
    Allowed case: attempt status says 'complete' (no-op), windows are incomplete,
    but vendor_final is true. This must NOT produce an error; it should become partial
    (unless blocked), because completeness truth remains false.
    """
    cs = [
        _cc(complete=False, status=AttemptStatus.complete, vendor_final=True),
    ]
    assert compute_product_status(cs) == ProductStatus.partial


def test_product_status_blocked_if_any_unmapped_and_no_errors() -> None:
    cs = [
        _cc(complete=True, status=AttemptStatus.ingested),
        _cc(complete=False, status=AttemptStatus.unmapped),
    ]
    assert compute_product_status(cs) == ProductStatus.blocked


def test_product_status_blocked_if_any_cost_cap_and_no_errors() -> None:
    cs = [
        _cc(complete=True, status=AttemptStatus.ingested),
        _cc(complete=False, status=AttemptStatus.skipped_cost_cap),
    ]
    assert compute_product_status(cs) == ProductStatus.blocked


def test_product_status_partial_if_incomplete_but_no_blockers_or_errors() -> None:
    cs = [
        _cc(complete=True, status=AttemptStatus.ingested),
        _cc(complete=False, status=AttemptStatus.incomplete),
    ]
    assert compute_product_status(cs) == ProductStatus.partial

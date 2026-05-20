from __future__ import annotations

import hashlib

import pandas as pd
from _pytest.monkeypatch import MonkeyPatch

import mxm.v1.marketdata.orchestrators.statistics_1d as orch_mod
from mxm.v1.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptRow,
    Statistics1DAttemptsStore,
)
from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from tests.integration.testkit.fakes_refdata import make_contract
from tests.integration.testkit.patching_statistics_1d import (
    OfflineStats1DConfig,
    patch_statistics_1d_orchestrator_offline,
)
from tests.integration.testkit.statistics_1d_world import Statistics1DWorld


def _latest_attempt(
    backend: SQLiteBackend,
    *,
    product_id: str,
    contract_id: str,
) -> Statistics1DAttemptRow:
    store = Statistics1DAttemptsStore(backend=backend)
    row = store.get_latest_attempt_for_contract(
        product_id=product_id,
        contract_id=contract_id,
    )
    assert row is not None, "expected an attempt row to be recorded"
    return row


def _effective_rows(a: Statistics1DAttemptRow) -> int | None:
    return (
        a.stored_rows_after if a.stored_rows_after is not None else a.stored_rows_before
    )


def _effective_min(a: Statistics1DAttemptRow) -> str | None:
    return a.stored_min_after if a.stored_min_after is not None else a.stored_min_before


def _effective_max(a: Statistics1DAttemptRow) -> str | None:
    return a.stored_max_after if a.stored_max_after is not None else a.stored_max_before


def _event_key_hash(df: pd.DataFrame) -> str:
    keys = (
        df[["instrument_id", "stat_type", "ts_event", "sequence"]]
        .drop_duplicates()
        .sort_values(["instrument_id", "stat_type", "ts_event", "sequence"])
        .copy()
    )

    # Force deterministic scalar types (and make pyright happy)
    keys["instrument_id"] = keys["instrument_id"].astype("int64")
    keys["stat_type"] = keys["stat_type"].astype("int64")
    keys["sequence"] = keys["sequence"].astype("int64")

    # Convert ts_event to UTC int64 nanoseconds
    ts = pd.DatetimeIndex(keys["ts_event"])
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    keys["ts_event_ns"] = ts.view("int64")

    payload = (
        keys[["instrument_id", "stat_type", "ts_event_ns", "sequence"]]
        .to_csv(index=False, header=False)
        .encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def test_statistics_1d_orchestrator_roundtrip_idempotent(
    monkeypatch: MonkeyPatch,
    statistics_1d_world: Statistics1DWorld,
) -> None:
    world = statistics_1d_world
    backend: SQLiteBackend = world.backend
    store: Statistics1DStore = world.stats_store
    product_id = "cme_emini_snp500_futures"
    instrument_id = 111

    # Patch orchestrator to hermetic mode (no live refdata periods, no vendor calls)
    patch_statistics_1d_orchestrator_offline(
        monkeypatch,
        cfg=OfflineStats1DConfig(
            product_id=product_id,
            instrument_id=instrument_id,
            dataset="TEST.DATASET",
            publisher_id=1,
            estimated_cost_usd=0.0,
        ),
    )

    # Patch RefDataAPI used inside orchestrator._enumerate_contracts
    class FakeRefDataAPI:
        def get_contracts_for_product(self, pid: str):
            assert pid == product_id
            return [make_contract(product_id=product_id)]

    monkeypatch.setattr(orch_mod, "RefDataAPI", FakeRefDataAPI)

    # Clean slate for the instrument
    store.delete(dataset="TEST.DATASET", publisher_id=1, instrument_id=instrument_id)

    # Run twice
    r1 = orch_mod.ingest_statistics_1d_for_product(
        backend=backend,
        store=store,
        product_id=product_id,
        mode="bootstrap",
        cost_cap_usd=10.0,
        client=object(),
    )
    contract_id = r1.runs[0].contract_id
    assert r1.contracts_total > 0, "test misconfigured: no eligible contracts"
    assert len(r1.runs) > 0, "test misconfigured: orchestrator ran zero contracts"

    attempts = Statistics1DAttemptsStore(backend=backend)
    latest = attempts.get_latest_attempt_for_contract(
        product_id=product_id,
        contract_id=r1.runs[0].contract_id,
    )

    assert latest is not None
    # show the useful bits in assertion failure
    assert latest.status != "error", (
        f"status={latest.status} detail={latest.status_detail} "
        f"error_type={latest.error_type} error_message={latest.error_message}"
    )
    assert r1.runs[0].status in (
        "ingested",
        "complete",
    ), f"unexpected status: {r1.runs[0]}"

    a1 = _latest_attempt(backend, product_id=product_id, contract_id=contract_id)

    # 1) Orchestrator did not record an error
    assert a1.status != "error", (
        f"run1 status=error detail={a1.status_detail} "
        f"error_type={a1.error_type} error_message={a1.error_message}"
    )

    # 2) Run1 should have attempted an ingest (either completed or incomplete/vendor_final_partial)
    assert a1.status in {
        "ingested",
        "incomplete",
        "complete",
    }, f"unexpected run1 status: {a1.status}"

    # 3) If it ingested, we should see coverage_after populated (row_count_after > 0)
    # Names here depend on your attempt row fields; from your earlier printout these exist:
    assert (
        a1.stored_rows_after or 0
    ) > 0, f"expected stored_rows_after > 0, got {a1.stored_rows_after!r}"
    assert (
        a1.stored_min_after is not None and a1.stored_max_after is not None
    ), "expected min/max ts after ingest"

    # Ingest path should set coverage_after
    assert a1.stored_rows_after is not None and a1.stored_rows_after > 0
    assert a1.stored_min_after is not None
    assert a1.stored_max_after is not None
    # 4) Costs: in hermetic mode, estimate is 0.0 and we treat estimate as charged.
    # Accept either None or 0.0, but not positive.
    assert (a1.cost_estimated_usd or 0.0) == 0.0
    assert (a1.cost_used_usd or 0.0) == 0.0
    assert (a1.cost_charged_usd or 0.0) == 0.0
    df1 = store.read(
        dataset="TEST.DATASET", publisher_id=1, instrument_id=instrument_id
    )
    h1 = _event_key_hash(df1)
    cov1 = store.scan_coverage(
        dataset="TEST.DATASET", publisher_id=1, instrument_id=instrument_id
    )

    r2 = orch_mod.ingest_statistics_1d_for_product(
        backend=backend,
        store=store,
        product_id=product_id,
        mode="bootstrap",
        cost_cap_usd=10.0,
        client=object(),
    )

    a2 = _latest_attempt(backend, product_id=product_id, contract_id=contract_id)

    assert a2.status != "error", (
        f"run2 status=error detail={a2.status_detail} "
        f"error_type={a2.error_type} error_message={a2.error_message}"
    )

    # Run2 should be a noop path in practice; orchestrator records it as "complete" with detail "already_complete"
    # or, depending on state, still "complete" under vendor-final noop partial.
    assert a2.status in {
        "complete",
        "dry_run",
        "skipped_empty_expected_window",
    }, f"unexpected run2 status: {a2.status}"
    assert a2.dry_run is False, "did not expect dry_run in this test"

    # Coverage should not change between run1 and run2 at the ledger level

    # NOOP path: we expect coverage_after to be None (no ingest), but coverage_before should be present
    assert a2.stored_rows_after is None
    assert a2.stored_min_after is None
    assert a2.stored_max_after is None

    assert a2.stored_rows_before is not None and a2.stored_rows_before > 0
    assert a2.stored_min_before is not None
    assert a2.stored_max_before is not None
    assert _effective_rows(a2) == _effective_rows(a1)
    assert _effective_min(a2) == _effective_min(a1)
    assert _effective_max(a2) == _effective_max(a1)

    # No additional cost on the noop run
    assert (a2.cost_used_usd or 0.0) == 0.0
    assert (a2.cost_charged_usd or 0.0) == 0.0

    df2 = store.read(
        dataset="TEST.DATASET", publisher_id=1, instrument_id=instrument_id
    )
    h2 = _event_key_hash(df2)
    cov2 = store.scan_coverage(
        dataset="TEST.DATASET", publisher_id=1, instrument_id=instrument_id
    )

    # Assert: storage idempotency
    assert len(df2) == len(df1)
    assert h2 == h1

    assert (
        df2[["instrument_id", "stat_type", "ts_event", "sequence"]].duplicated().sum()
        == 0
    )

    # Assert: coverage stable
    assert cov2.row_count == cov1.row_count
    assert cov2.min_ts == cov1.min_ts
    assert cov2.max_ts == cov1.max_ts

    # Assert: stage stable and non-error
    assert r1.stage_status in ("ok", "halted")
    assert r2.stage_status in ("ok", "halted")
    assert all(run.status != "error" for run in r2.runs)

"""Tests for instrument-definition mapping orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import cast

import pytest
from pytest import MonkeyPatch

import mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.build as build_module
from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.build import (
    rebuild_instrument_definition_mappings,
)
from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.moneymachine.marketdata.mapping.vendors.databento.instrument_resolver import (
    RefdataPeriodLookupError,
)
from mxm.refdata import RefDataReader

PRODUCT_ID = "ES"
FEED = "databento:GLBX.MDP3:ES.FUT:parent:definition"


# ---------------------------------------------------------------------------
# Narrow test doubles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeProductRoot:
    dataset: str = "GLBX.MDP3"
    parent: str = "ES.FUT"
    stype_in: str = "parent"


@dataclass(frozen=True)
class _FakeFeed:
    value: str

    def key(self) -> str:
        return self.value


@dataclass(frozen=True)
class _FakeContract:
    contract_id: str
    period_id: str


@dataclass(frozen=True)
class _FakePeriod:
    period_id: str
    first_date: date


class _FakeRefDataReader:
    def __init__(
        self,
        *,
        contracts: list[_FakeContract],
        periods_by_id: dict[str, _FakePeriod],
    ) -> None:
        self.contracts = contracts
        self.periods_by_id = periods_by_id

    def get_contracts_for_product(
        self,
        product_id: str,
    ) -> list[_FakeContract]:
        assert product_id == PRODUCT_ID
        return list(self.contracts)

    def get_period_by_id(
        self,
        period_id: str,
    ) -> _FakePeriod | None:
        return self.periods_by_id.get(period_id)


class _FakeDefinitionsStore:
    def __init__(
        self,
        *,
        watermark: str | None,
    ) -> None:
        self.watermark = watermark
        self.requested_feeds: list[str] = []

    def get_watermark(
        self,
        *,
        feed: str,
    ) -> str | None:
        self.requested_feeds.append(feed)
        return self.watermark


@dataclass(frozen=True)
class _FakeResetResult:
    rows_deleted: int


@dataclass(frozen=True)
class _FakeBuildResult:
    contracts_attempted: int
    inserted: int
    ignored: int
    unmapped: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _BuildCall:
    product_id: str
    feed: str
    dataset: str
    contracts: tuple[tuple[int, int], ...]


class _FakeMappingsStore:
    def __init__(
        self,
        *,
        vendor_maturities: list[tuple[int, int]],
        build_result: _FakeBuildResult | None = None,
        reset_rows_deleted: int = 0,
    ) -> None:
        self.vendor_maturities = vendor_maturities
        self.build_result = build_result
        self.reset_rows_deleted = reset_rows_deleted

        self.reset_products: list[str] = []
        self.requested_feeds: list[str] = []
        self.build_calls: list[_BuildCall] = []

    def reset_product(
        self,
        *,
        product_id: str,
    ) -> _FakeResetResult:
        self.reset_products.append(product_id)
        return _FakeResetResult(
            rows_deleted=self.reset_rows_deleted,
        )

    def list_vendor_maturities_from_current(
        self,
        *,
        feed: str,
    ) -> list[tuple[int, int]]:
        self.requested_feeds.append(feed)
        return list(self.vendor_maturities)

    def build_from_current_definitions(
        self,
        *,
        product_id: str,
        feed: str,
        dataset: str,
        contracts: list[tuple[int, int]],
    ) -> _FakeBuildResult:
        self.build_calls.append(
            _BuildCall(
                product_id=product_id,
                feed=feed,
                dataset=dataset,
                contracts=tuple(contracts),
            )
        )

        if self.build_result is None:
            raise AssertionError(
                "build_from_current_definitions was called unexpectedly"
            )

        return self.build_result


# ---------------------------------------------------------------------------
# Cast helpers
# ---------------------------------------------------------------------------


def _reader(
    fake: _FakeRefDataReader,
) -> RefDataReader:
    return cast(RefDataReader, fake)


def _defs_store(
    fake: _FakeDefinitionsStore,
) -> InstrumentDefinitionsStore:
    return cast(InstrumentDefinitionsStore, fake)


def _mappings_store(
    fake: _FakeMappingsStore,
) -> InstrumentDefinitionMappingsStore:
    return cast(InstrumentDefinitionMappingsStore, fake)


# ---------------------------------------------------------------------------
# Stable vendor scope
# ---------------------------------------------------------------------------


def _fake_product_root(
    product_id: str,
) -> _FakeProductRoot:
    assert product_id == PRODUCT_ID
    return _FakeProductRoot()


def _fake_make_feed(
    *,
    source: str,
    dataset: str,
    symbol: str,
    stype_in: str,
    schema: str,
) -> _FakeFeed:
    assert source == "databento"
    assert dataset == "GLBX.MDP3"
    assert symbol == "ES.FUT"
    assert stype_in == "parent"
    assert schema == "definition"

    return _FakeFeed(FEED)


@pytest.fixture(autouse=True)
def patch_vendor_scope(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        build_module,
        "get_databento_product_root",
        _fake_product_root,
    )
    monkeypatch.setattr(
        build_module,
        "make_instrument_definition_feed",
        _fake_make_feed,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stops_when_definitions_watermark_is_missing() -> None:
    reader = _FakeRefDataReader(
        contracts=[],
        periods_by_id={},
    )
    definitions = _FakeDefinitionsStore(
        watermark=None,
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[],
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="update",
    )

    assert report.stopped_reason == "gate_failed"
    assert report.definitions_watermark is None

    assert len(report.gates) == 1
    assert report.gates[0].name == "definitions_watermark_exists"
    assert report.gates[0].ok is False

    assert definitions.requested_feeds == [FEED]
    assert mappings.requested_feeds == []
    assert mappings.build_calls == []


def test_stops_when_current_definitions_have_no_outrights() -> None:
    reader = _FakeRefDataReader(
        contracts=[],
        periods_by_id={},
    )
    definitions = _FakeDefinitionsStore(
        watermark="2026-08-31T00:00:00Z",
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[],
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="update",
    )

    assert report.stopped_reason == "gate_failed"
    assert len(report.gates) == 2

    assert report.gates[0].name == "definitions_watermark_exists"
    assert report.gates[0].ok is True

    assert report.gates[1].name == "definitions_current_has_outrights"
    assert report.gates[1].ok is False

    assert report.vendor_maturities_total == 0
    assert mappings.build_calls == []


def test_reset_happens_before_readiness_gates() -> None:
    reader = _FakeRefDataReader(
        contracts=[],
        periods_by_id={},
    )
    definitions = _FakeDefinitionsStore(
        watermark=None,
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[],
        reset_rows_deleted=7,
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="bootstrap",
        reset=True,
    )

    assert mappings.reset_products == [PRODUCT_ID]

    assert report.reset_requested is True
    assert report.reset_result is not None
    assert report.reset_result.rows_deleted == 7

    assert report.stopped_reason == "gate_failed"


def test_stops_when_refdata_contains_no_contract_maturities() -> None:
    reader = _FakeRefDataReader(
        contracts=[],
        periods_by_id={},
    )
    definitions = _FakeDefinitionsStore(
        watermark="2026-08-31T00:00:00Z",
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[
            (2026, 3),
        ],
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="update",
    )

    assert report.stopped_reason == "no_contracts"
    assert report.refdata_contracts_total == 0
    assert report.refdata_maturities_total == 0
    assert report.vendor_maturities_total == 1
    assert report.overlap_attempted == 0

    assert mappings.build_calls == []


def test_stops_when_refdata_and_vendor_have_no_maturity_overlap() -> None:
    reader = _FakeRefDataReader(
        contracts=[
            _FakeContract(
                contract_id="ES-2026-03",
                period_id="2026-03",
            )
        ],
        periods_by_id={
            "2026-03": _FakePeriod(
                period_id="2026-03",
                first_date=date(2026, 3, 1),
            )
        },
    )
    definitions = _FakeDefinitionsStore(
        watermark="2026-08-31T00:00:00Z",
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[
            (2026, 6),
        ],
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="update",
    )

    assert report.stopped_reason == "no_overlap"
    assert report.refdata_contracts_total == 1
    assert report.refdata_maturities_total == 1
    assert report.vendor_maturities_total == 1
    assert report.overlap_attempted == 0

    assert mappings.build_calls == []


def test_builds_only_overlapping_maturities_and_finalizes_report() -> None:
    reader = _FakeRefDataReader(
        contracts=[
            _FakeContract(
                contract_id="ES-2026-03-A",
                period_id="2026-03",
            ),
            _FakeContract(
                contract_id="ES-2026-03-B",
                period_id="2026-03",
            ),
            _FakeContract(
                contract_id="ES-2026-06",
                period_id="2026-06",
            ),
        ],
        periods_by_id={
            "2026-03": _FakePeriod(
                period_id="2026-03",
                first_date=date(2026, 3, 1),
            ),
            "2026-06": _FakePeriod(
                period_id="2026-06",
                first_date=date(2026, 6, 1),
            ),
        },
    )
    definitions = _FakeDefinitionsStore(
        watermark="2026-08-31T00:00:00Z",
    )

    build_result = _FakeBuildResult(
        contracts_attempted=1,
        inserted=1,
        ignored=0,
        unmapped=(),
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[
            (2026, 6),
            (2026, 9),
        ],
        build_result=build_result,
    )

    report = rebuild_instrument_definition_mappings(
        refdata_reader=_reader(reader),
        defs_store=_defs_store(definitions),
        mappings_store=_mappings_store(mappings),
        product_id=PRODUCT_ID,
        mode="update",
    )

    assert mappings.build_calls == [
        _BuildCall(
            product_id=PRODUCT_ID,
            feed=FEED,
            dataset="GLBX.MDP3",
            contracts=((2026, 6),),
        )
    ]

    assert report.stopped_reason == "ok"
    assert report.refdata_contracts_total == 3
    assert report.refdata_maturities_total == 2
    assert report.vendor_maturities_total == 2
    assert report.overlap_attempted == 1

    assert report.build_result is build_result

    assert report.stage_status == "ok"
    assert report.stop_reason == "ok"
    assert report.mapping_ready_for_ohlcv is True
    assert report.cost_used_usd == 0.0

    assert report.counts["refdata_contracts_total"] == 3
    assert report.counts["refdata_maturities_total"] == 2
    assert report.counts["vendor_maturities_total"] == 2
    assert report.counts["overlap_attempted"] == 1
    assert report.counts["build_attempted"] == 1
    assert report.counts["build_inserted"] == 1
    assert report.counts["build_ignored"] == 0
    assert report.counts["build_unmapped"] == 0
    assert report.counts["stopped_reason"] == "ok"
    assert report.counts["mapping_ready_for_ohlcv"] is True


def test_missing_refdata_period_is_an_integrity_error() -> None:
    reader = _FakeRefDataReader(
        contracts=[
            _FakeContract(
                contract_id="ES-2026-03",
                period_id="2026-03",
            )
        ],
        periods_by_id={},
    )
    definitions = _FakeDefinitionsStore(
        watermark="2026-08-31T00:00:00Z",
    )
    mappings = _FakeMappingsStore(
        vendor_maturities=[
            (2026, 3),
        ],
    )

    with pytest.raises(
        RefdataPeriodLookupError,
        match="2026-03",
    ):
        rebuild_instrument_definition_mappings(
            refdata_reader=_reader(reader),
            defs_store=_defs_store(definitions),
            mappings_store=_mappings_store(mappings),
            product_id=PRODUCT_ID,
            mode="update",
        )

    assert mappings.build_calls == []

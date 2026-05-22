from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from mxm.v1.marketdata.datasets.daily_mark import api as dmapi


@dataclass(frozen=True)
class _FakeContract:
    contract_id: str
    product_id: str


class _FakeRefDataAPI:
    def __init__(
        self,
        *,
        by_id: dict[str, _FakeContract] | None = None,
        by_product: dict[str, list[_FakeContract]] | None = None,
    ) -> None:
        self._by_id = by_id or {}
        self._by_product = by_product or {}

    def get_contract_by_id(self, contract_id: str) -> _FakeContract:
        try:
            return self._by_id[contract_id]
        except KeyError as exc:
            raise ValueError(f"unknown contract_id: {contract_id}") from exc

    def get_contracts_for_product(self, product_id: str) -> list[_FakeContract]:
        return list(self._by_product.get(product_id, []))


class _FakeDailyMarkStore:
    def __init__(
        self,
        *,
        read_map: dict[tuple[str, str], pd.DataFrame] | None = None,
        meta_map: dict[tuple[str, str], dict[str, object] | None] | None = None,
    ) -> None:
        self._read_map = read_map or {}
        self._meta_map = meta_map or {}

        self.read_calls: list[dict[str, object]] = []
        self.read_meta_calls: list[dict[str, object]] = []
        self.mark_path_calls: list[dict[str, object]] = []

    def read(
        self,
        *,
        calendar_id: str,
        contract_id: str,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        self.read_calls.append(
            {
                "calendar_id": calendar_id,
                "contract_id": contract_id,
                "start_session_id": start_session_id,
                "end_session_id": end_session_id,
            }
        )

        key = (calendar_id, contract_id)
        if key not in self._read_map:
            raise FileNotFoundError(f"missing daily_mark surface for {key!r}")
        return self._read_map[key]

    def read_meta(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> dict[str, object] | None:
        self.read_meta_calls.append(
            {
                "calendar_id": calendar_id,
                "contract_id": contract_id,
            }
        )
        return self._meta_map.get((calendar_id, contract_id))

    def mark_path(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> Path:
        self.mark_path_calls.append(
            {
                "calendar_id": calendar_id,
                "contract_id": contract_id,
            }
        )
        return Path(
            f"/tmp/marketdata/mxm/daily-mark/by_contract/"
            f"calendar_id={calendar_id}/contract_id={contract_id}/daily_mark.parquet"
        )


def _patch_api_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    refdata: _FakeRefDataAPI,
    store: _FakeDailyMarkStore,
) -> None:
    def _make_refdata_api() -> _FakeRefDataAPI:
        return refdata

    def _make_daily_mark_store(
        *,
        layout: object,
    ) -> _FakeDailyMarkStore:
        _ = layout
        return store

    monkeypatch.setattr(dmapi, "RefDataAPI", _make_refdata_api)
    monkeypatch.setattr(dmapi, "DailyMarkStore", _make_daily_mark_store)


def _contract(
    *,
    contract_id: str = "cme_emini_snp500_futures.Mar-2025",
    product_id: str = "cme_emini_snp500_futures",
) -> _FakeContract:
    return _FakeContract(contract_id=contract_id, product_id=product_id)


def _daily_mark_df(
    *,
    contract_id: str = "cme_emini_snp500_futures.Mar-2025",
) -> pd.DataFrame:
    # Deliberately unsorted to verify API canonicalises/sorts.
    return pd.DataFrame(
        {
            "session_id": [2, 1],
            "contract_id": [contract_id, contract_id],
            "mark_px": [101.0, 100.0],
            "mark_source": ["observed_settle", "observed_settle"],
            "mark_quality": ["final", "final"],
            "is_markable": [True, True],
            "is_carried": [False, False],
            "carry_streak": [0, 0],
        }
    )


def test_read_daily_mark_contract_reads_and_canonicalises_single_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    store = _FakeDailyMarkStore(
        read_map={
            (calendar_id, contract.contract_id): _daily_mark_df(
                contract_id=contract.contract_id
            )
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_contract(
        calendar_id=calendar_id,
        contract_id=contract.contract_id,
    )

    assert out["product_id"].tolist() == [contract.product_id, contract.product_id]
    assert out["contract_id"].tolist() == [contract.contract_id, contract.contract_id]
    assert out["session_id"].tolist() == [1, 2]
    assert len(store.read_calls) == 1
    assert store.read_calls[0]["calendar_id"] == calendar_id
    assert store.read_calls[0]["contract_id"] == contract.contract_id


def test_read_daily_mark_contract_passes_session_id_slice_to_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    store = _FakeDailyMarkStore(
        read_map={
            (calendar_id, contract.contract_id): _daily_mark_df(
                contract_id=contract.contract_id
            )
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    _ = dmapi.read_daily_mark_contract(
        calendar_id=calendar_id,
        contract_id=contract.contract_id,
        start_session_id=10,
        end_session_id=20,
    )

    assert store.read_calls[0]["start_session_id"] == 10
    assert store.read_calls[0]["end_session_id"] == 20


def test_read_daily_mark_contract_raises_for_unknown_contract_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refdata = _FakeRefDataAPI(by_id={})
    store = _FakeDailyMarkStore()
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    with pytest.raises(ValueError, match=r"unknown contract_id"):
        _ = dmapi.read_daily_mark_contract(
            calendar_id="mxm_business_days_v1_2010-01-01_2050-12-31",
            contract_id="missing-contract",
        )


def test_read_daily_mark_contract_rejects_missing_session_id_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    bad_df = pd.DataFrame(
        {
            "contract_id": [contract.contract_id],
            "mark_px": [100.0],
        }
    )
    store = _FakeDailyMarkStore(read_map={(calendar_id, contract.contract_id): bad_df})
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    with pytest.raises(ValueError, match=r"missing required column 'session_id'"):
        _ = dmapi.read_daily_mark_contract(
            calendar_id=calendar_id,
            contract_id=contract.contract_id,
        )


def test_read_daily_mark_contract_rejects_contract_id_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    bad_df = _daily_mark_df(contract_id="different-contract")
    store = _FakeDailyMarkStore(read_map={(calendar_id, contract.contract_id): bad_df})
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    with pytest.raises(ValueError, match=r"does not match requested contract_id"):
        _ = dmapi.read_daily_mark_contract(
            calendar_id=calendar_id,
            contract_id=contract.contract_id,
        )


def test_read_daily_mark_contract_returns_empty_canonical_frame_when_store_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    store = _FakeDailyMarkStore(
        read_map={(calendar_id, contract.contract_id): pd.DataFrame()}
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_contract(
        calendar_id=calendar_id,
        contract_id=contract.contract_id,
    )

    assert list(out.columns) == ["session_id", "contract_id", "product_id"]
    assert out.empty
    assert pd.api.types.is_integer_dtype(out["session_id"])


def test_read_daily_mark_contract_meta_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    store = _FakeDailyMarkStore(meta_map={(calendar_id, contract.contract_id): None})
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_contract_meta(
        calendar_id=calendar_id,
        contract_id=contract.contract_id,
    )

    assert out is None
    assert len(store.read_meta_calls) == 1


def test_read_daily_mark_contract_meta_enriches_meta_with_contract_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    contract = _contract()
    refdata = _FakeRefDataAPI(by_id={contract.contract_id: contract})
    store = _FakeDailyMarkStore(
        meta_map={
            (calendar_id, contract.contract_id): {
                "content_sha256": "abc123",
                "row_count": 10,
            }
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_contract_meta(
        calendar_id=calendar_id,
        contract_id=contract.contract_id,
    )

    assert out is not None
    assert out["contract_id"] == contract.contract_id
    assert out["product_id"] == contract.product_id
    assert out["calendar_id"] == calendar_id
    assert out["content_sha256"] == "abc123"
    assert out["row_count"] == 10
    assert isinstance(out["path"], str)
    assert calendar_id in str(out["path"])
    assert contract.contract_id in str(out["path"])


def test_read_daily_mark_contract_meta_raises_for_unknown_contract_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refdata = _FakeRefDataAPI(by_id={})
    store = _FakeDailyMarkStore()
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    with pytest.raises(ValueError, match=r"unknown contract_id"):
        _ = dmapi.read_daily_mark_contract_meta(
            calendar_id="mxm_business_days_v1_2010-01-01_2050-12-31",
            contract_id="missing-contract",
        )


def test_read_daily_mark_product_reads_existing_contract_surfaces_and_concatenates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    c1 = _contract(
        contract_id="cme_emini_snp500_futures.Mar-2025",
        product_id="cme_emini_snp500_futures",
    )
    c2 = _contract(
        contract_id="cme_emini_snp500_futures.Jun-2025",
        product_id="cme_emini_snp500_futures",
    )

    refdata = _FakeRefDataAPI(
        by_product={c1.product_id: [c1, c2]},
    )
    store = _FakeDailyMarkStore(
        read_map={
            (calendar_id, c1.contract_id): _daily_mark_df(contract_id=c1.contract_id),
            (calendar_id, c2.contract_id): _daily_mark_df(contract_id=c2.contract_id),
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_product(
        calendar_id=calendar_id,
        product_id=c1.product_id,
    )

    assert len(out) == 4
    assert set(out["contract_id"].unique().tolist()) == {c1.contract_id, c2.contract_id}
    assert out["product_id"].unique().tolist() == [c1.product_id]
    assert out.equals(
        out.sort_values(
            by=["product_id", "contract_id", "session_id"], kind="mergesort"
        ).reset_index(drop=True)
    )


def test_read_daily_mark_product_skips_missing_contract_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    c1 = _contract(
        contract_id="cme_emini_snp500_futures.Mar-2025",
        product_id="cme_emini_snp500_futures",
    )
    c2 = _contract(
        contract_id="cme_emini_snp500_futures.Jun-2025",
        product_id="cme_emini_snp500_futures",
    )

    refdata = _FakeRefDataAPI(
        by_product={c1.product_id: [c1, c2]},
    )
    store = _FakeDailyMarkStore(
        read_map={
            (calendar_id, c1.contract_id): _daily_mark_df(contract_id=c1.contract_id),
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_product(
        calendar_id=calendar_id,
        product_id=c1.product_id,
    )

    assert len(out) == 2
    assert out["contract_id"].unique().tolist() == [c1.contract_id]


def test_read_daily_mark_product_returns_empty_canonical_frame_when_no_surfaces_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_id = "cme_emini_snp500_futures"
    c1 = _contract(
        contract_id="cme_emini_snp500_futures.Mar-2025",
        product_id=product_id,
    )
    refdata = _FakeRefDataAPI(by_product={product_id: [c1]})
    store = _FakeDailyMarkStore(read_map={})
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    out = dmapi.read_daily_mark_product(
        calendar_id="mxm_business_days_v1_2010-01-01_2050-12-31",
        product_id=product_id,
    )

    assert list(out.columns) == ["session_id", "contract_id", "product_id"]
    assert out.empty
    assert pd.api.types.is_integer_dtype(out["session_id"])


def test_read_daily_mark_product_passes_session_id_slice_to_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_id = "mxm_business_days_v1_2010-01-01_2050-12-31"
    c1 = _contract(
        contract_id="cme_emini_snp500_futures.Mar-2025",
        product_id="cme_emini_snp500_futures",
    )
    refdata = _FakeRefDataAPI(by_product={c1.product_id: [c1]})
    store = _FakeDailyMarkStore(
        read_map={
            (calendar_id, c1.contract_id): _daily_mark_df(contract_id=c1.contract_id),
        }
    )
    _patch_api_dependencies(monkeypatch, refdata=refdata, store=store)

    _ = dmapi.read_daily_mark_product(
        calendar_id=calendar_id,
        product_id=c1.product_id,
        start_session_id=100,
        end_session_id=200,
    )

    assert len(store.read_calls) == 1
    assert store.read_calls[0]["start_session_id"] == 100
    assert store.read_calls[0]["end_session_id"] == 200

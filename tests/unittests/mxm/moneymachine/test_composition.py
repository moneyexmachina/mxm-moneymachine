"""Tests for the Money Machine composition root."""

from typing import cast
from unittest.mock import Mock

from pytest import MonkeyPatch

import mxm.moneymachine.composition as composition
from mxm.moneymachine.runtime import MoneyMachine
from mxm.refdata import RefData
from mxm.runtime import RuntimeContext


def test_build_moneymachine_composes_refdata(
    monkeypatch: MonkeyPatch,
) -> None:
    ctx = cast(
        RuntimeContext,
        Mock(spec=RuntimeContext),
    )
    refdata = cast(
        RefData,
        Mock(spec=RefData),
    )

    build_refdata_mock = Mock(
        return_value=refdata,
    )

    monkeypatch.setattr(
        composition,
        "build_refdata",
        build_refdata_mock,
    )

    app = composition.build_moneymachine(ctx)

    build_refdata_mock.assert_called_once_with(ctx)

    assert isinstance(app, MoneyMachine)
    assert app.refdata is refdata

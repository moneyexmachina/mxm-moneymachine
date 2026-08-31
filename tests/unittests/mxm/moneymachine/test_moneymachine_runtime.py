"""Tests for the Money Machine runtime façade."""

from unittest.mock import Mock

from mxm.moneymachine.runtime import MoneyMachine
from mxm.refdata import RefData


def test_money_machine_exposes_refdata_application() -> None:
    refdata = Mock(spec=RefData)

    app = MoneyMachine(
        refdata=refdata,
    )

    assert app.refdata is refdata

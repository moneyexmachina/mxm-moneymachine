"""Runtime façade for the Money Ex Machina application."""

from __future__ import annotations

from mxm.refdata import RefData

__all__ = ["MoneyMachine"]


class MoneyMachine:
    """Assembled runtime façade for the Money Ex Machina application."""

    def __init__(
        self,
        *,
        refdata: RefData,
    ) -> None:
        self.refdata = refdata

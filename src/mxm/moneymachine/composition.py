"""Composition root for the Money Ex Machina application."""

from __future__ import annotations

from mxm.moneymachine.runtime import MoneyMachine
from mxm.refdata import build_refdata
from mxm.runtime import RuntimeContext

__all__ = ["build_moneymachine"]


def build_moneymachine(
    ctx: RuntimeContext,
) -> MoneyMachine:
    """Build the Money Machine object graph from a resolved RuntimeContext."""

    refdata = build_refdata(ctx)

    return MoneyMachine(
        refdata=refdata,
    )

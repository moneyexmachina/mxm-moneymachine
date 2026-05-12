"""
MXM V1 — Trade transition helpers.

This module contains pure functions operating on trade-like execution
state.

At the current stage of the execution design, the key trade-side
transition is:

    initial_holdings(t), target_holdings(t)
        ↓
    target_trades(t)

The type distinction is:

    ContractBundle
        realised / executable integer bundle

    TargetContractBundle
        intended / ideal real-valued bundle

Accordingly:

- initial_holdings are represented as ContractBundle
- target_holdings are represented as TargetContractBundle
- target_trades are represented as TargetContractBundle

This is intentional.

Target trades remain in target-space because they still represent ideal
desired changes in holdings. Only the executor later determines how
target trades become realised integer trades.

All functions in this module are pure:
they take bundle objects as inputs and return new bundle objects as
outputs, without mutating state.
"""

from __future__ import annotations

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle


def _as_target_bundle(bundle: ContractBundle) -> TargetContractBundle:
    """
    Lift a realised / executable bundle into target-space.

    This is a numeric-regime conversion only:

        contract_id -> integer lots
            becomes
        contract_id -> float quantities

    No semantic change beyond the target-space representation is implied.
    """
    return TargetContractBundle(bundle.quantities)


def build_target_trades(
    initial_holdings: ContractBundle,
    target_holdings: TargetContractBundle,
) -> TargetContractBundle:
    """
    Build target trades required to move from initial holdings to target
    holdings.

    Conceptually:

        target_trades = target_holdings - initial_holdings

    with the subtraction carried out in target-space.

    Parameters
    ----------
    initial_holdings:
        Decision-ready realised holdings entering the decision step.

    target_holdings:
        Ideal target holdings produced by the decision process.

    Returns
    -------
    TargetContractBundle
        Ideal desired trade quantities required to move from the current
        realised holdings to the target holdings.
    """
    initial_holdings_in_target_space = _as_target_bundle(initial_holdings)
    return target_holdings - initial_holdings_in_target_space

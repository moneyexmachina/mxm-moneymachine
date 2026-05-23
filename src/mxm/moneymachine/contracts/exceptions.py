"""
MXM V1 — Contract selection exceptions.

These exceptions define the *typed failure surface* of the contract-selection
layer. They are part of the semantic contract of the engine and must remain
stable once downstream layers depend on them.

Design principles
-----------------
- Explicit: no silent fallbacks, no implicit coercions
- Typed: callers can distinguish failure modes programmatically
- Informative: carry enough context for diagnostics and audit logs
"""

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ContractSelectionError(Exception):
    """
    Base class for all contract-selection failures.

    Downstream code should generally catch subclasses, not this base class.
    """

    pass


# ---------------------------------------------------------------------------
# Rule / configuration errors
# ---------------------------------------------------------------------------


class UnknownSelectorRule(ContractSelectionError):
    """
    Raised when a selector rule or its parameters are malformed or unsupported
    by the current engine version.

    Examples:
    - unsupported rank key
    - unsupported PeriodFilter basis
    - invalid period_type / elements combination
    """

    def __init__(self, message: str):
        super().__init__(message)


# ---------------------------------------------------------------------------
# Selection outcome errors
# ---------------------------------------------------------------------------


class NoEligibleContracts(ContractSelectionError):
    """
    Raised when *no contracts* remain after applying:
    - period filtering
    - eligibility predicate (as_of_session)

    This indicates that the selection intent is well-formed, but impossible
    at the given as_of_session.
    """

    def __init__(
        self,
        *,
        product_id: str,
        as_of_session: str | None = None,
        message: str | None = None,
    ):
        self.product_id = product_id
        self.as_of_session = as_of_session

        if message is None:
            if as_of_session is not None:
                message = (
                    f"No eligible contracts for product_id={product_id!r} "
                    f"as_of_session={as_of_session}"
                )
            else:
                message = f"No eligible contracts for product_id={product_id!r}"

        super().__init__(message)


class RelativeContractUnavailable(ContractSelectionError):
    """
    Raised when eligible contracts exist, but the requested depth `n`
    exceeds the available candidates.

    Example:
    - requesting n=3 when only 2 eligible contracts exist
    """

    def __init__(
        self,
        *,
        product_id: str,
        as_of_session: str | None = None,
        n: int,
        available: int,
        message: str | None = None,
    ):
        self.product_id = product_id
        self.as_of_session = as_of_session
        self.n = n
        self.available = available

        if message is None:
            if as_of_session is not None:
                message = (
                    f"Relative contract unavailable for product_id={product_id!r}, "
                    f"as_of_session={as_of_session}, "
                    f"requested n={n}, available={available}"
                )
            else:
                message = (
                    f"Relative contract unavailable for product_id={product_id!r}, "
                    f"requested n={n}, available={available}"
                )

        super().__init__(message)

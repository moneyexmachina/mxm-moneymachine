from __future__ import annotations

"""
Shared orchestration domain types (provisional).

This module defines the small, stable vocabulary used across the
`mxm.v1.marketdata.orchestration` package.

"Provisional" means:
- these types are intended to implement the MXM V1 normative semantics,
  but the authoritative status/status_detail taxonomy still lives in the
  normative semantics document(s);
- this vocabulary is deliberately coarse and dataset-agnostic;
- fine-grained reasons belong in *reason codes* (status_detail) rather than
  dataset-specific enums.

This module is pure and must not import:
- pandas / numpy
- dataset modules (`datasets/*`)
- vendor modules (`vendors/*`)
- stores (`stores/*`)

Semantic logic belongs in dedicated modules (e.g. `state.py`, `coverage.py`),
not here.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, NewType

# ---------------------------------------------------------------------------
# Identifiers (orchestration-level, opaque)
# ---------------------------------------------------------------------------

AttemptId = NewType("AttemptId", str)
RequestKey = NewType("RequestKey", str)


# ---------------------------------------------------------------------------
# Core decision vocabulary
# ---------------------------------------------------------------------------

DecisionAction = Literal["noop", "attempt_ingest", "stop_run"]


@dataclass(frozen=True)
class Decision:
    """
    Result of a pure orchestration decision.

    - action: what the orchestrator should do next
    - reason: short, stable, human-readable reason suitable for logs/reports
    """

    action: DecisionAction
    reason: str


# ---------------------------------------------------------------------------
# Budget / retry policies (shared across datasets)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """
    Minimal MVP retry policy (shared across datasets).

    Notes:
      - This is intentionally small and conservative.
      - Consecutive error counting may be approximate in early MVP.
    """

    max_consecutive_errors: int = 3
    stop_run_on_systemic_error: bool = True


@dataclass(frozen=True)
class BudgetContext:
    """
    Budget context for a run.

    The orchestration layer only uses this for gating decisions. Cost estimation
    and billable accounting remain vendor- and run-owned concerns.
    """

    remaining_usd: float


# ---------------------------------------------------------------------------
# Attempt outcome vocabulary (coarse status + fine detail)
# ---------------------------------------------------------------------------


class AttemptStatus(str, Enum):
    """
    Coarse, dataset-agnostic attempt status vocabulary.

    The intent is that every dataset can map its attempt outcomes to this set.

    Fine distinctions MUST be expressed in `status_detail` (reason codes).
    """

    # An ingestion attempt executed and resulted in persisted local data changes.
    INGESTED = "ingested"

    # The attempt executed but used local cache (no vendor pull).
    CACHED = "cached"

    # The attempt did not execute (policy gate, budget gate, etc.).
    SKIPPED = "skipped"

    # The attempt could not execute due to a blocking precondition.
    BLOCKED = "blocked"

    # The attempt executed but failed (retryable or systemic is encoded in detail).
    ERROR = "error"


class CacheStatus(str, Enum):
    """
    Whether the vendor payload was obtained from cache or fetched from vendor.

    This is intentionally coarse; any vendor-specific nuance belongs in vendors/.
    """

    HIT = "hit"
    MISS = "miss"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Reason-code vocabulary (fine detail)
# ---------------------------------------------------------------------------

# Keep these as Literals rather than Enums for now to avoid premature ossification.
# The normative semantics doc should eventually enumerate the canonical set.

BlockedReason = Literal[
    "blocked_unmapped",
    "blocked_empty_expected",
    "blocked_no_instruments",
    "blocked_precondition_failed",
    "blocked_unknown",
]

SkippedReason = Literal[
    "skipped_budget",
    "skipped_policy",
    "skipped_already_complete",
    "skipped_operator_noop",
    "skipped_unknown",
]

ErrorClass = Literal[
    "retryable",
    "systemic",
    "unknown",
]

# If you want, you can later separate "error_type" (exception class) from "error_class"
# (semantic category). The former should remain free-form strings.


# ---------------------------------------------------------------------------
# Completeness vocabulary (dataset-agnostic verdict)
# ---------------------------------------------------------------------------


class CompletenessVerdict(str, Enum):
    """
    Canonical completeness outcome for a (scope, expected window).

    This does NOT prescribe how completeness is proven; datasets provide evidence.

    The purpose is to allow a shared orchestration policy to treat different
    datasets consistently.
    """

    # Expected is fully satisfied by local evidence.
    COMPLETE = "complete"

    # Expected is not satisfied and should be attempted (subject to policy/budget).
    INCOMPLETE = "incomplete"

    # Expected is empty and therefore vacuously complete.
    VACUOUS = "vacuous"

    # Not complete, but acceptable to treat as done because vendor is final and
    # local evidence indicates "best possible" has been obtained.
    #
    # Example (OHLCV): vendor_final=True and we have *some* local data, but cannot
    # prove dense completeness due to observed-range limitations.
    ACCEPTABLE_PARTIAL_FINAL = "acceptable_partial_final"

    # Completeness could not be evaluated (insufficient evidence).
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Derived state vocabulary (generic windowed orchestration)
# ---------------------------------------------------------------------------


class DerivedState(str, Enum):
    """
    Coarse derived state vocabulary used to map conditions -> decisions.

    This is intentionally dataset-agnostic. Dataset-specific nuance belongs in
    reason codes (status_detail) and adapter-provided evidence.

    NOTE: event-stream datasets (e.g. instrument_definitions) may use a different
    derived state set; this one targets windowed / time-indexed facts datasets.
    """

    DONE = "done"
    BLOCKED = "blocked"
    NEEDS_INGEST = "needs_ingest"
    RETRYABLE_ERROR = "retryable_error"
    SKIPPED_BUDGET = "skipped_budget"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Core “attempt outcome” summary object (orchestration-facing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptOutcome:
    """
    Orchestration-facing summary of a single attempt.

    The full audit record (including dataset-specific fields) lives in the
    dataset's attempts store. This summary exists to:
      - drive generic decision logic,
      - support consistent reporting,
      - avoid importing dataset-specific attempt row models.
    """

    status: AttemptStatus
    status_detail: str  # should be one of the reason codes above when applicable

    request_key: RequestKey | None = None
    cache: CacheStatus = CacheStatus.UNKNOWN

    row_count: int | None = None

    # Error surfaces (free-form strings for now)
    error_class: ErrorClass | None = None
    error_type: str | None = None
    error_message: str | None = None

    # Optional cost surface for gating/reporting (if available)
    billable_usd: float | None = None

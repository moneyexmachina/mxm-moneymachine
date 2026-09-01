"""Prefect orchestration for MXM reference-data operations."""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from mxm.moneymachine.composition import build_moneymachine
from mxm.refdata.preflight import run_preflight
from mxm.runtime import RuntimeContext, build_runtime_context, build_runtime_identity

type RefDataFlowResultValue = str | int | bool | None
type RefDataFlowResult = dict[str, RefDataFlowResultValue]


def _runtime_context(
    *,
    environment: str,
    role: str,
) -> RuntimeContext:
    """Build one MXM runtime context for an independently executing task."""

    identity = build_runtime_identity(
        app="mxm-moneymachine",
        environment=environment,
        role=role,
    )

    return build_runtime_context(
        identity=identity,
    )


@task(
    name="refdata-preflight",
    retries=1,
    retry_delay_seconds=30,
)
def preflight_refdata_task(
    *,
    environment: str,
    role: str,
) -> None:
    """Verify that the selected runtime can operate reference data."""

    logger = get_run_logger()

    ctx = _runtime_context(
        environment=environment,
        role=role,
    )

    report = run_preflight(ctx)

    for check in report.checks:
        logger.info(
            "refdata preflight: check=%s passed=%s message=%s",
            check.name,
            check.passed,
            check.message,
        )

    if not report.passed:
        raise RuntimeError("Reference-data preflight failed.")

    logger.info(
        "Reference-data preflight passed: environment=%s role=%s",
        environment,
        role,
    )


@task(
    name="refdata-build",
    retries=1,
    retry_delay_seconds=30,
)
def build_refdata_task(
    *,
    environment: str,
    role: str,
) -> None:
    """Bring reference data to its configured materialised state."""

    logger = get_run_logger()

    ctx = _runtime_context(
        environment=environment,
        role=role,
    )

    moneymachine = build_moneymachine(ctx)

    logger.info(
        "Starting reference-data build: environment=%s role=%s",
        environment,
        role,
    )

    moneymachine.refdata.build()

    logger.info(
        "Reference-data build completed: environment=%s role=%s",
        environment,
        role,
    )


@task(
    name="refdata-diagnostics",
    retries=1,
    retry_delay_seconds=30,
)
def diagnose_refdata_task(
    *,
    environment: str,
    role: str,
) -> RefDataFlowResult:
    """Verify the operational state produced by the reference-data build."""

    logger = get_run_logger()

    ctx = _runtime_context(
        environment=environment,
        role=role,
    )

    moneymachine = build_moneymachine(ctx)
    report = moneymachine.refdata.diagnostics()

    for result in report.results:
        logger.info(
            "refdata diagnostic: check=%s status=%s message=%s",
            result.name,
            result.status,
            result.message,
        )

    if report.counts is None:
        products = None
        contracts = None
        periods = None
        cycles = None
    else:
        products = report.counts.products
        contracts = report.counts.contracts
        periods = report.counts.periods
        cycles = report.counts.cycles

        logger.info(
            "Reference-data counts: products=%s contracts=%s periods=%s cycles=%s",
            products,
            contracts,
            periods,
            cycles,
        )

    if not report.ready:
        raise RuntimeError("Reference-data diagnostics failed after build.")

    logger.info(
        "Reference-data diagnostics passed: environment=%s role=%s",
        environment,
        role,
    )

    return {
        "environment": environment,
        "role": role,
        "ready": report.ready,
        "products": products,
        "contracts": contracts,
        "periods": periods,
        "cycles": cycles,
    }


@flow(name="mxm-refdata-build")
def refdata_build_flow(
    *,
    environment: str = "dev",
    role: str = "default",
) -> RefDataFlowResult:
    """Build and verify MXM reference data in one operational workflow."""

    preflight_refdata_task(
        environment=environment,
        role=role,
    )

    build_refdata_task(
        environment=environment,
        role=role,
    )

    return diagnose_refdata_task(
        environment=environment,
        role=role,
    )

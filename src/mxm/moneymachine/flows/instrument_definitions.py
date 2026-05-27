from __future__ import annotations

from typing import cast

from prefect import flow, get_run_logger, task

from mxm.moneymachine.marketdata.datasets.instrument_definitions.ingest import Mode
from mxm.moneymachine.marketdata.ops.instrument_definitions import (
    InstrumentDefinitionsRunRequest,
    run_instrument_definitions,
)
from mxm.moneymachine.runtime.execution_context import ExecutionContext
from mxm.moneymachine.utils.json_normalise import json_value_from_obj


def prefect_execution_context() -> ExecutionContext:
    return ExecutionContext(runtime_kind="prefect")


@task(
    name="run-instrument-definitions",
    retries=1,
    retry_delay_seconds=30,
)
def run_instrument_definitions_task(
    *,
    request: InstrumentDefinitionsRunRequest,
    execution_context: ExecutionContext,
) -> dict[str, object]:
    report = run_instrument_definitions(
        request=request,
        execution_context=execution_context,
    )

    payload = json_value_from_obj(report)
    if not isinstance(payload, dict):
        raise TypeError("instrument definitions report did not normalize to object")

    return cast(dict[str, object], payload)


@flow(name="instrument-definitions-flow")
def instrument_definitions_flow(
    *,
    product_id: str,
    mode: Mode = "update",
    reset: bool = False,
    cost_cap_usd: float = 1.0,
    window_days: int = 31,
    max_windows: int = 1,
    overlap: str = "1d",
    end: str | None = None,
    databento_api_key_secret_path: str = "mxm/dev/databento/api-key",
) -> dict[str, object]:
    logger = get_run_logger()

    request = InstrumentDefinitionsRunRequest(
        product_id=product_id,
        mode=mode,
        reset=reset,
        cost_cap_usd=cost_cap_usd,
        window_days=window_days,
        max_windows=max_windows,
        overlap=overlap,
        end=end,
        databento_api_key_secret_path=databento_api_key_secret_path,
    )

    logger.info(
        "Running instrument definitions ingest for product_id=%s mode=%s max_windows=%s",
        product_id,
        mode,
        max_windows,
    )

    result = run_instrument_definitions_task(
        request=request,
        execution_context=prefect_execution_context(),
    )

    logger.info(
        "Instrument definitions ingest finished for product_id=%s stopped_reason=%s",
        product_id,
        result.get("stopped_reason"),
    )

    return result


if __name__ == "__main__":
    instrument_definitions_flow(product_id="cme_emini_snp500_futures")

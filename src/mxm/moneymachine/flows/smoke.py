from __future__ import annotations

from prefect import flow, get_run_logger


@flow(name="mxm-smoke-flow")
def smoke_flow(message: str = "hello from mxm") -> str:
    logger = get_run_logger()
    logger.info("Smoke flow received message: %s", message)
    return message


if __name__ == "__main__":
    smoke_flow()

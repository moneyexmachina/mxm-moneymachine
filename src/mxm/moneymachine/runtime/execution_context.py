from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RuntimeKind = Literal[
    "local",
    "cli",
    "prefect",
    "test",
]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """
    Runtime execution provenance for MXM operational execution.

    The execution context captures information about the runtime environment
    under which a semantic operation is being executed.

    The context is intentionally orchestration-framework agnostic.

    Domain code should depend on ExecutionContext rather than directly on
    Prefect runtime objects.
    """

    runtime_kind: RuntimeKind

    run_id: str | None = None

    flow_run_id: str | None = None
    task_run_id: str | None = None
    deployment_id: str | None = None

    work_pool_name: str | None = None
    worker_name: str | None = None

    operator: str | None = None


def local_execution_context() -> ExecutionContext:
    """
    Create a local execution context.

    Intended for:
    - local development,
    - ad hoc execution,
    - debugging,
    - non-orchestrated runs.
    """
    return ExecutionContext(runtime_kind="local")


def cli_execution_context() -> ExecutionContext:
    """
    Create a CLI execution context.

    Intended for:
    - explicit CLI-triggered operational runs,
    - local operator invocation.
    """
    return ExecutionContext(runtime_kind="cli")


def test_execution_context() -> ExecutionContext:
    """
    Create a test execution context.

    Intended for:
    - unit tests,
    - integration tests,
    - deterministic replay environments.
    """
    return ExecutionContext(runtime_kind="test")

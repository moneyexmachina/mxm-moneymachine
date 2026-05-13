#
# MXM V1 — Instrument definition mappings jobs.
#
# This module defines runtime-facing jobs for the
# `instrument_definition_mappings` dataset.
#
# In the Session 35 architecture, a job is:
# - a named unit of work
# - executed in a single runtime
# - responsible for constructing the dependencies it needs
# - responsible for calling the underlying dataset operation
#
# This module therefore sits above:
# - `build.py`    → core dataset operation / domain logic
#
# and below:
# - CLI adapters  → user-facing command invocation
# - schedulers    → timed or event-driven execution
#
# Important:
# - This module does not parse CLI arguments.
# - This module does not implement cross-runtime orchestration.
# - This module does not own dataset semantics; it instantiates runtime
#   dependencies and invokes the canonical build function.

from __future__ import annotations

from pathlib import Path
from typing import Literal

from mxm.v1.marketdata.datasets.instrument_definition_mappings.build import (
    InstrumentDefinitionMappingsBuildReport,
    rebuild_instrument_definition_mappings,
)
from mxm.v1.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

Mode = Literal["bootstrap", "update"]


def rebuild_instrument_definition_mappings_for_product(
    *,
    product_id: str,
    mode: Mode = "update",
    reset: bool = False,
    root: Path | None = None,
) -> InstrumentDefinitionMappingsBuildReport:
    """
    Rebuild instrument definition mappings for a single product.

    This job constructs the required runtime dependencies for the
    `instrument_definition_mappings` dataset and then invokes the canonical
    build operation in `build.py`.

    Parameters
    ----------
    product_id:
        MXM product identifier.
    mode:
        Build mode.
        - "bootstrap": first-time build, often after reset
        - "update": safe rerun / append-only update semantics
    reset:
        Whether to delete product-scoped mapping rows before rebuilding.
    root:
        Optional MXM storage root. Defaults to ``Path.home() / ".mxm"``.

    Returns
    -------
    InstrumentDefinitionMappingsBuildReport
        Structured report returned by the underlying build operation.

    Notes
    -----
    This is a single-runtime atomic job. It is suitable for:
    - direct Python invocation
    - invocation via the unified MXM CLI
    - invocation by an external scheduler

    It is not responsible for:
    - CLI parsing
    - multi-job orchestration
    - scheduling policy
    """
    resolved_root = root if root is not None else (Path.home() / ".mxm")

    layout = MarketdataLayout(root=resolved_root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    defs_store = InstrumentDefinitionsStore(backend=backend)
    mappings_store = InstrumentDefinitionMappingsStore(backend=backend)

    return rebuild_instrument_definition_mappings(
        defs_store=defs_store,
        mappings_store=mappings_store,
        product_id=product_id,
        mode=mode,
        reset=bool(reset),
    )

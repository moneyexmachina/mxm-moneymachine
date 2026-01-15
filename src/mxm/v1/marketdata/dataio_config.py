from __future__ import annotations

from pathlib import Path

from mxm.config import MXMConfig, make_subconfig


def marketdata_dataio_cfg() -> MXMConfig:
    """
    DataIO request archive configuration for MXM V1 marketdata ingestion.

    Root:
        ~/.mxm/dataio/marketdata/

    Returns
    -------
    MXMConfig
        A config-shaped object (OmegaConf DictConfig typed as MXMConfig)
        providing:

            cfg.paths.root
            cfg.paths.db_path
            cfg.paths.responses_dir
    """
    root = Path.home() / ".mxm" / "dataio" / "marketdata"
    db_path = root / "dataio.sqlite"
    responses_dir = root / "responses"

    root.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    return make_subconfig(
        {
            "paths": {
                "root": root,
                "db_path": db_path,
                "responses_dir": responses_dir,
            }
        },
        readonly=True,
        resolve=False,
    )

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """
    Compute SHA256 hex digest for a file.

    Parameters
    ----------
    path:
        File path to hash.
    chunk_bytes:
        Read chunk size. Default is 1 MiB.

    Returns
    -------
    str
        Lowercase hex digest.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_bytes), b""):
            h.update(chunk)
    return h.hexdigest()

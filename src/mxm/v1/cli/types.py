from __future__ import annotations

import argparse
from typing import Protocol


class Subparsers(Protocol):
    def add_parser(
        self,
        name: str,
        **kwargs: object,
    ) -> argparse.ArgumentParser: ...

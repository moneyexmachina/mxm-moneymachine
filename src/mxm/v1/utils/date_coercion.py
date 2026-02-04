# src/mxm/v1/utils/date_coercion.py
from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np


def coerce_np_day(value: Any) -> np.datetime64:
    """
    Coerce a date-like input into numpy datetime64[D].

    Accepted:
      - datetime.date
      - datetime.datetime
      - numpy.datetime64
      - str ('YYYY-MM-DD' or ISO8601-ish accepted by numpy)
    """
    if value is None:
        raise TypeError("day value is None")

    if isinstance(value, np.datetime64):
        return value.astype("datetime64[D]")

    if isinstance(value, dt.datetime):
        value = value.date()

    if isinstance(value, dt.date):
        return np.datetime64(value).astype("datetime64[D]")  # type: ignore[reportCallIssue]

    if isinstance(value, str):
        return np.datetime64(value).astype("datetime64[D]")  # type: ignore[reportCallIssue]

    raise TypeError(f"unsupported day type: {type(value).__name__} value={value!r}")

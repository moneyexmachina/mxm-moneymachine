"""
MXM V1 — MXM business calendar builder.

This module builds the canonical MXM business calendar artifact for MXM V1.

Current policy
--------------
The current MXM business calendar policy is:

- daily UTC-aligned business sessions
- include all weekdays (Monday to Friday)
- exclude January 1
- exclude December 25

The builder is intentionally narrow and deterministic. It does not depend on
trading calendars and does not encode venue-specific holiday logic. It simply
constructs the operative MXM business-session domain for the requested date
span.

This is a boundary/construction module. Small input normalization is acceptable
here. The returned `MXMBusinessCalendar` remains the strict validated core
artifact.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from mxm.moneymachine.calendars.mxm_business_calendar import MXMBusinessCalendar


def _as_day_scalar(value: np.datetime64, *, name: str) -> np.datetime64:
    """
    Normalize a datetime64 scalar to day resolution.

    Parameters
    ----------
    value:
        Input datetime64 scalar.
    name:
        Parameter name for error messages.

    Returns
    -------
    np.datetime64
        The same scalar represented as `datetime64[D]`.

    Raises
    ------
    ValueError
        If the normalized value is NaT.
    """
    out = value.astype("datetime64[D]")

    if np.isnat(out):
        raise ValueError(f"{name} must not be NaT")

    return out


def _validate_day_span(
    *,
    start_label: np.datetime64,
    end_label: np.datetime64,
) -> None:
    """
    Validate that the requested builder span is ordered.
    """
    if start_label > end_label:
        raise ValueError(f"start_label {start_label} must be <= end_label {end_label}")


def _generate_day_span(
    *,
    start_label: np.datetime64,
    end_label: np.datetime64,
) -> NDArray[np.datetime64]:
    """
    Generate the inclusive civil-day span `[start_label, end_label]`
    at `datetime64[D]` resolution.
    """
    return np.arange(
        start_label,
        end_label + np.timedelta64(1, "D"),
        np.timedelta64(1, "D"),
        dtype="datetime64[D]",
    )


def _weekday_mask(labels: NDArray[np.datetime64]) -> NDArray[np.bool_]:
    """
    Return a mask selecting Monday-Friday labels.

    Notes
    -----
    NumPy stores `datetime64[D]` as integer days relative to the Unix epoch.
    1970-01-01 was a Thursday. Mapping Monday->0, ..., Sunday->6 is therefore:

        weekday = (days_since_epoch + 3) % 7
    """
    days_since_epoch = labels.view("int64")
    weekday = (days_since_epoch + 3) % 7
    return weekday < 5


def _fixed_exclusion_mask(labels: NDArray[np.datetime64]) -> NDArray[np.bool_]:
    """
    Return a mask selecting labels excluded by the current MXM business-calendar
    policy.

    Current exclusions:
    - January 1
    - December 25
    """
    out = np.zeros(labels.size, dtype=bool)

    for i, label in enumerate(labels):
        label_str = str(label)
        month_day = label_str[5:10]
        out[i] = month_day in {"01-01", "12-25"}

    return out


def build_mxm_business_calendar(
    *,
    calendar_id: str,
    start_label: np.datetime64,
    end_label: np.datetime64,
) -> MXMBusinessCalendar:
    """
    Build the canonical MXM business calendar over an inclusive date span.

    Policy
    ------
    The current builder policy is:

    - include all weekdays
    - exclude January 1
    - exclude December 25

    Parameters
    ----------
    calendar_id:
        Identifier for the resulting business calendar artifact.
    start_label:
        Inclusive start date of the requested span.
    end_label:
        Inclusive end date of the requested span.

    Returns
    -------
    MXMBusinessCalendar
        The constructed business calendar artifact.

    Raises
    ------
    ValueError
        If the input span is invalid or if the filtered span contains no
        business sessions.
    """
    start_day = _as_day_scalar(start_label, name="start_label")
    end_day = _as_day_scalar(end_label, name="end_label")

    _validate_day_span(start_label=start_day, end_label=end_day)

    all_days = _generate_day_span(start_label=start_day, end_label=end_day)

    included_mask = _weekday_mask(all_days) & ~_fixed_exclusion_mask(all_days)
    labels = all_days[included_mask]

    if labels.size == 0:
        raise ValueError(
            "Requested date span contains no MXM business sessions "
            "after applying the business-calendar policy."
        )

    session_ids = np.arange(labels.size, dtype=np.int64)
    start_ts = labels.astype("datetime64[ns]")
    end_ts = (start_ts + np.timedelta64(1, "D")).astype("datetime64[ns]")

    return MXMBusinessCalendar(
        calendar_id=calendar_id,
        session_ids=session_ids,
        labels=labels,
        start_ts=start_ts,
        end_ts=end_ts,
    )

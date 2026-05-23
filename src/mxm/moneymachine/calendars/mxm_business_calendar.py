"""
MXM V1 — MXMBusinessCalendar core model.

This module defines the canonical MXM business calendar artifact for MXM V1.

Core concept
------------
An MXM business calendar defines an ordered session domain for MXM operating
time. A session is identified by:

    (calendar_id, session_id)

where:

- `calendar_id` identifies the calendar artifact
- `session_id` is a dense integer coordinate within that calendar

The calendar also provides two attached representations for each session:

1. `label`
   A human-readable session label, represented in V1 as `np.datetime64[D]`

2. `(start_ts, end_ts)`
   A canonical timestamp embedding of the session as a half-open interval
   `[start_ts, end_ts)`, represented in canonical MXM timestamp form
   `np.datetime64[ns]`

V1 scope
--------
In V1, MXM business sessions are daily UTC-aligned operating sessions:

- session ids are dense integers
- labels are UTC civil dates
- start timestamps are UTC midnight for the label date
- end timestamps are UTC midnight on the following civil date

This calendar artifact is authoritative for the MXM business-session domain.
It does not encode:

- exchange microstructure
- venue open / close schedules
- product-specific settlement timing
- execution feasibility
- data availability
- mark fallback policy

Those belong to downstream layers.

Design principles
-----------------
- session identity is `(calendar_id, session_id)`
- labels are representations, not identity
- timestamps are explicit and canonical
- the calendar artifact is immutable
- construction validates strictly and eagerly
- no convenience session arithmetic is embedded here; dense integer arithmetic
  and slicing are left to client code
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray

from mxm.moneymachine.utils.timestamps import (
    TSNSArray,
    assert_monotonic_increasing_ts_ns_array,
    assert_no_nat,
    assert_ts_ns_array,
)


def canonical_calendar_id(value: str) -> str:
    """
    Canonicalise an MXM business calendar id.

    Policy:
    - strip surrounding whitespace
    - lower-case

    Parameters
    ----------
    value:
        Raw calendar id.

    Returns
    -------
    str
        Canonical calendar id.

    Raises
    ------
    ValueError
        If the canonicalised id is empty.
    """
    out = value.strip().lower()
    if out == "":
        raise ValueError("calendar_id must not be empty")
    return out


def _assert_1d_array(value: NDArray[np.generic], *, name: str) -> None:
    """
    Assert that `value` is 1-dimensional.
    """
    if value.ndim != 1:
        raise ValueError(f"{name} must be 1D, got ndim={value.ndim}")


def _assert_dtype_exact(
    value: NDArray[np.generic],
    *,
    name: str,
    expected: str | np.dtype | type[np.generic],
) -> None:
    """
    Assert that `value.dtype` matches `expected` exactly.
    """
    expected_dtype = np.dtype(expected)
    if value.dtype != expected_dtype:
        raise TypeError(f"{name} must have dtype {expected_dtype}, got {value.dtype}")


def _assert_day_array(value: NDArray[np.generic], *, name: str) -> None:
    """
    Assert that `value` is a 1D datetime64[D] ndarray with no NaT.
    """
    _assert_1d_array(value, name=name)
    _assert_dtype_exact(value, name=name, expected="datetime64[D]")

    if np.any(np.isnat(value)):
        raise ValueError(f"{name} must not contain NaT")


def _assert_int64_array(value: NDArray[np.generic], *, name: str) -> None:
    """
    Assert that `value` is a 1D int64 ndarray.
    """
    _assert_1d_array(value, name=name)
    _assert_dtype_exact(value, name=name, expected=np.int64)


def _assert_ts_ns_array_strict(
    value: NDArray[np.generic],
    *,
    name: str,
) -> None:
    """
    Assert that `value` is a 1D datetime64[ns] ndarray in canonical TSNS form.
    """
    _assert_1d_array(value, name=name)
    assert_ts_ns_array(value)
    arr = cast(TSNSArray, value)
    assert_no_nat(arr)


def _coerce_day_scalar_strict(value: np.datetime64, *, name: str) -> np.datetime64:
    """
    Convert an np.datetime64 scalar to datetime64[D] for lookup.

    Raises
    ------
    ValueError
        If the result is NaT.
    """
    out = value.astype("datetime64[D]")

    if np.isnat(out):
        raise ValueError(f"{name} must not be NaT")

    return out


def _searchsorted_exact_day(
    labels: NDArray[np.datetime64],
    target: np.datetime64,
) -> int | None:
    """
    Return the exact index of `target` in a sorted datetime64[D] label array,
    or None if absent.
    """
    idx = int(np.searchsorted(labels, target, side="left"))
    if idx >= labels.size:
        return None
    if labels[idx] != target:
        return None
    return idx


@dataclass(frozen=True, slots=True)
class MXMBusinessCalendar:
    """
    Immutable MXM business calendar artifact.

    Parameters
    ----------
    calendar_id:
        Stable identifier for the calendar artifact.
    session_ids:
        Dense integer session coordinates. Must be exactly `0, 1, ..., N-1`.
    labels:
        Session labels as `datetime64[D]`, strictly increasing and unique.
    start_ts:
        Session start timestamps as canonical `datetime64[ns]`.
    end_ts:
        Session end timestamps as canonical `datetime64[ns]`.

    Notes
    -----
    Session identity is:

        (calendar_id, session_id)

    Labels and timestamps are attached representations of that identity.

    For the V1 daily business calendar, the required alignment is:

    - `start_ts[i] == labels[i] cast to datetime64[ns]`
    - `end_ts[i]   == start_ts[i] + 1 day`
    """

    calendar_id: str
    session_ids: NDArray[np.int64]
    labels: NDArray[np.datetime64]
    start_ts: NDArray[np.datetime64]
    end_ts: NDArray[np.datetime64]

    def __post_init__(self) -> None:
        object.__setattr__(self, "calendar_id", canonical_calendar_id(self.calendar_id))

        _assert_int64_array(self.session_ids, name="session_ids")
        _assert_day_array(self.labels, name="labels")
        _assert_ts_ns_array_strict(self.start_ts, name="start_ts")
        _assert_ts_ns_array_strict(self.end_ts, name="end_ts")

        self._validate_lengths(
            session_ids=self.session_ids,
            labels=self.labels,
            start_ts=self.start_ts,
            end_ts=self.end_ts,
        )
        self._validate_non_empty(session_ids=self.session_ids)
        self._validate_session_ids(session_ids=self.session_ids)
        self._validate_labels(labels=self.labels)
        self._validate_timestamps(start_ts=self.start_ts, end_ts=self.end_ts)
        self._validate_v1_alignment(
            labels=self.labels, start_ts=self.start_ts, end_ts=self.end_ts
        )

    @staticmethod
    def _validate_lengths(
        *,
        session_ids: NDArray[np.int64],
        labels: NDArray[np.datetime64],
        start_ts: NDArray[np.datetime64],
        end_ts: NDArray[np.datetime64],
    ) -> None:
        n = session_ids.size
        if labels.size != n:
            raise ValueError(f"labels size {labels.size} != session_ids size {n}")
        if start_ts.size != n:
            raise ValueError(f"start_ts size {start_ts.size} != session_ids size {n}")
        if end_ts.size != n:
            raise ValueError(f"end_ts size {end_ts.size} != session_ids size {n}")

    @staticmethod
    def _validate_non_empty(
        *,
        session_ids: NDArray[np.int64],
    ) -> None:
        if session_ids.size == 0:
            raise ValueError("calendar must contain at least one session")

    @staticmethod
    def _validate_session_ids(
        *,
        session_ids: NDArray[np.int64],
    ) -> None:
        expected = np.arange(session_ids.size, dtype=np.int64)
        if not np.array_equal(session_ids, expected):
            raise ValueError("session_ids must be exactly the dense sequence 0..N-1")

    @staticmethod
    def _validate_labels(
        *,
        labels: NDArray[np.datetime64],
    ) -> None:
        if labels.size <= 1:
            return

        diffs = labels[1:] - labels[:-1]
        if not np.all(diffs > np.timedelta64(0, "D")):
            raise ValueError("labels must be strictly increasing and unique")

    @staticmethod
    def _validate_timestamps(
        *,
        start_ts: NDArray[np.datetime64],
        end_ts: NDArray[np.datetime64],
    ) -> None:
        assert_monotonic_increasing_ts_ns_array(start_ts)
        assert_monotonic_increasing_ts_ns_array(end_ts)

        if not np.all(start_ts < end_ts):
            raise ValueError("every session must satisfy start_ts < end_ts")

        if start_ts.size <= 1:
            return

        if not np.all(end_ts[:-1] <= start_ts[1:]):
            raise ValueError("session intervals must be ordered and non-overlapping")

    @staticmethod
    def _validate_v1_alignment(
        *,
        labels: NDArray[np.datetime64],
        start_ts: NDArray[np.datetime64],
        end_ts: NDArray[np.datetime64],
    ) -> None:
        expected_start_ts = labels.astype("datetime64[ns]")
        if not np.array_equal(start_ts, expected_start_ts):
            raise ValueError(
                "start_ts must equal labels cast to datetime64[ns] "
                "(UTC-midnight embedding)"
            )

        expected_end_ts = expected_start_ts + np.timedelta64(1, "D")
        if not np.array_equal(end_ts, expected_end_ts):
            raise ValueError("end_ts must equal start_ts + 1 day for every session")

    def __len__(self) -> int:
        """
        Return the number of sessions in the calendar.
        """
        return int(self.session_ids.size)

    def contains_session_id(self, session_id: int) -> bool:
        """
        Return True iff `session_id` is valid for this calendar.
        """
        return 0 <= session_id < len(self)

    def validate_session_id(self, session_id: int) -> None:
        """
        Validate that `session_id` is a valid session coordinate for this
        calendar.

        Raises
        ------
        ValueError
            If `session_id` lies outside the calendar domain.
        """

        if session_id < 0 or session_id >= len(self):
            raise ValueError(
                f"session_id {session_id} is outside valid range "
                f"[0, {len(self) - 1}] for calendar {self.calendar_id!r}"
            )

    def contains_label(self, label: np.datetime64) -> bool:
        """
        Return True iff `label` exists in this calendar.
        """
        day = _coerce_day_scalar_strict(label, name="label")
        return _searchsorted_exact_day(self.labels, day) is not None

    def session_id_from_label(self, label: np.datetime64) -> int:
        """
        Return the session id corresponding to `label`.

        Raises
        ------
        ValueError
            If `label` is not present in this calendar.
        """
        day = _coerce_day_scalar_strict(label, name="label")
        idx = _searchsorted_exact_day(self.labels, day)
        if idx is None:
            raise ValueError(
                f"label {day} is not present in calendar {self.calendar_id!r}"
            )
        return int(self.session_ids[idx])

    def label_from_session_id(self, session_id: int) -> np.datetime64:
        """
        Return the label attached to `session_id`.
        """
        self.validate_session_id(session_id)
        return self.labels[session_id]

    def start_ts_from_session_id(self, session_id: int) -> np.datetime64:
        """
        Return the start timestamp attached to `session_id`.
        """
        self.validate_session_id(session_id)
        return self.start_ts[session_id]

    def end_ts_from_session_id(self, session_id: int) -> np.datetime64:
        """
        Return the end timestamp attached to `session_id`.
        """
        self.validate_session_id(session_id)
        return self.end_ts[session_id]

    def bounds_from_session_id(
        self,
        session_id: int,
    ) -> tuple[np.datetime64, np.datetime64]:
        """
        Return `(start_ts, end_ts)` attached to `session_id`.
        """
        self.validate_session_id(session_id)
        return self.start_ts[session_id], self.end_ts[session_id]

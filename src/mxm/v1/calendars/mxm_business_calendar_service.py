from __future__ import annotations

"""
MXM V1 — MXM business calendar service.

This module provides a thin runtime wrapper around
`build_mxm_business_calendar(...)`.

Purpose
-------
The service exists for ergonomic runtime use in scripts and orchestration
layers:

- configure one canonical MXM business calendar span
- build lazily
- cache in memory
- hand out the same immutable calendar artifact on repeated access

This service does not persist calendars and does not derive them from trading
calendars. It simply wraps the rule-based MXM business-calendar builder.
"""

from dataclasses import dataclass, field

import numpy as np

from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.mxm_business_calendar_builder import (
    build_mxm_business_calendar,
)


@dataclass(slots=True)
class MXMBusinessCalendarService:
    """
    Thin runtime constructor/cache for the MXM business calendar.

    Parameters
    ----------
    calendar_id:
        Identifier assigned to the resulting MXM business calendar artifact.
    start_label:
        Inclusive start label of the calendar span.
    end_label:
        Inclusive end label of the calendar span.
    """

    calendar_id: str
    start_label: np.datetime64
    end_label: np.datetime64
    _cache: MXMBusinessCalendar | None = field(default=None, init=False)

    def get_calendar(self) -> MXMBusinessCalendar:
        """
        Return the configured MXM business calendar.

        The result is built lazily and cached in memory.
        """
        if self._cache is not None:
            return self._cache

        calendar = build_mxm_business_calendar(
            calendar_id=self.calendar_id,
            start_label=self.start_label,
            end_label=self.end_label,
        )
        self._cache = calendar
        return calendar

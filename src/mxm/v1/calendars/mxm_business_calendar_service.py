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
- derive one canonical calendar identity from:
    - structural calendar base id
    - start label
    - end label
- build lazily
- cache in memory
- hand out the same immutable calendar artifact on repeated access

Identity semantics
------------------
The resulting `calendar_id` must be sufficient to identify the exact calendar
artifact semantics relevant to downstream datasets and orchestration.

Therefore the effective calendar identity includes:
- the structural calendar base id (e.g. "mxm_business_days_v1")
- the inclusive start label
- the inclusive end label

This ensures that downstream systems only need to persist / compare
`calendar_id`, not additional calendar span metadata.

This service does not persist calendars and does not derive them from trading
calendars. It simply wraps the rule-based MXM business-calendar builder.
"""

from dataclasses import dataclass, field

import numpy as np

from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.mxm_business_calendar_builder import (
    build_mxm_business_calendar,
)
from mxm.v1.utils.date_utils import coerce_np_day, fmt_iso_day


def build_mxm_business_calendar_id(
    *,
    calendar_base_id: str,
    start_label: np.datetime64,
    end_label: np.datetime64,
) -> str:
    """
    Build the canonical MXM business-calendar identity string.

    The identity is derived from:
    - structural calendar base id
    - inclusive start label
    - inclusive end label

    Example
    -------
    mxm_business_days_v1_2010-01-01_2050-12-31
    """
    start_day = coerce_np_day(start_label)
    end_day = coerce_np_day(end_label)

    if end_day < start_day:
        raise ValueError(
            "calendar end_label must be >= start_label, "
            f"got start_label={fmt_iso_day(start_day)!r}, "
            f"end_label={fmt_iso_day(end_day)!r}"
        )

    return f"{calendar_base_id}_{fmt_iso_day(start_day)}_{fmt_iso_day(end_day)}"


@dataclass(slots=True)
class MXMBusinessCalendarService:
    """
    Thin runtime constructor/cache for the MXM business calendar.

    Parameters
    ----------
    calendar_base_id:
        Structural identifier for the calendar rule set, e.g.
        "mxm_business_days_v1".

        This should be version-bumped whenever the structural calendar behavior
        changes (holiday rules, business-day rules, etc.).

    start_label:
        Inclusive start label of the calendar span.

    end_label:
        Inclusive end label of the calendar span.

    Notes
    -----
    The effective calendar artifact identity exposed to downstream systems is
    the derived `calendar_id`, not `calendar_base_id` alone.
    """

    calendar_base_id: str
    start_label: np.datetime64
    end_label: np.datetime64
    _cache: MXMBusinessCalendar | None = field(default=None, init=False)

    @property
    def calendar_id(self) -> str:
        """
        Return the canonical effective calendar identity.

        This identity fully captures:
        - structural calendar version (`calendar_base_id`)
        - inclusive calendar span (`start_label`, `end_label`)
        """
        return build_mxm_business_calendar_id(
            calendar_base_id=self.calendar_base_id,
            start_label=self.start_label,
            end_label=self.end_label,
        )

    def get_calendar(self) -> MXMBusinessCalendar:
        """
        Return the configured MXM business calendar.

        The result is built lazily and cached in memory.
        """
        if self._cache is not None:
            return self._cache

        start_day = coerce_np_day(self.start_label)
        end_day = coerce_np_day(self.end_label)

        if end_day < start_day:
            raise ValueError(
                "calendar end_label must be >= start_label, "
                f"got start_label={fmt_iso_day(start_day)!r}, "
                f"end_label={fmt_iso_day(end_day)!r}"
            )

        calendar = build_mxm_business_calendar(
            calendar_id=self.calendar_id,
            start_label=start_day,
            end_label=end_day,
        )
        self._cache = calendar
        return calendar

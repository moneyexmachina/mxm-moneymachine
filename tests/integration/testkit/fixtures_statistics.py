from __future__ import annotations

import pandas as pd


def make_statistics_1d_rawish_df(
    *, instrument_id: int, raw_symbol: str = "TEST.2020-01"
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                stat_type=3,
                ts_event=pd.Timestamp("2020-01-02T20:00:00Z"),
                ts_recv=pd.Timestamp("2020-01-02T20:00:01Z"),
                ts_ref=pd.Timestamp("2020-01-02T00:00:00Z"),
                sequence=1,
                price=3200.25,
                stat_flags=0,
                is_final=False,
                is_actual=True,
            ),
            dict(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                stat_type=3,
                ts_event=pd.Timestamp("2020-01-02T22:00:00Z"),
                ts_recv=pd.Timestamp("2020-01-02T22:00:01Z"),
                ts_ref=pd.Timestamp("2020-01-02T00:00:00Z"),
                sequence=2,
                price=3200.50,
                stat_flags=1,
                is_final=True,
                is_actual=True,
            ),
            dict(
                instrument_id=instrument_id,
                raw_symbol=raw_symbol,
                stat_type=3,
                ts_event=pd.Timestamp("2020-01-03T20:00:00Z"),
                ts_recv=pd.Timestamp("2020-01-03T20:00:01Z"),
                ts_ref=pd.Timestamp("2020-01-03T00:00:00Z"),
                sequence=1,
                price=3210.00,
                stat_flags=0,
                is_final=False,
                is_actual=True,
            ),
        ]
    )

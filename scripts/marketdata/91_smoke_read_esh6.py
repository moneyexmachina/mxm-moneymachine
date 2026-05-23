from __future__ import annotations

from pathlib import Path

from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.parquet.daily_bars import read_daily_bars


def main() -> None:
    dataset = "GLBX.MDP3"
    publisher_id = 1
    instrument_id = 42140878  # from the ingest output

    mxm_root = Path.home() / ".mxm"
    layout = MarketdataLayout(root=mxm_root)

    df = read_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )

    print(f"[ok] read {len(df)} rows from store")
    print(f"[info] ts_event range: {df['ts_event'].min()} .. {df['ts_event'].max()}")
    print("[info] head:")
    print(df.head(3).to_string(index=False))
    print("[info] tail:")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

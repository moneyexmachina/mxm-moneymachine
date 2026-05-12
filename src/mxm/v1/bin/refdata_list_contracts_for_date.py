from datetime import date

from mxm.refdata.api.ref_data_api import RefDataAPI


def main() -> None:
    TARGET_DATE = date(
        2021, 6, 15
    )  # choose a date where many products have a live contract
    LIMIT = 25

    api = RefDataAPI()
    contracts = api.get_contracts_for_date(TARGET_DATE)

    # Deterministic ordering for proof output
    contracts = sorted(
        contracts,
        key=lambda c: (c.product_id, c.period_id, c.contract_id),
    )[:LIMIT]

    print(f"Contracts active on: {TARGET_DATE.isoformat()}")
    print()

    header = (
        f"{'product_id':<26}"
        f"{'contract_id':<34}"
        f"{'period_id':<14}"
        f"{'first_day_of_interest':<22}"
        f"{'last_trading_day':<20}"
    )
    print(header)
    print("-" * len(header))

    for c in contracts:
        print(
            f"{c.product_id:<26}"
            f"{c.contract_id:<34}"
            f"{c.period_id:<14}"
            f"{c.first_day_of_interest!s:<22}"
            f"{c.last_trading_day!s:<20}"
        )


if __name__ == "__main__":
    main()

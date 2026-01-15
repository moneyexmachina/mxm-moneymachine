from datetime import date

from mxm_refdata.api.ref_data_api import RefDataAPI


def _get(obj, attr):
    """Safe attribute access for proof printing."""
    return getattr(obj, attr, "-")


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
        key=lambda c: (
            _get(c, "product_id"),
            _get(c, "period_id"),
            _get(c, "contract_id"),
        ),
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
            f"{_get(c, 'product_id'):<26}"
            f"{_get(c, 'contract_id'):<34}"
            f"{_get(c, 'period_id'):<14}"
            f"{str(_get(c, 'first_day_of_interest')):<22}"
            f"{str(_get(c, 'last_trading_day')):<20}"
        )


if __name__ == "__main__":
    main()

from mxm.refdata.api.ref_data_api import RefDataAPI


def main() -> None:
    PRODUCT_ID = "comex_gold_futures"
    LIMIT = 25

    api = RefDataAPI()
    contracts = api.get_contracts_for_product(PRODUCT_ID)

    # Deterministic ordering for proofs
    contracts = sorted(
        contracts,
        key=lambda c: (
            str(c.first_day_of_interest),
            c.contract_id,
        ),
    )[:LIMIT]

    # Table header
    header = (
        f"{'contract_id':<28}"
        f"{'first_day_of_interest':<22}"
        f"{'last_trading_day':<20}"
        f"{'currency':<10}"
        f"{'unit':<14}"
        f"{'contract_size':<14}"
    )
    print(header)
    print("-" * len(header))

    for c in contracts:
        print(
            f"{c.contract_id:<28}"
            f"{c.first_day_of_interest!s:<22}"
            f"{c.last_trading_day!s:<20}"
            f"{c.currency:<10}"
            f"{c.unit:<14}"
            f"{c.contract_size!s:<14}"
        )


if __name__ == "__main__":
    main()

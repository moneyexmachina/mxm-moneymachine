from mxm_refdata.api.ref_data_api import RefDataAPI


def _get(obj, attr):
    """Safe attribute access for proof printing."""
    return getattr(obj, attr, "-")


def main() -> None:
    PRODUCT_ID = "comex_gold_futures"
    LIMIT = 25

    api = RefDataAPI()
    contracts = api.get_contracts_for_product(PRODUCT_ID)

    # Deterministic ordering for proofs
    contracts = sorted(
        contracts,
        key=lambda c: (
            _get(c, "first_day_of_interest"),
            _get(c, "contract_id"),
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
            f"{_get(c, 'contract_id'):<28}"
            f"{str(_get(c, 'first_day_of_interest')):<22}"
            f"{str(_get(c, 'last_trading_day')):<20}"
            f"{_get(c, 'currency'):<10}"
            f"{_get(c, 'unit'):<14}"
            f"{str(_get(c, 'contract_size')):<14}"
        )


if __name__ == "__main__":
    main()

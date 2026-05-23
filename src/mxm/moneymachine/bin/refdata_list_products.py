from mxm.refdata.api.ref_data_api import RefDataAPI


def main() -> None:
    api = RefDataAPI()
    products = api.get_all_products()
    for p in products:
        # Keep this stable and readable for proof capture
        print(p.product_id)


if __name__ == "__main__":
    main()

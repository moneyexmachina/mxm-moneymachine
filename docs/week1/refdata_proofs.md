# Week 1 — Reference Data Proofs

This document records concrete, runnable proofs that `mxm-refdata` provides
the reference data required for the MXM V1 MVP.

The goal is not completeness or polish, but to demonstrate that the system can
answer basic, operational questions about futures products, contracts, and
calendars in a deterministic and inspectable way.

## Proof Surface

The following capabilities must be demonstrated:

1. **List available futures products**  
   Show which futures products are currently defined in `mxm-refdata`.

2. **Enumerate contracts for a product**  
   For a selected futures product:
   - list all contracts from 2010 to 2035,
   - include contract identifiers,
   - include first “of-interest” date,
   - include last tradable date,
   - include key contract specifications (multiplier, currency, tick size).

3. **Resolve the active contract on a given date**  
   For a selected futures product and date:
   - identify the active contract according to exchange rules and calendars.

4. **Inspect the contract chain on a given date**  
   For a selected futures product and date:
   - list the active contract and the next N contracts considered “of interest”.

Each proof below records:
- the exact command executed,
- the date and environment (where relevant),
- the raw command-line output.

## Notes
WE need to first make sure mxm-refdata is boringly usable.
Moved the
├── data
│   ├── first_day_of_interest_rule.json
│   ├── futures_products.csv
│   └── last_trading_rule.json

inside the package... and adapted the way they are loaded.

We also made sure that the sqlite db is written into a user overridable location.


## Proofs

### Proof 1 — List available futures products

Command:

```bash
poetry run python ./src/mxm/v1/bin/refdata_list_products.py
```

Output:

```text
INFO:root:Initializing database schema...
INFO:root:Tables created: dict_keys(['futures_contracts', 'futures_products', 'periods'])
INFO:root:Starting full instrument setup...
INFO:root:Full instrument setup completed successfully.
comex_gold_futures
cbot_corn_futures
cme_gbp_futures
cme_emini_snp500_futures
nymex_natural_gas_futures
```

### Proof 2 — List contracts for a futures product (sample)

This proof demonstrates that the system can enumerate a product’s contract chain and expose core lifecycle fields for each contract.

Command:

```bash
poetry run python src/mxm/v1/bin/refdata_list_contracts_for_product.py
```

Output (first 25 contracts for `comex_gold_futures`):

```text
contract_id                 first_day_of_interest last_trading_day    currency  unit          contract_size
------------------------------------------------------------------------------------------------------------
comex_gold_futures.Jan-2000 1994-02-01            2000-01-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jun-2000 1994-07-01            2000-06-28          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Dec-2000 1995-01-03            2000-12-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jan-2001 1995-02-01            2001-01-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jun-2001 1995-07-03            2001-06-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Dec-2001 1996-01-02            2001-12-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jan-2002 1996-02-01            2002-01-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jun-2002 1996-07-01            2002-06-26          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Dec-2002 1997-01-02            2002-12-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jan-2003 1997-02-03            2003-01-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jun-2003 1997-07-01            2003-06-26          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Dec-2003 1998-01-02            2003-12-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jan-2004 1998-02-02            2004-01-28          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Feb-2000 1998-03-02            2000-02-25          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Mar-2000 1998-04-01            2000-03-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Apr-2000 1998-05-01            2000-04-26          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.May-2000 1998-06-01            2000-05-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jun-2004 1998-07-01            2004-06-28          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jul-2000 1998-08-03            2000-07-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Aug-2000 1998-09-01            2000-08-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Sep-2000 1998-10-01            2000-09-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Oct-2000 1998-11-02            2000-10-27          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Nov-2000 1998-12-01            2000-11-28          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Dec-2004 1999-01-04            2004-12-29          Currency.USDProductUnit.TROY_OUNCE100.0
comex_gold_futures.Jan-2005 1999-02-01            2005-01-27          Currency.USDProductUnit.TROY_OUNCE100.0
```

Notes:
- The lifecycle columns (`first_day_of_interest`, `last_trading_day`) are present and vary by contract month and year.
- The `currency` and `unit` fields are currently printed using their enum string representations; formatting will be improved to render bare values (for example `USD`, `TROY_OUNCE`) in a later proof.


### Proof 3 — Active contract on a given date (currently wrong behaviour)

This proof inspects the contracts returned by the reference data system for a given target date.

Command:

```bash
poetry run python src/mxm/v1/bin/refdata_contracts_for_date.py
```

Output:

```text
Contracts active on: 2021-06-15

product_id                contract_id                       period_id     first_day_of_interest last_trading_day
--------------------------------------------------------------------------------------------------------------------
cme_emini_snp500_futures  cme_emini_snp500_futures.Jun-2021 Jun-2021      2016-04-01            2021-06-18
cme_gbp_futures           cme_gbp_futures.Jun-2021          Jun-2021      2016-07-01            2021-06-14
comex_gold_futures        comex_gold_futures.Jun-2021       Jun-2021      2015-07-01            2021-06-28
nymex_natural_gas_futures nymex_natural_gas_futures.Jun-2021Jun-2021      2009-11-27            2021-05-27
```

Notes:
- For each product, exactly one contract is returned for the given date.
- The returned contracts correspond to the delivery month containing the target date.

Analytical note (not part of the proof)

This behaviour indicates that RefDataAPI.get_contracts_for_date(date) currently resolves the delivering contract per product, rather than returning all contracts that are “active” (open for trading / of interest) on that date.

In other words, the method behaves more like:

“Which contract is in its delivery period on this date?”

rather than:

“Which contracts are live or tradable on this date?”

This is a valid and useful query, but it does not satisfy the original Proof 3 intent (“inspect the contract chain on a given date”), which would typically include:

multiple forward contracts per product,

spanning many future delivery months.

Accordingly:

this proof is correctly recorded as observed behaviour,

but the proof definition must be revised, and

the implementation in mxm-refdata must be reviewed to determine whether:

a second API method is needed, or

this method should be renamed / redefined.

That investigation belongs to the next step inside mxm-refdata.

### Proof 4 — Contract chain on a given date
(To be filled)

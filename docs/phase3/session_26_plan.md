# Session 26 – Refine Synthetic Asset Construction Policy for Mixed Listing Structures

Status: 🔜 Planned  
Date: 2026-03-XX  
Scope: Adjust synthetic-asset construction policy so that generated chains are structurally valid under the new WeightsSeries roll pacing model.

# 1. Objective

Session 26 will refine the **Synthetic Asset construction policy** so that we only generate assets on **contiguous contract chains**.

This follows directly from the result of Session 25.

Session 25 established that:

- roll pacing is driven by the **front contract of the same selector family**
- operationally, this is implemented by taking the role selector and forcing `N=1`
- this works correctly for any chain whose rank progression is structurally coherent

The remaining issue is therefore **not** in the weights engine.

It is in the **policy layer**.

Some products have listing structures that are:

- fully monthly
- fully quarterly
- fully seasonal
- or mixed between front serials and longer-dated quarterly / semi-annual families

If we generate generic `L1..Ln` listed-chain assets across a mixed structure, then the chain is no longer semantically homogeneous.

Session 26 therefore has one core goal:

> Only generate CONT / TS / PS assets on chains that are internally contiguous and semantically stable.

# 2. Why This Session Is Needed

## 2.1 What Session 25 proved

The smoke tooling showed:

- the role-level weights could be misleading because of relabelling
- the contract-aggregated weight view showed that rolling is now economically correct
- roll timing should be anchored by the `N=1` selector of the same selector family

This means the roll engine is now correct **provided the selector family itself forms a coherent chain**.

## 2.2 What remains unresolved

The current policy compiler still assumes:

- every product gets generic listed-chain assets
- CONT: `L1..L12`
- TS: `TS(L1/L2) .. TS(L11/L12)`
- PS: cross-product spreads built from the same listed-chain logic

That assumption is valid only for products whose listing surface is a **single contiguous family**.

It is invalid or conceptually muddy for products with **mixed listing frequencies**.

# 3. Core Design Principle for Session 26

The key design rule to lock is:

> A synthetic rolling chain must correspond to a real contiguous selector family.

This means we should not ask:

- “how many `L` levels can we build?”

We should instead ask:

- “what selector families exist for this product?”
- “which of those families are contiguous?”
- “which assets should we generate on each family?”

# 4. Product-by-Product Interpretation of Current Listing Rules

The current `futures_products.csv` implies the following:

## 4.1 `nymex_natural_gas_futures`

Listing rule:

> Monthly contracts listed for the current year and the next 12 calendar years.

Interpretation:

- full monthly chain
- contiguous throughout
- generic listed-chain policy is valid

Can generate:

- CONT on monthly chain
- TS on monthly chain
- PS against other products on monthly chain

Examples:

- `L1..L12`
- `TS(L1/L2) .. TS(L11/L12)`

## 4.2 `cme_emini_snp500_futures`

Listing rule:

> Quarterly contracts (Mar, Jun, Sep, Dec) listed for 21 consecutive quarters.

Interpretation:

- pure quarterly chain
- contiguous within quarterly family
- generic monthly `L1..Ln` is **not** conceptually wrong if built from the listed chain, but the more explicit and meaningful family is **quarterly**

Preferred generated family:

- quarterly chain only

Can generate:

- quarterly CONT
- quarterly TS
- quarterly PS if paired with another quarterly-compatible product

Examples:

- `Mar1`, `Jun1`, `Sep1`, `Dec1` family
- or, better, an explicit quarterly-rank family (`Q1..Qn`) if introduced

## 4.3 `cme_gbp_futures`

Listing rule:

> Quarterly contracts listed for 20 consecutive quarters and serial contracts listed for 3 months.

Interpretation:

- mixed front serial monthly + long-dated quarterly
- generic `L1..Ln` across the whole listing surface is not a stable homogeneous family
- this is exactly the type of product that motivated Session 26

Preferred generated families:

- quarterly family only for rolling assets
- optionally later, a short serial front family if explicitly modelled
- but not generic `L1..L12`

Can generate in v1:

- quarterly CONT
- quarterly TS
- quarterly PS if desired

Should not generate in v1:

- generic long listed-chain rolling family spanning serial + quarterly mixture

## 4.4 `comex_gold_futures`

Listing rule:

> 24 consecutive months and any Jun and Dec in the nearest 72 months.

Interpretation:

- one monthly front chain
- plus a long-dated semi-annual Jun/Dec chain
- generic `L1..Ln` is valid only through the fully monthly front region
- beyond that, the listed set ceases to be a homogeneous monthly ladder

Preferred generated families:

- front monthly family (bounded depth)
- Jun/Dec family

Can generate:

- monthly CONT / TS on front monthly region only
- Jun/Dec CONT (and possibly TS later if desired)

Need to decide exact front-month depth policy:

- likely use a bounded monthly depth, e.g. monthly `L1..L23`
- not arbitrary `L1..L72`

## 4.5 `cbot_corn_futures`

Listing rule:

> Mar, May, Sep and 8 monthly contracts of Jul and Dec listed annually after the termination of trading in the December contract of the current year.

Interpretation:

- not a simple monthly chain
- structurally this is a **seasonal grain family**
- the meaningful chain is the grain delivery cycle, not generic calendar months

Preferred generated family:

- seasonal agricultural chain

Can generate:

- CONT along the grain sequence
- TS along adjacent seasonal steps

This likely requires explicit selector-family authoring rather than reusing generic listed-chain logic.

# 5. Main Policy Decisions to Make

Session 26 should decide and implement the following.

## 5.1 Replace “generic listed chain for all products” with “per-product chain families”

Current policy surface:

- one generic listed family (`L1..Ln`)
- optional fixed-month families

New policy surface:

- per-product supported chain families
- each family explicitly declares what can be built

Examples:

- Natural Gas → monthly family
- ES → quarterly family
- GBP → quarterly family
- Gold → bounded monthly family + Jun/Dec family
- Corn → seasonal family

## 5.2 Introduce chain-family semantics into policy

The compiler currently knows how to build:

- `_listed_rule(n=n)`
- `_fixed_month_rule(month=m, n=n)`

Session 26 should decide whether policy is expressed in terms of:

### Option A — existing selector primitives only
Use current selector machinery, but choose the right filters/depths per product.

### Option B — explicit chain-family policy objects
Introduce a more expressive policy layer like:

- monthly chain
- quarterly chain
- semiannual chain
- seasonal chain

For Session 26, Option A may be enough if kept narrow and deterministic.

## 5.3 Bound monthly depth where the monthly region is finite

For Gold:

- monthly front region exists only for 24 consecutive months
- beyond that only Jun/Dec survives

So policy must not generate monthly `L1..L72`.

It should generate only the bounded front monthly region.

Likely decision:

- explicit per-product maximum depth for listed monthly front chain

## 5.4 Stop generating invalid PS families across incompatible chains

Cross-product spreads currently use:

- `a_cur = L_n`
- `a_nxt = L_(n+1)`
- `b_cur = L_n`
- `b_nxt = L_(n+1)`

This only makes sense when both products expose compatible contiguous chain families.

Session 26 should decide:

- whether PS remains limited to products whose v1 chain family is compatible
- whether cross-family PS is out of scope for now

A reasonable v1 choice is:

> Only build PS where both products use the same family archetype currently supported by policy.

# 6. Concrete Refactor Plan

## 6.1 Refine `construction_policy.py`

Current `PolicyDefaults` only contains global depth knobs.

Session 26 should revise policy authoring so that per-product behaviour includes chain-family structure.

Potential additions:

- explicit `listed_chain_mode`
- per-product chain depth overrides
- explicit enable/disable flags for monthly / quarterly / seasonal / semiannual families

At minimum:

- stop treating every product as generic `L1..L12`

## 6.2 Refine `policy_compile.py`

This is the main implementation site.

Current compiler behaviour:

- builds generic listed-chain CONT and TS for every product
- builds fixed-month CONT sets from valid period rules
- builds PS globally on listed-chain rules

Session 26 changes:

- dispatch per product according to the valid family structure
- build only those CONT / TS families that are structurally valid
- constrain PS generation accordingly

## 6.3 Add explicit product-family interpretation helpers

The compiler needs a clean internal representation of “what chain families exist for this product”.

This likely wants one or more helpers such as:

- `_supported_chain_families_for_product(...)`
- `_monthly_front_depth_for_product(...)`
- `_quarterly_months_for_product(...)`
- `_semiannual_months_for_product(...)`
- `_seasonal_cycle_for_product(...)`

These do not need to be over-generalised yet; they only need to cover the current five products cleanly.

# 7. Suggested Initial Product Policy for Current Universe

A reasonable v1 policy target is:

## Natural Gas
- monthly listed family
- CONT: monthly `L1..L12`
- TS: monthly adjacent ladder
- PS: allowed with other monthly-compatible products

## ES
- quarterly family only
- CONT: quarterly front chain
- TS: quarterly adjacent ladder
- PS: only against compatible quarterly family if used

## GBP
- quarterly family only
- no generic listed chain spanning front serials and quarterlies

## Gold
- front monthly family with bounded depth
- Jun/Dec family
- no generic listed chain beyond monthly front region

## Corn
- seasonal grain family only
- no generic monthly listed chain

# 8. Testing / Verification Plan

Session 26 should use the new smoke machinery from Session 25.

For each supported family type, rebuild the registry and inspect at least one representative example.

Recommended checks:

- registry asset ids reflect new policy surface
- generated assets correspond to intended chain families
- smoke weights for representative CONT / TS assets show proper contract-space rolling
- no obviously mixed-family artefacts are being generated

Important:

- do not yet over-snapshot the output
- use smoke inspection first
- add policy-compile unit tests once the intended family rules are locked

# 9. Deliverables

Session 26 is complete when:

- [ ] Product chain-family interpretation is clearly defined for the current five products
- [ ] `construction_policy.py` reflects those chain-family choices
- [ ] `policy_compile.py` generates only structurally valid rolling families
- [ ] Gold, GBP, and Corn no longer generate misleading generic `L1..Ln` chains where inappropriate
- [ ] PS generation is constrained to valid family combinations
- [ ] Registry rebuild succeeds
- [ ] Smoke inspection confirms correct rolling on representative assets

# 10. Non-Goals

Session 26 is not about:

- changing the WeightsSeries engine
- changing LinearRoll
- changing ContractSeries selector semantics
- introducing holdings / unit transforms / execution

Those are already in a good state.

This session is only about:

> refining the **policy layer** so that we construct the right synthetic assets.

# 11. Summary

Session 25 solved roll realisation and exposed, via smoke inspection, that the remaining issue was **policy over mixed listing structures**, not weights logic.

Session 26 will therefore make the synthetic asset universe structurally correct by ensuring that generated chains correspond to real contiguous selector families for each product.

This is the necessary final cleanup before moving on to the next realised layer.

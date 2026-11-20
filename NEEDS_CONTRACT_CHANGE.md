# Contract changes made for implementation

Two shared fields were added to `app/models.py` to implement the supplied v2 requirements:

- `Decision.aiz_decision` records one of AI-Z's four official words on each ledger row.
- `Element.brane_policy_ref` and `Decision.brane_policy_ref` keep each local rule linked to its BRANE enforcement rule.

The matching `brane_policy_ref` field was made required in `contracts/policy.schema.json`. The team should carry these contract additions into the frozen shared schema before merging parallel work.

The legal matrix implementation also changes the affordability contract intentionally: only `net_pay_cents`, `housing_cents`, `utilities_cents` and `debt_payment_cents` remain as figures in `OfficerView`. `other_spending_cents` and `monthly_margin_cents` are removed. `OfficerView` now carries a local P14 note/human-review flag and the neutral P10 status string. Rebuild `contracts/openapi.yaml` after any further model edits.

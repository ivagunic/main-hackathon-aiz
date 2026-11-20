# BRANE adapter

Configure `BRANE_BASE_URL`, `BRANE_MODEL`, and optionally `BRANE_API_KEY`; set `BRANE_MODE=live` to enable the assumed `/v1/chat/completions` adapter. Development defaults to `FakeBrane`. BRANE's actual endpoint, policy configuration procedure, local route and decision-log fields have not been confirmed, so live mode requires validation with AI-Z before use.

Set `BRANE_LOCAL_PATH` and `BRANE_LOCAL_MODEL` only after AI-Z supplies the approved local route. The adapter currently assumes `/v1/local/chat/completions`. `brane_ok()` checks the assumed `/health` path.

The current pipeline submits exactly four integer fields: `net_pay_cents`, `housing_cents`, `utilities_cents`, and `debt_payment_cents`. It does not submit case identifiers, source pages, open questions, messages, transaction descriptions, or applicant identifiers. Connection failures or missing positive BRANE verdicts fail closed.

`PRESCRUB=on` is the only supported mode and runs local schema and outbound checks before the request. Raw-source dispatch is disabled. The opt-in live BRANE enforcement test sends a harmless synthetic P1 schema violation and records a denial only when BRANE rejects it; it is not run in the default test suite.

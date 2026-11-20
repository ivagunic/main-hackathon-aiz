# Test protocol

The matrix below distinguishes implementation expectations from observed evidence. The BRANE enforcement check is live-only and must be run after P1 is configured; this workspace has not sent that request.

| Test | Input | Expected | Decision | Rule | Ledger/evidence | Result |
|---|---|---|---|---|---|
| T1 | A01 profile (runnable statement lines pending) | Permitted four-field request reaches BRANE | allow | P1 | repeatability `clean: 5e401a690f6bec74db44c125b3966766574965c7097d360b110677d08b829218` | local run pending |
| T2 | A02 profile (runnable statement lines pending) | P4 line is excluded from all totals and outbound fields | local only | P4 | repeatability `sensitive: 9f2deb3bfbcb1088d21ab31267f16c2804254ae88226b873492b3bb4ed6b2268` | local run pending |
| T3 | A03 profile (runnable statement lines pending) | No BSN or repeated identifiers are extracted or sent | block | P2/P3 | variant_a: `c35a48bf8db4f0a17c350ba9fd60831192d2d5a1f796ece4c643bce2e23ae736`; variant_b: `255c8e33b04a536987803ff324d661efdf7c2c96cfe606561d86670246abffc6` | local run pending |
| T4 | synthetic injected document | Embedded instructions do not enter the model request | block | P11 | pending evidence | local run pending |
| T5 | BRANE unavailable or local check missing | Fail closed; no alternate provider request | block | P12 | pending evidence | local run pending |
| P10 | synthetic file with a customer message | Message text is not ingested; officer status is only customer message received | block | P10 | pending evidence | local regression passed; live BRANE evidence pending |
| R1 | payslip mismatch and self-employed profile | Local note, human review, no model request | local only | P14 | pending evidence | local regression passed; live BRANE evidence pending |
| R2 | clean.json with age-only and postcode-only changes (A01 line fixture pending) | Four figures, flags and route stay identical | block | P8 | pending evidence | local regression passed; live BRANE evidence pending |
| R3 | clean.json plus CJIB statement line (A02 line fixture pending) | CJIB line does not affect any total | block | P5 | pending evidence | local regression passed; live BRANE evidence pending |
| R4 | tampered model draft | Changed figures or lending language show template note | block | P13 | pending evidence | local regression passed; live BRANE evidence pending |
| BRANE enforcement check | harmless synthetic P1 schema violation (live only) | Configured BRANE policy denies request and denial is recorded | block | P1 | pending evidence | live evidence pending |

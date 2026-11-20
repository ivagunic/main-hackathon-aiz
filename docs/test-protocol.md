# Test protocol

The matrix below distinguishes implementation expectations from observed evidence. The BRANE enforcement check is live-only and must be run after P1 is configured; this workspace has not sent that request.

| Test | Input | Expected | Decision | Rule | Ledger/evidence | Result |
|---|---|---|---|---|---|
| T1 | A01 profile (runnable statement lines pending) | Permitted four-field request reaches BRANE | allow | P1 | repeatability `clean: 924369458250bbca2f913d0c587a7fb00c325745d0153cc70caef008941adc12` | local legacy-fixture pass; A01–A03 profile fixtures and live BRANE evidence pending |
| T2 | A02 profile (runnable statement lines pending) | P4 line is excluded from all totals and outbound fields | local only | P4 | repeatability `sensitive: 16e070d4cd5982647928d84eef033a16e7c98ce1d14dbe10eafd650321f6aaeb` | local legacy-fixture pass; A01–A03 profile fixtures and live BRANE evidence pending |
| T3 | A03 profile (runnable statement lines pending) | No BSN or repeated identifiers are extracted or sent | block | P2/P3 | variant_a: `3a2a42a3e239175060ab9dc5bbad59be0cfe3c74643e36dbfe7f7f8ec1a3451e`; variant_b: `956d2845862a6964d2da4a66c76ff6bd8f7c7e747c27134f014cc0991158d4e6` | local legacy-fixture pass; A01–A03 profile fixtures and live BRANE evidence pending |
| T4 | synthetic injected document | Embedded instructions do not enter the model request | block | P11 | pending evidence | local regression passed; live BRANE evidence pending |
| T5 | BRANE unavailable or local check missing | Fail closed; no alternate provider request | block | P12 | pending evidence | local regression passed; live BRANE evidence pending |
| P10 | synthetic file with a customer message | Message text is not ingested; officer status is only customer message received | block | P10 | pending evidence | local regression passed; live BRANE evidence pending |
| R1 | payslip mismatch and self-employed profile | Local note, human review, no model request | local only | P14 | pending evidence | local regression passed; live BRANE evidence pending |
| R2 | clean.json with age-only and postcode-only changes (A01 line fixture pending) | Four figures, flags and route stay identical | block | P8 | pending evidence | local regression passed; live BRANE evidence pending |
| R3 | clean.json plus CJIB statement line (A02 line fixture pending) | CJIB line does not affect any total | block | P5 | pending evidence | local regression passed; live BRANE evidence pending |
| R4 | tampered model draft | Changed figures or lending language show template note | block | P13 | pending evidence | local regression passed; live BRANE evidence pending |
| BRANE smoke | harmless four-field live request and closed localhost port | Positive verdict, request metadata printed, then BraneUnavailable at closed port | allow/block | P1/P12 | pending evidence | live evidence pending |
| BRANE enforcement check | harmless synthetic P1 schema violation (live only) | Configured BRANE policy denies request and denial is recorded | block | P1 | pending evidence | live evidence pending |

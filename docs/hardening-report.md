# Hardening report

Independent test pass over the loan file assistant, 20 Nov 2026. Synthetic data only, `BRANE_MODE=fake`, and any non-localhost socket connection fails the test.

## What was added

`tests/hardening/` holds 13 files and 770 test cases, covering the brief's sections A to M.

- Every test checks three surfaces: what FakeBrane received, the OfficerView JSON, and the SSE stream from `/cases/{id}/events`.
- The leak tests also check the ledger export (JSONL and CSV) and all captured log output.
- 50 invented loan files plant a unique name, IBAN, BSN, employer, address and three sensitive merchants each. The values appear in upper and lower case, as a spaced IBAN, a dotted BSN, initials, inside descriptions and on every page.

Baseline before any change: ruff clean, 39 passed, 1 skipped. First run of the new tests: **402 failed**, 364 passed.

## Bugs found and fixed

| # | What broke | Severity | Fix |
|---|---|---|---|
| 1 | BSN shown in visible transactions whenever the line had no IBAN (50 of 50 files) | Leak | BSN- and IBAN-shaped values are masked in visible lines |
| 2 | Employer shown as the salary counterparty, because intake dropped it before it could be pseudonymised | Leak | Intake keeps the employer name so it can be replaced |
| 3 | Initials such as "K. L. Surname" were not replaced | Leak | The name pattern accepts dotted or spaced initials |
| 4 | Mosque, synagogue, parish, FNV/CNV, dentist, Kirche, Krankenhaus, hôpital, Partei and similar merchants were not recognised | Leak | Added to the merchant dictionary |
| 5 | Misspellings, zero-width characters, punctuation inside words and spaced letters slipped past the classifier | Leak | Text is normalised first; misspelled stems are matched word by word |
| 6 | Street names (Kerkstraat, Apotheekweg) were flagged as church or pharmacy | Wrong figure | Street names are ignored when matching |
| 7 | A sensitive or CJIB line in a new month halved housing, utilities and debt | Wrong figure | Excluded lines no longer count towards the number of months |
| 8 | Applicant names containing keywords ("Tom Church", "Sanne Kerkhof", "Sloane") changed the figures (P8) | Wrong figure | The applicant's own name and address are hidden before keyword matching |
| 9 | A valid policy with no cloud-allow rule still let the cloud call through | Fail-open | The cloud call needs a policy decision allowing it first |
| 10 | Negative or huge payload values were accepted; an invalid payload crashed the pipeline instead of failing closed | Fail-open | Values must be between 0 and 10^9; the check runs inside the fail-closed block |
| 11 | "a p p r o v e", "appro​ve", full-width text, "sc0re", "goedgekeurd", "afgewezen", "aanbevolen" and "adviseren" got past the draft check | Fail-open | The draft is normalised and checked again with spacing removed |
| 12 | NL, DE, base64, spaced and "system :" style instructions were not flagged; address and employer were never checked | Missed flag | Wider patterns, base64 decoding, and checks on address, employer and purpose |
| 13 | Case id with backslashes or a drive letter read any `.json` file on disk (Windows) | Leak | Case ids are limited to letters, digits, `_` and `-` in the API and pipeline |
| 14 | Unknown case returned 400 with the server path; a `null` or `[]` upload returned 500; no upload size limit | Cosmetic / crash | 404 with a generic message, clean 400, 413 above 2 MB |
| 15 | Q&A did not refuse many protected-data or Dutch decision questions (answers never contained data) | Audit gap | Wider refusal patterns; each refusal is ledgered |
| 16 | A review "reason" made of zero-width characters or dots was accepted | Gate bypass | A reason needs 20 visible characters, at least 10 of them letters |

Final run: **800 passed, 6 expected failures (open items), 1 skipped, 2 failed** (see below).

## Still open

These need a decision or a shared-interface change:

- **OPEN-1:** names of private people in transfers (P2) are shown in the officer view. Recognising names needs a design choice.
- **OPEN-2:** instructions inside payslip or page text are thrown away at intake before they are checked. They cannot reach the model, but they are not recorded in the ledger. Fixing this needs a `LoanFile` field (`app/models.py`).
- **OPEN-3:** words like "loan" or "lening" inside injected text can move a payment between housing and debt. The total never changes.
- **Review reason not stored:** the officer's reason is checked but only the action goes into the event, not the ledger. There is also no officer login. Fixing this needs a schema change.
- **Recurring-merchant rule:** a sensitive line sharing a counterparty with the landlord would hide the rent line too.
- **Draft check:** it does not catch swapped figures (housing quoted as debt) or numbers written out in words.

## Changed by another tool during this pass (not modified here)

`app/gateway/__init__.py` was rewritten while these tests ran. Three problems came with it:

- `tests/security/test_gateway.py::test_live_gateway_fails_closed_on_closed_braneserver_without_fallback` fails. The client now needs an API key and uses a different path.
- `test_live_client_harness_positive_control` fails. The new verdict record has no `verdict` key, so the pipeline refuses every successful live answer. This fails closed, but means live drafting can never work.
- The new verdict record copies the full raw BRANE response into the ledger and the SSE `brane_call` event. This probably breaks matrix section D. The test for it passes only because of the previous problem.

Two ruff errors in that file remain.

## Not testable without live BRANE

- BRANE's own enforcement of P1 (four-field schema) and P2/P3 (personal-data and BSN detection).
- Real verdict headers and response format.
- Timeout behaviour with real latency.
- What BRANE logs or keeps on its side.

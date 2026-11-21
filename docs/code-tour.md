# Code tour: one loan file through the assistant

*For a jury walkthrough · policy v1 · 21 November 2026*

## Page 1 — from file to officer view

### Follow one case

Start at `app/api/main.py`: `create_case()` accepts a synthetic fixture or a bounded JSON upload, and `run_case()` sends it to `app.pipeline.process()`. The API validates case IDs and deletes uploaded temporary files after processing. `app/intake.parse_file_data()` validates the input model, drops raw page text, clears BSN, keeps only the payslip fields needed for printed net pay, and drops message bodies unless the opt-in hardship switch is enabled; even then the officer view exposes only “customer message received.”

`app.classify.classify()` reads `data/dictionaries/sensitive_merchants.yaml` and tags statement lines locally. `app.calc.compute()` derives four integer-cent values: printed net pay, housing, utilities and debt payments. It excludes P4 sensitive and P5 criminal lines from every total and from the month count. It also compares printed net pay with salary credits; a mismatch becomes an open question instead of a model input.

`app.pipeline.process()` builds and stores a local pseudonym map, applies `policy/policy.v1.yaml`, and records the decisions in the SQLite ledger. P14 evidence gaps and self-employed income return a local reconciliation note and a human-review flag before any model request. For an ordinary case, the pipeline validates an exact four-key, integer-only payload, verifies that the aggregate is permitted by policy, checks for source-derived leaks, and only then calls `app.gateway.BraneClient`.

`app.gateway.build_brane_request()` is the single place that assembles the BRANE URL, headers and OpenAI-format body. BRANE returns a model draft and decision metadata. The shared verdict rule in `app.pipeline._brane_decision()` accepts only HTTP 200 with an allowed route and action. The pipeline checks the draft against P13, substitutes the four locally calculated amounts into the approved tokens, then creates `OfficerView`. `app.api.get_view()` marks it opened; the page renders that view. An authorised officer’s later action is recorded separately by `app.api.review()`.

An officer question takes a separate, smaller path: `app.api.ask()` calls `app.qa.ask()`. Its deterministic direct and accumulation guards run first. If they pass, the question is pseudonymised and sent via the same gateway with a system message containing only the four values and the caveat; no statement, hidden line or document text is available to that call. The answer must pass the shared BRANE verdict rule and P13 amount/wording check before it is shown. The API adds one ledger row per question without storing the question text.

### Three checks before a cloud answer is trusted

1. **Payload schema:** `pipeline.validate_cloud_payload()` and the gateway’s `_require_four_integer_fields()` require exactly `net_pay_cents`, `housing_cents`, `utilities_cents`, and `debt_payment_cents`, each an integer. Extra keys, booleans, strings and other types are rejected before the gateway sends the request.
2. **Outbound guard:** `gateway.outbound_guard()` calls `pseudo.assert_clean()` and checks source counterparties. The question path prescreens known identifiers, requires `PRESCRUB=on`, and sends only the scrubbed question plus the restricted system message. These controls stop known identifiers and source lines from becoming model context.
3. **Verdict rule:** `_brane_decision()` requires a complete positive BRANE decision before a draft or answer is displayed. A refusal is a refusal; an absent or malformed verdict is not treated as permission.

These checks cover different failure points: data shape, source leakage and the decision to use returned text. They complement, rather than replace, the local calculation and output checks.

## Page 2 — rules, failures and jury questions

### Where rules P1–P15 are enforced

| Rule | Enforcement in this code |
|---|---|
| P1 | `pipeline.validate_cloud_payload()` plus gateway schema validation enforce the four integer fields; `policy.v1.yaml` governs aggregate routing. |
| P2 | `pseudo.build_map()`, `scrub()` and `assert_clean()` protect names, address, employer and IBAN; gateway guard blocks a leak. |
| P3 | Intake clears BSN; `mask_identifiers()` catches BSN-shaped values; classification and policy mark national IDs excluded. |
| P4 | Sensitive merchant dictionary and `classify_text()` mark local-only; `calc.compute()` excludes them from all totals; question guards refuse inference. |
| P5 | The criminal dictionary group and classifier mark CJIB/reclassering; calculation excludes these transactions from all totals. |
| P6 | Intake keeps the printed `net_cents` field only; `parse_payslip_text()` extracts net pay and no other payslip line. |
| P7 | `calc.compute()` uses only the selected fixed obligation categories; statement detail stays local and is not sent as document text. |
| P8 | Applicant identity is scrubbed before classification; proxy fields are not calculation inputs; paired proxy invariance tests check figures, flags and route. |
| P9 | No social-network connector or model field exists; unknown policy cases default to refusal. |
| P10 | Intake drops message bodies by default; `HARDSHIP_ENABLED` defaults false; the view exposes only the receipt status. |
| P11 | `classify._attack()` detects embedded instructions; raw page text is removed at intake; the model receives a fixed prompt or an officer’s guarded question. |
| P12 | `BraneClient` maps refusal and unavailable failures distinctly; `pipeline.process()` and `qa.ask()` fail closed without another provider. |
| P13 | `pipeline._render_token_draft()` rejects digits, unknown/missing tokens and decision wording, then inserts local values; QA checks amounts and prohibited wording. |
| P14 | `pipeline.process()` returns a local note and human-review flag before dispatch for mismatch or self-employed income. |
| P15 | No automated lending decision route exists; QA guards refuse decision requests and `api.review()` records the human officer’s action separately. |

The local agent enforces the controls above; BRANE contributes gateway policy decisions and provider-side protection. `policy.v1.yaml` names the BRANE categories for rules with equivalents and uses `agent-only` where this application owns the control. The table describes code paths and tests, not a claim that every live BRANE category has been independently audited.

### How failure stays safe

Connection errors, timeouts and server errors become `BraneUnavailable`; explicit refused responses become `BraneBlocked`. There are no retries to a model provider or a second host. The pipeline returns an unavailable/template view, and officer questions show “The safety check is offline, so the question was not sent.” Missing headers, unknown routes, malformed responses, an unclean draft, a changed figure or unsafe wording also cannot turn into a displayed model answer. Local calculations remain deterministic, and P14 cases do not call the model at all.

### Ten questions a technical judge may ask

1. **What actually leaves the bank?** The drafting request contains exactly four integer-cent fields and a fixed prompt with figure tokens. Officer questions contain only the scrubbed question and a system message with those four figures plus the caveat.
2. **Why use integer cents?** Integer cents avoid floating-point rounding in calculations and schema validation. Euro formatting happens locally after the draft passes its token checks.
3. **Can the model decide whether to lend?** No, there is no model decision endpoint and the question guard refuses approval, scoring, risk and recommendation requests. The authorised officer records a separate decision through the review endpoint.
4. **What if BRANE is down?** Connection failures, timeouts and 5xx responses become unavailable, and the application shows a safe local response. It does not retry another host or send directly to a provider.
5. **How are sensitive transactions handled?** Local dictionaries classify them before calculation. P4 and P5 transactions are omitted from all four figures and are not supplied as model context.
6. **How do you prevent prompt injection?** Document instructions are classified as data and source pages are stripped at intake. The model receives a constrained prompt, never the uploaded document text.
7. **What prevents a fabricated amount in a note?** The draft must contain each approved token exactly once, no digits, currency symbols, unknown tokens or decision language. The application replaces tokens with the locally computed figures.
8. **How are identifiers protected?** Known applicant details are pseudonymised before an outbound question, while the outbound guard checks source-derived identifiers and transaction counterparties. If prescrubbing or the map is unavailable, question processing stops.
9. **What happens with a payslip mismatch or self-employed income?** The application produces a local reconciliation note and flags human review before requesting a model draft. It makes no adverse inference from that gap.
10. **How can you show that proxies do not affect the result?** The R2 paired test changes only a proxy value and compares the figures, flags and route. The calculation also avoids using applicant identity when classifying transaction text.

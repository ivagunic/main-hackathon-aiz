# AI-Z Loan File Assistant

This repository contains a synthetic loan-file demo for deterministic affordability calculations, privacy routing, protected-data handling, and human review. It never makes a credit recommendation.

## Run locally

Use Python 3.12, install `requirements.txt`, then run `make verify`. Start the API with `uvicorn app.api.main:app --reload`. The default is `BRANE_MODE=fake`; choose a synthetic case such as `clean`, `sensitive`, `variant_a`, or `variant_b` through `POST /cases`, then process it with `POST /cases/{case_id}/process`.

The outbound request contains exactly four integer fields: `net_pay_cents`, `housing_cents`, `utilities_cents`, and `debt_payment_cents`. P4/P5 transactions are excluded from every total. Officer views carry the caveat: “This file documents selected fixed obligations only. It does not establish total expenditure or disposable income.”

Hardship messages are disabled by default (`HARDSHIP_ENABLED=false`). When a file contains a message, the officer view shows only “customer message received”; the message text is not ingested. The JSON uploader validates the file structure but does not prove that the contents are synthetic; do not use real applicant data with this demo.

## Evidence tools

- `make suite10` runs the four-fixture repeatability suite ten times and writes `evidence/repeatability.json`.
- `make redteam` runs the fixed attacks and legitimate-task list, writing `redteam/results/v1.json`.
- `make protocol` regenerates `docs/test-protocol.md` from the policy matrix and repeatability hashes.
- `make openapi` regenerates `contracts/openapi.yaml` from the FastAPI app.
- `make smoke` sends one synthetic four-field request to live BRANE, reports its verdict/status/latency, then verifies that a closed port raises `BraneUnavailable`.
- `make export-ledger CASE_ID=sensitive` exports the local ledger.

## BRANE setup status

The live adapter is configurable through `BRANE_BASE_URL`, `BRANE_API_KEY`, `BRANE_MODEL`, `BRANE_LOCAL_PATH`, and `BRANE_LOCAL_MODEL`. The routes and policy references are assumptions until AI-Z supplies and confirms the service details. See [the integration decisions log](docs/decisions-log.md) and [BRANE setup checklist](docs/brane-setup-checklist.md) before enabling live mode. Only a positive BRANE verdict is accepted; an unavailable or unreported verdict fails closed. Raw-source dispatch is disabled. Copy `.env.example` and fill values only from the BRANE operator; it contains no real credentials.

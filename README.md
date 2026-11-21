# Loan file assistant (AI-Z track, team UpSolve)

A loan file assistant for a bank's credit officer: it reads a loan file and works out net pay, housing, utilities and debt payments in plain code.
Only those four totals ever leave the bank, and every request to the AI goes through BRANE, which enforces our privacy rules.
The assistant never decides: a human officer reads the result and records the decision with a reason.

All data in this repository is invented. Do not use it with real people's data.

## Run it in 3 steps (practice mode, no key needed)

Practice mode uses a built-in stand-in for BRANE. While the app runs it makes no network calls. (The first start downloads Python 3.12 and the libraries once.)

**1. Install uv** (the Python package runner), once:

| System | Command |
|---|---|
| Windows (PowerShell) | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| macOS | `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Linux | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

Open a new terminal afterwards so `uv` is found.

**2. Start the app** from the repository folder:

```
uv run --python 3.12 --with-requirements requirements.txt python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

With make: `make demo`. Wait for `Application startup complete`.

**3. Open** http://127.0.0.1:8000 in your browser. Stop the app with Ctrl+C.

## Run it live with your own BRANE key

1. Copy the settings file:
   - Windows (PowerShell): `Copy-Item .env.example .env`
   - macOS or Linux: `cp .env.example .env`
2. Open `.env`, fill in `BRANE_API_KEY`, and change `BRANE_MODE=fake` to `BRANE_MODE=live`.
3. Start the app with the settings file:

```
uv run --env-file .env --python 3.12 --with-requirements requirements.txt python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

With make: `make demo` (it reads `.env` automatically when the file exists).

Our team policy lives in BRANE. A copy is in [`policy/brane_policy.json`](policy/brane_policy.json); the local rule file the code routes by is [`policy/policy.v1.yaml`](policy/policy.v1.yaml). `.env` is ignored by git; never commit a key.

## What to click

Pick one of the five practice files in Step 1 and press **Read this file**:

| File | What it shows |
|---|---|
| Clean file | Normal case: four amounts, a short note, one visible payment |
| File with sensitive payments | Church and pharmacy payments are left out and never shown |
| Variant A, Variant B | Other people, same rules |
| File with a hidden instruction | Text saying "ignore all previous instructions" has no effect |

Then work through the 12 checks in [docs/manual-test-script.md](docs/manual-test-script.md): they cover refused questions, the safety check being offline, recording a decision and downloading the record.

## Run the tests

```
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
```

With make: `make verify` (also runs the linter: `uv run --python 3.12 --with-requirements requirements.txt ruff check app tests scripts redteam`).

The tests always use the stand-in for BRANE, even when `.env` says live. In the hardening suite (`tests/hardening/`), any attempt to reach a non-local address fails the test. Result of the last run on 21 Nov 2026: **862 passed, 1 skipped, 6 expected failures** (listed under Known limits). The skipped test needs a live BRANE key.

## Where the evidence is

Everything is in [`evidence/pack/`](evidence/pack/):

- `test_evidence_run.csv`: the mandatory and edge-case tests run against live BRANE, with the X-Brane headers BRANE returned for each.
- `policy_matrix.csv`: rules P1 to P15 with the legal source, the target decision and how BRANE and our code enforce each one.
- `summary.md`: the headline counts from the evidence, repeatability and red-team runs.
- `rules-status.md`: the status of each rule and the test that proves it.
- `product-gaps.md`: where BRANE alone fell short and what our code does about it.

## How it works

1. **Read the file.** Only the fields we need are kept; the citizen service number and payslip text are dropped on arrival.
2. **Classify.** Every payment is sorted: ordinary, sensitive (health, religion, union, politics, dating), criminal (fines), identifier or hidden instruction.
3. **Calculate in code.** Net pay, housing, utilities and debt payments, never by a model. Sensitive and criminal payments are left out.
4. **Scrub.** Names, addresses, bank accounts and employers are replaced before anything can leave.
5. **Send four totals through BRANE.** Nothing else is in the request.
6. **Check the answer.** Only a positive BRANE decision is accepted; the note is replaced by a standard text if it changes a figure or suggests a decision.
7. **The officer decides.** The page shows the figures, where the request went, and asks for a decision with a reason.
8. **Record.** Every step is written to a ledger that can be downloaded.

```
app/
  api/        web endpoints and the demo page route
  intake/     reads loan files
  classify/   sorts payments and spots hidden instructions
  calc/       the four figures, in plain code
  pseudo/     replaces names, accounts and addresses
  policy/     routes each item by the rule file, keeps the ledger
  gateway/    the only code that talks to BRANE
  qa/         answers officer questions, refuses unsafe ones
  pipeline.py ties the steps together
frontend/     the one-page demo (plain HTML, no outside links)
data/         practice loan files and word lists
policy/       local rules and a copy of the BRANE policy
contracts/    shared data shapes and the API description
tests/        security tests and the hardening suite
evidence/     evidence pack and raw results
docs/         test script, policy matrix, decisions log, hardening report
scripts/      evidence and policy tools
redteam/      attack and legitimate-question lists
```

## Rules P1 to P15 at a glance

Status is copied from [`evidence/pack/rules-status.md`](evidence/pack/rules-status.md). "Agent" means our code.

| Rule | What it protects | Enforced by | Status |
|---|---|---|---|
| P1 | Only four integer totals leave the bank | Both | Implemented |
| P2 | Name, address, employer and bank account are left out | Both | Implemented |
| P3 | Citizen service number (BSN) is never read or sent | Both | Implemented |
| P4 | Health, religion, union, politics and dating payments stay local | Both | Implemented |
| P5 | Fines and probation payments are left out | Agent | Implemented |
| P6 | Payslip lines other than net pay are not read | Agent | Implemented |
| P7 | Other statement details stay local | Agent | Implemented |
| P8 | Age, postcode, nationality, gender and education are not used | Agent | Implemented |
| P9 | Social network data is not collected | Agent | Not built |
| P10 | Customer messages are not read | Agent | Implemented |
| P11 | Instructions hidden in documents are treated as data | Both | Partial |
| P12 | If BRANE is down or gives no clear answer, nothing is sent | Both | Implemented |
| P13 | The AI's note is checked before it is shown | Agent | Implemented |
| P14 | Gaps in the evidence go to a person, with no adverse note | Agent | Implemented |
| P15 | Only a human officer makes the lending decision | Agent | Implemented |

## Known limits

- BRANE's name detector missed repeated and upper-case name variants in our tests, so our code scrubs every known variant before sending. Details in `evidence/pack/product-gaps.md`.
- Practice data only. The upload endpoint checks the file's shape, not whether the people are real.
- The demo page offers five built-in files; there is no file upload on the page.
- Six tests are marked as expected failures; each is a known gap, not a hidden bug:
  - Names of private people in bank transfers are still shown on the officer's screen.
  - English instruction text containing "loan", placed in a payment description, can move that payment from housing to debt (the total is unchanged).
  - The same with the instruction placed in the payee name.
  - Dutch instruction text containing "lening", placed in a payment description, does the same.
  - The same with the Dutch instruction placed in the payee name.
  - An instruction hidden in payslip text cannot do anything, because that text is dropped on arrival, but it is therefore not written to the ledger either.

## About this project

Built during the MAIN Summit Hackathon, 20 to 21 November 2026, track AI-Z, team UpSolve. Synthetic data only.

We reused public open-source libraries only: FastAPI, Uvicorn, Pydantic, PyYAML, RapidFuzz, HTTPX, sse-starlette, pypdf and python-multipart, with pytest and Ruff for testing and linting. We used AI coding tools to help write and test the code.

.PHONY: verify demo suite10 export-ledger protocol openapi redteam smoke policy-pull policy-push policy-push-apply policy-check policy-draft-check brane-evidence policy-matrix-csv evidence-pack
ENV_FILE_FLAG := $(if $(wildcard .env),--env-file .env,)
verify:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt ruff check app tests scripts redteam
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python -m pytest -q
demo:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
suite10:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/suite10.py
export-ledger:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/export_ledger.py $(CASE_ID)
protocol:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/build_test_protocol.py
openapi:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/build_openapi.py
redteam:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python redteam/run.py
smoke:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_smoke.py
policy-pull:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_policy.py pull
policy-push:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_policy.py push
policy-push-apply:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_policy.py push --apply
policy-check:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_policy.py check "$(PROMPT)"
policy-draft-check:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/brane_policy.py draft-check
brane-evidence:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/run_brane_evidence.py
policy-matrix-csv:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/build_policy_matrix_csv.py
evidence-pack:
	uv run $(ENV_FILE_FLAG) --python 3.12 --with-requirements requirements.txt python scripts/build_evidence_pack.py

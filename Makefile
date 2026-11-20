.PHONY: verify demo suite10 export-ledger protocol openapi redteam
verify:
	uv run --python 3.12 --with-requirements requirements.txt ruff check app tests scripts redteam
	uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
demo:
	uv run --python 3.12 --with-requirements requirements.txt uvicorn app.api.main:app --reload
suite10:
	uv run --python 3.12 --with-requirements requirements.txt python scripts/suite10.py
export-ledger:
	uv run --python 3.12 --with-requirements requirements.txt python scripts/export_ledger.py $(CASE_ID)
protocol:
	uv run --python 3.12 --with-requirements requirements.txt python scripts/build_test_protocol.py
openapi:
	uv run --python 3.12 --with-requirements requirements.txt python scripts/build_openapi.py
redteam:
	uv run --python 3.12 --with-requirements requirements.txt python redteam/run.py

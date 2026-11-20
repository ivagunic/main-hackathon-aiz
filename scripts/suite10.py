import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

bootstrap_temp = tempfile.TemporaryDirectory(prefix="ai-z-bootstrap-")
os.environ.setdefault("LEDGER_PATH", str(Path(bootstrap_temp.name) / "bootstrap.sqlite3"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline
from app.policy import Ledger

ROOT = pipeline.ROOT

os.environ["BRANE_MODE"] = "fake"
os.environ["PRESCRUB"] = "on"
os.environ["BRANE_DEMO_DOWN"] = "off"
evidence = {"runs": []}
with tempfile.TemporaryDirectory(prefix="ai-z-repeatability-") as temp_dir:
    for run in range(10):
        pipeline.LEDGER = Ledger(Path(temp_dir) / f"run-{run}.sqlite3")
        hashes = {}
        for case_id in ("clean", "sensitive", "variant_a", "variant_b"):
            pipeline.process(case_id)
            hashes[case_id] = pipeline.LEDGER.decisions_hash(case_id)
        evidence["runs"].append(hashes)
if len({json.dumps(row, sort_keys=True) for row in evidence["runs"]}) != 1:
    raise SystemExit("Decision hashes changed across repeatability runs")
output = ROOT / "evidence" / "repeatability.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/security"], check=False)
raise SystemExit(result.returncode)

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("LEDGER_PATH", str(Path(tempfile.gettempdir()) / "ai-z-openapi-ledger.sqlite3"))
sys.path.insert(0, str(ROOT))

from app.api.main import app

Path(ROOT / "contracts" / "openapi.yaml").write_text(yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True), encoding="utf-8")

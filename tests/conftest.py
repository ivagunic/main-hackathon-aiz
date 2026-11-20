import os
import tempfile
from pathlib import Path

os.environ.setdefault("LEDGER_PATH", str(Path(tempfile.gettempdir()) / f"ai-z-test-ledger-{os.getpid()}.sqlite3"))

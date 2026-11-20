import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.policy import Ledger

parser = argparse.ArgumentParser()
parser.add_argument("case_id")
parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
args = parser.parse_args()
Path(f"{args.case_id}-ledger.{args.format}").write_text(Ledger().export(args.case_id, args.format), encoding="utf-8")

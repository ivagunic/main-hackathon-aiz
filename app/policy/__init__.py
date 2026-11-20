from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.models import Decision, Element


def load_policy(path: str | Path) -> dict:
    policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or "rules" not in policy or "version" not in policy: raise ValueError("Invalid policy file")
    valid_lanes = {"cloud_pseudonymised", "cloud_aggregate", "local_only", "excluded", "refuse", "human_review"}
    default = policy.get("default")
    if not isinstance(default, dict) or not all(key in default for key in ("lane", "rule_id", "citation", "brane_policy_ref")):
        raise ValueError("Policy default must define lane, rule_id, citation, and brane_policy_ref")
    if default["lane"] not in valid_lanes: raise ValueError("Invalid default policy lane")
    if not isinstance(policy["rules"], list): raise TypeError("Policy rules must be a list")
    ids = set()
    for rule in policy["rules"]:
        if not all(key in rule for key in ("id", "match", "action", "lane", "citation", "brane_policy_ref")):
            raise ValueError("Each policy rule requires id, match, action, lane, citation, and brane_policy_ref")
        if rule["id"] in ids: raise ValueError(f"Duplicate policy rule id: {rule['id']}")
        if rule["lane"] not in valid_lanes: raise ValueError(f"Invalid policy lane in {rule['id']}")
        ids.add(rule["id"])
    return policy


def route(element: Element, action: str, policy: dict) -> Element:
    for rule in policy["rules"]:
        match = rule.get("match", {})
        categories = match.get("categories", [match.get("category", element.category)])
        if element.category in categories and match.get("action", action) == action:
            return element.model_copy(update={"lane": rule["lane"], "rule_id": rule["id"], "citation": rule["citation"], "brane_policy_ref": rule["brane_policy_ref"]})
    rule = policy.get("default", {"lane": "refuse", "rule_id": "R-DEFAULT", "citation": "No rule matched; fail closed"})
    return element.model_copy(update={"lane": rule["lane"], "rule_id": rule["rule_id"], "citation": rule["citation"], "brane_policy_ref": rule.get("brane_policy_ref", "BRANE-DEFAULT")})


class Ledger:
    def __init__(self, path: str | Path = "ledger.sqlite3") -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, element_id TEXT, category TEXT, lane TEXT, rule_id TEXT, citation TEXT, policy_version TEXT, brane_verdict TEXT, payload_sha256 TEXT, ts TEXT, aiz_decision TEXT, brane_policy_ref TEXT)")

    def append(self, d: Decision) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO decisions(case_id,element_id,category,lane,rule_id,citation,policy_version,brane_verdict,payload_sha256,ts,aiz_decision,brane_policy_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (d.case_id,d.element_id,d.category,d.lane,d.rule_id,d.citation,d.policy_version,d.brane_verdict,d.payload_sha256,d.ts.isoformat(),d.aiz_decision,d.brane_policy_ref))

    def rows(self, case_id: str) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY seq", (case_id,))]

    def decisions_hash(self, case_id: str) -> str:
        raw = "".join(f"{r['element_id']}|{r['category']}|{r['lane']}|{r['rule_id']}\n" for r in self.rows(case_id))
        return hashlib.sha256(raw.encode()).hexdigest()

    def export(self, case_id: str, fmt: str = "jsonl") -> str:
        rows = self.rows(case_id)
        if fmt == "jsonl": return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        if fmt != "csv": raise ValueError("fmt must be jsonl or csv")
        import io
        stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["seq"]); writer.writeheader(); writer.writerows(rows)
        return stream.getvalue()


def record(case_id: str, element: Element, policy_version: str, ledger: Ledger, *, verdict: str | None = None, payload_hash: str | None = None) -> None:
    lane = element.lane or "refuse"
    aiz = {"cloud_aggregate": "allow", "cloud_pseudonymised": "protect", "local_only": "local only", "excluded": "block", "refuse": "block"}.get(lane)
    if element.rule_id == "P2":
        # P2 omits identifiers from outbound requests as a protection measure.
        aiz = "protect"
    ledger.append(Decision(seq=0, case_id=case_id, element_id=element.id, category=element.category, lane=lane, rule_id=element.rule_id or "R-DEFAULT", citation=element.citation or "", policy_version=policy_version, brane_verdict=verdict, payload_sha256=payload_hash, ts=datetime.now(UTC), aiz_decision=aiz, brane_policy_ref=element.brane_policy_ref))


def diff_policies(a: dict, b: dict) -> list[dict]:
    left = {r["id"]: r for r in a.get("rules", [])}; right = {r["id"]: r for r in b.get("rules", [])}
    return [{"id": key, "before": left.get(key), "after": right.get(key)} for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]

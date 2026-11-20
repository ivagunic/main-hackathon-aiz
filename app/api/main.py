from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import pipeline
from app.intake import parse_file_data
from app.models import Element, OfficerView
from app.policy import load_policy, record
from app.qa import ask as ask_question

app = FastAPI(title="AI-Z Loan File Assistant")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
OPENED: dict[str, datetime] = {}
UPLOADS: dict[str, Path] = {}


class Review(BaseModel):
    officer_id: str
    action: str
    reason: str


class Question(BaseModel):
    session_id: str
    question: str


@app.post("/cases")
async def create_case(case_id: Annotated[str | None, Form()] = None, file: Annotated[UploadFile | None, File()] = None):
    if file is None:
        if not case_id or not case_id.isalnum():
            raise HTTPException(422, "Provide a synthetic fixture case_id or a synthetic JSON loan file")
        path = pipeline.ROOT / "data" / "files" / f"{case_id}.json"
        if not path.exists():
            raise HTTPException(404, "Synthetic fixture not found")
        return {"case_id": case_id}
    try:
        content = await file.read()
        loan = parse_file_data(content)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "Upload must be a valid synthetic LoanFile JSON document") from exc
    selected_id = case_id or loan.case_id
    if not selected_id.isalnum() or selected_id != loan.case_id:
        raise HTTPException(422, "case_id must match the uploaded synthetic LoanFile")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", prefix="ai-z-synthetic-", delete=False) as temp:
        temp.write(content)
        temp.flush()
        temp_path = Path(temp.name)
    previous = UPLOADS.get(selected_id)
    if previous:
        previous.unlink(missing_ok=True)
    UPLOADS[selected_id] = temp_path
    return {"case_id": selected_id}


@app.post("/cases/{case_id}/process", response_model=OfficerView)
def run_case(case_id: str) -> OfficerView:
    OPENED.pop(case_id, None)
    path = UPLOADS.pop(case_id, None)
    try:
        view = pipeline.process(case_id, path)
        return view.model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if path:
            path.unlink(missing_ok=True)


@app.get("/cases/{case_id}/view", response_model=OfficerView)
def get_view(case_id: str) -> OfficerView:
    if case_id not in pipeline.VIEWS:
        raise HTTPException(404, "Case has not been processed")
    OPENED[case_id] = datetime.now(UTC)
    return pipeline.VIEWS[case_id].model_dump(mode="json")


@app.get("/cases/{case_id}/events")
def events(case_id: str):
    return EventSourceResponse({"data": json.dumps(event)} for event in pipeline.EVENTS.get(case_id, []))


@app.get("/cases/{case_id}/ledger")
def ledger(case_id: str, fmt: str = "json"):
    if fmt == "json":
        return {"rows": pipeline.LEDGER.rows(case_id), "decisions_hash": pipeline.LEDGER.decisions_hash(case_id)}
    if fmt not in {"jsonl", "csv"}:
        raise HTTPException(422, "fmt must be json, jsonl, or csv")
    return PlainTextResponse(pipeline.LEDGER.export(case_id, fmt), media_type="text/csv" if fmt == "csv" else "application/x-ndjson")


@app.post("/cases/{case_id}/review")
def review(case_id: str, body: Review):
    if case_id not in OPENED:
        raise HTTPException(409, "Open the case view before recording a review")
    if body.action not in {"approve", "decline", "ask_more"}:
        raise HTTPException(422, "Invalid review action")
    if len(body.reason.strip()) < 20:
        raise HTTPException(422, "Review reason must contain at least 20 characters")
    pipeline.EVENTS.setdefault(case_id, []).append({"type": "review_recorded", "officer_id": body.officer_id, "action": body.action})
    return {"recorded": True}


@app.post("/cases/{case_id}/ask")
def ask(case_id: str, body: Question):
    if case_id not in OPENED:
        raise HTTPException(409, "Open the case view before asking a question")
    answer = ask_question(case_id, body.session_id, body.question, pipeline.VIEWS[case_id])
    if answer.refused:
        pipeline.EVENTS.setdefault(case_id, []).append({"type": "flag_raised", "flag": "question_refused", "rule_id": answer.rule_id})
        control = Element(id=hashlib.sha1(f"{case_id}:{body.session_id}:{body.question}".encode()).hexdigest()[:12], source_ref="qa:refusal", kind="control", text="", category="instruction_attack", detector="qa_rules", lane="refuse", rule_id=answer.rule_id or "R-QA-REFUSE", citation=answer.citation or "", brane_policy_ref="LOCAL-QA-REFUSE")
        record(case_id, control, pipeline.ACTIVE_POLICY_VERSION, pipeline.LEDGER)
    return answer.__dict__


@app.post("/admin/policy/{version}")
def activate_policy(version: str):
    if version not in {"v0", "v1"}:
        raise HTTPException(404, "Unknown policy version")
    try:
        load_policy(pipeline.ROOT / "policy" / f"policy.{version}.yaml")
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "Policy file is invalid") from exc
    pipeline.ACTIVE_POLICY_VERSION = version
    return {"active_policy": version}


@app.post("/admin/brane/{state}")
def demo_brane_switch(state: str):
    if state not in {"up", "down"}:
        raise HTTPException(422, "state must be up or down")
    os.environ["BRANE_DEMO_DOWN"] = "on" if state == "down" else "off"
    return {"brane": state}

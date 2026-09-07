from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from adapters import WorkbookAdapter, WorkbookContractError
from pipeline import AnalysisIntent, ConfirmedMapping, InsightPipeline


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
WORK = ROOT / ".work"
UPLOADS = WORK / "uploads"
STATES = WORK / "states"
UPLOADS.mkdir(parents=True, exist_ok=True)
STATES.mkdir(parents=True, exist_ok=True)
TEMPLATE = Path(os.getenv("SKU_AGENT_TEMPLATE", r"C:\Users\320332974\OneDrive - Philips\Documents\可视化模板.pptx"))
pipeline = InsightPipeline(ROOT, TEMPLATE)
app = FastAPI(title="SKU Data Insight Agent", version="1.0.0")


class IntentRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=2000)


class RunRequest(IntentRequest):
    file_id: str
    confirmed_mappings: dict[str, list[ConfirmedMapping]] | None = None
    human_reviewed: bool = False
    semantic_labels_confirmed: bool = False


class ReviewRequest(IntentRequest):
    file_id: str


class ConfirmRequest(BaseModel):
    confirmed_mappings: dict[str, list[ConfirmedMapping]]


class ConfirmLabelsRequest(BaseModel):
    approved: bool = True


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise HTTPException(400, "Invalid id")
    return value


def state_path(run_id: str) -> Path:
    return STATES / f"{safe_id(run_id)}.json"


def write_state(run_id: str, state: dict[str, Any]) -> None:
    state_path(run_id).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def read_state(run_id: str) -> dict[str, Any]:
    path = state_path(run_id)
    if not path.exists():
        raise HTTPException(404, "Run not found")
    return json.loads(path.read_text(encoding="utf-8"))


def uploaded_workbook(file_id: str) -> Path:
    folder = UPLOADS / safe_id(file_id)
    matches = list(folder.glob("*.xlsx"))
    if len(matches) != 1:
        raise HTTPException(404, "Uploaded workbook not found")
    return matches[0]


def contract_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, WorkbookContractError):
        return {"code": exc.code, "message": str(exc), "details": exc.details}
    return {"code": "PIPELINE_FAILED", "message": str(exc), "details": {}}


def recognize_web_intent(prompt: str) -> tuple[AnalysisIntent, str, str | None]:
    """Keep deterministic extraction available when the optional intent API is temporarily unreachable."""
    intent = pipeline.agnes.parse_intent(prompt, safe_local_fallback=True)
    status = pipeline.agnes.status()
    used_agnes = status.get("last_operation") == "intent" and status.get("last_status") == "success"
    parser = "Agnes AI" if used_agnes else "Local validated fallback"
    warning = None if used_agnes else status.get("last_error")
    return intent, parser, warning


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agnes_configured": pipeline.agnes.enabled,
        "llm": pipeline.agnes.status(),
        "template_available": TEMPLATE.exists(),
    }


@app.post("/api/files")
async def upload_workbook(file: UploadFile = File(...)) -> dict[str, str]:
    filename = Path(file.filename or "raw-data.xlsx").name
    if Path(filename).suffix.lower() != ".xlsx":
        raise HTTPException(400, "Only .xlsx raw workbooks are accepted")
    file_id = uuid.uuid4().hex
    folder = UPLOADS / file_id
    folder.mkdir(parents=True)
    destination = folder / filename
    size = 0
    with destination.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                target.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(413, "Workbook exceeds 100 MB")
            target.write(chunk)
    if size < 4 or destination.read_bytes()[:2] != b"PK":
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "The uploaded file is not a valid XLSX container")
    try:
        adapter = WorkbookAdapter(destination, ROOT / "data_contract.yaml")
        adapter.close()
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, contract_error(exc)) from exc
    return {"file_id": file_id, "filename": filename}


@app.post("/api/intents")
def parse_intent(request: IntentRequest) -> dict[str, Any]:
    try:
        intent, parser, warning = recognize_web_intent(request.prompt)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"intent": intent.model_dump(), "parser": parser, "warning": warning}


@app.post("/api/reviews")
def preview_review(request: ReviewRequest) -> dict[str, Any]:
    workbook = uploaded_workbook(request.file_id)
    try:
        intent, parser, intent_warning = recognize_web_intent(request.prompt)
        prepared = pipeline.prepare(workbook, intent)
        adapter = WorkbookAdapter(workbook, ROOT / "data_contract.yaml")
        try:
            channels: dict[str, Any] = {}
            for target in intent.analysis_targets:
                channel = target.channel
                blocks = sorted(adapter._month_blocks(adapter.values_book[adapter.config.channel_sheet(channel)]), key=lambda item: item[1])
                mappings = prepared["mappings"][channel]
                records = adapter.extract(channel, mappings, intent.months)
                channels[channel] = {
                    "source_sheet": adapter.config.channel_sheet(channel),
                    "available_months": len(blocks),
                    "available_range": [blocks[0][2], blocks[-1][2]],
                    "selected_range": sorted({item.period_label for item in records}),
                    "mappings": [asdict(item) for item in mappings],
                    "mapping_resolutions": [asdict(item) for item in prepared["resolutions"][channel]],
                    "pending_candidates": prepared["pending"].get(channel, []),
                    "records": [item.to_dict() for item in records],
                }
        finally:
            adapter.close()
        return {
            "intent": intent.model_dump(),
            "parser": parser,
            "intent_warning": intent_warning,
            "workbook": {"filename": workbook.name, "adapter_version": prepared["adapter_version"]},
            "channels": channels,
            "requires_mapping_confirmation": bool(prepared["pending"]),
            "requires_label_confirmation": bool(prepared["semantic_plan"].review_required),
            "semantic_plan": prepared["semantic_plan"].model_dump(),
            "llm_status": pipeline.agnes.status(),
        }
    except Exception as exc:
        raise HTTPException(422, contract_error(exc)) from exc


@app.post("/api/analysis-runs")
def start_run(request: RunRequest) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    workbook = uploaded_workbook(request.file_id)
    try:
        intent, _, _ = recognize_web_intent(request.prompt)
        result = pipeline.run(workbook, intent, request.confirmed_mappings, semantic_labels_confirmed=request.semantic_labels_confirmed)
    except Exception as exc:
        failure = contract_error(exc)
        error = {"status": "failed", "run_id": run_id, "error": failure["message"], "error_code": failure["code"], "details": failure["details"]}
        write_state(run_id, error)
        raise HTTPException(422, error) from exc
    state = {**result, "run_id": run_id, "file_id": request.file_id, "prompt": request.prompt, "extraction_reviewed": request.human_reviewed, "semantic_labels_confirmed": request.semantic_labels_confirmed}
    write_state(run_id, state)
    return state


@app.post("/api/analysis-runs/{run_id}/confirm")
def confirm_mapping(run_id: str, request: ConfirmRequest) -> dict[str, Any]:
    current = read_state(run_id)
    if current.get("status") != "awaiting_mapping_confirmation":
        raise HTTPException(409, "This run is not awaiting mapping confirmation")
    workbook = uploaded_workbook(current["file_id"])
    intent = AnalysisIntent.model_validate(current["intent"])
    try:
        result = pipeline.run(workbook, intent, request.confirmed_mappings, semantic_labels_confirmed=bool(current.get("semantic_labels_confirmed")))
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    state = {**result, "run_id": run_id, "file_id": current["file_id"], "prompt": current["prompt"], "semantic_labels_confirmed": bool(current.get("semantic_labels_confirmed"))}
    write_state(run_id, state)
    return state


@app.post("/api/analysis-runs/{run_id}/confirm-labels")
def confirm_labels(run_id: str, request: ConfirmLabelsRequest) -> dict[str, Any]:
    current = read_state(run_id)
    if current.get("status") != "awaiting_label_confirmation":
        raise HTTPException(409, "This run is not awaiting label confirmation")
    if not request.approved:
        raise HTTPException(422, "Label plan was not approved")
    workbook = uploaded_workbook(current["file_id"])
    intent = AnalysisIntent.model_validate(current["intent"])
    try:
        result = pipeline.run(workbook, intent, semantic_labels_confirmed=True)
    except Exception as exc:
        failure = contract_error(exc)
        raise HTTPException(422, failure) from exc
    state = {**result, "run_id": run_id, "file_id": current["file_id"], "prompt": current["prompt"], "semantic_labels_confirmed": True}
    write_state(run_id, state)
    return state


@app.get("/api/analysis-runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return read_state(run_id)


@app.get("/api/analysis-runs/{run_id}/files/{channel}/{kind}")
def download_file(run_id: str, channel: str, kind: str) -> FileResponse:
    state = read_state(run_id)
    if state.get("status") != "completed":
        raise HTTPException(409, "Run is not completed")
    result = next((item for item in state.get("results", []) if item["channel"] == channel.upper()), None)
    if result is None or kind not in {"pdf", "json", "zip"}:
        raise HTTPException(404, "Artifact not found")
    artifact_value = result.get(kind) or (result.get("analysis") if kind == "json" else None)
    if not artifact_value:
        raise HTTPException(404, "Artifact not found")
    path = Path(artifact_value).resolve()
    approved_root = (ROOT / "outputs" / "agent-runs").resolve()
    if approved_root not in path.parents or not path.exists():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(path, filename=path.name)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")

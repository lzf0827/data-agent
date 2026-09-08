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
from artifact_service import ArtifactService
from document_agent import DocumentAgent
from memory_store import MemoryStore
from pipeline import AnalysisIntent, AnalysisPlan, ConfirmedMapping, InsightPipeline, proto_l3_enabled, rule_based_intent
from tools import LocalToolRegistry, ToolExecutor
from tools.analytics import DeterministicAnalyticsTool
from tools.official_search import OfficialSearchTool


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
WORK = ROOT / ".work"
UPLOADS = WORK / "uploads"
STATES = WORK / "states"
UPLOADS.mkdir(parents=True, exist_ok=True)
STATES.mkdir(parents=True, exist_ok=True)
TEMPLATE = Path(os.getenv("SKU_AGENT_TEMPLATE", r"C:\Users\320332974\OneDrive - Philips\Documents\可视化模板.pptx"))
pipeline = InsightPipeline(ROOT, TEMPLATE)
memory_store = MemoryStore(Path(os.getenv("MEMORY_STORE_PATH", str(WORK / "memory"))))
artifact_service = ArtifactService(WORK, memory_store)
local_tool_registry = LocalToolRegistry()
local_tool_registry.register(OfficialSearchTool(ROOT, int(os.getenv("OFFICIAL_SEARCH_CACHE_SECONDS", "21600"))))
local_tool_registry.register(DeterministicAnalyticsTool())
local_tool_registry.register(DeterministicAnalyticsTool("analyze_price_trend", "price", "Analyze authorized price movement."))
local_tool_registry.register(DeterministicAnalyticsTool("analyze_metric_movement", "sales", "Analyze authorized sales movement."))
local_tool_registry.register(DeterministicAnalyticsTool("compare_competitors", "summary", "Compare authorized same-channel competitor records."))
local_tool_executor = ToolExecutor(local_tool_registry, int(os.getenv("LOCAL_TOOL_MAX_CALLS", "8")))
document_agent = DocumentAgent(ROOT, memory_store, artifact_service, pipeline.agnes, local_tool_executor)
app = FastAPI(title="SKU Data Insight Agent", version="1.0.0")


@app.middleware("http")
async def prevent_stale_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/styles.css"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class IntentRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=2000)


class RunRequest(IntentRequest):
    file_id: str
    confirmed_mappings: dict[str, list[ConfirmedMapping]] | None = None
    human_reviewed: bool = False
    semantic_labels_confirmed: bool = False
    proto_l3_approved: bool = False


class ReviewRequest(IntentRequest):
    file_id: str


class ConfirmRequest(BaseModel):
    confirmed_mappings: dict[str, list[ConfirmedMapping]]


class ConfirmLabelsRequest(BaseModel):
    approved: bool = True


class ConfirmPlanRequest(BaseModel):
    approved: bool = True


class WorkspaceRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)


class ConversationRequest(BaseModel):
    mode: str = Field(default="document_analysis", pattern=r"^(strict_excel|document_analysis|mixed_analysis|report_generation)$")
    title: str = Field(default="New analysis", min_length=2, max_length=200)


class TurnRequest(BaseModel):
    message: str = Field(min_length=2, max_length=12000)
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)


class ExcelTurnRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    run_id: str = Field(min_length=32, max_length=64)
    answer: str = Field(min_length=1, max_length=20000)
    intent: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list, max_length=10)
    summary: dict[str, Any] = Field(default_factory=dict)


class OutputRequest(BaseModel):
    turn_id: str | None = None
    output_type: str = Field(default="markdown", pattern=r"^markdown$")


def resource_id(value: str, prefix: str) -> str:
    if not re.fullmatch(rf"{re.escape(prefix)}-[a-f0-9]{{32}}", value):
        raise HTTPException(400, "Invalid resource id")
    return value


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
    """Use the deterministic contract parser as the reliable web entry point.

    Intent extraction is a small, safety-critical routing decision. Agnes can
    still be opted in for enrichment, but a proxy or certificate outage must
    not make the Excel preview appear broken.
    """
    local_intent = rule_based_intent(prompt)
    if os.getenv("AGNES_INTENT_LLM_FIRST", "false").strip().lower() not in {"1", "true", "yes"}:
        pipeline.agnes._mark_fallback("intent")
        return local_intent, "Local validated parser", None
    intent = pipeline.agnes.parse_intent(prompt, safe_local_fallback=True)
    status = pipeline.agnes.status()
    used_agnes = status.get("last_operation") == "intent" and status.get("last_status") == "success"
    return intent, "Agnes AI" if used_agnes else "Local validated parser", None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "ui_version": "20260908-6",
        "agnes_configured": pipeline.agnes.enabled,
        "llm": pipeline.agnes.status(),
        "template_available": TEMPLATE.exists(),
        "memory_store": "sqlite-local",
        "document_analysis": True,
        "local_tools": local_tool_registry.catalog(),
    }


@app.post("/api/workspaces")
def create_workspace(request: WorkspaceRequest) -> dict[str, Any]:
    return memory_store.create_workspace(request.title)


@app.get("/api/workspaces")
def list_workspaces() -> list[dict[str, Any]]:
    return memory_store.list_workspaces()


@app.post("/api/workspaces/{workspace_id}/conversations")
def create_conversation(workspace_id: str, request: ConversationRequest) -> dict[str, Any]:
    workspace_id = resource_id(workspace_id, "ws")
    if memory_store.get_workspace(workspace_id) is None:
        raise HTTPException(404, "Workspace not found")
    return memory_store.create_conversation(workspace_id, request.mode, request.title)


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    conversation_id = resource_id(conversation_id, "conv")
    result = memory_store.get_conversation(conversation_id)
    if result is None:
        raise HTTPException(404, "Conversation not found")
    result["findings"] = memory_store.list_findings(conversation_id)
    result["turns"] = memory_store.recent_turns(conversation_id, 50)
    return result


@app.post("/api/workspaces/{workspace_id}/artifacts")
async def upload_artifact(workspace_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    workspace_id = resource_id(workspace_id, "ws")
    if memory_store.get_workspace(workspace_id) is None:
        raise HTTPException(404, "Workspace not found")
    filename = Path(file.filename or "artifact").name
    staging = WORK / "staging"; staging.mkdir(parents=True, exist_ok=True)
    temp = staging / f"{uuid.uuid4().hex}-{filename}"
    size = 0
    try:
        with temp.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise HTTPException(413, "Artifact exceeds 100 MB")
                target.write(chunk)
        return artifact_service.ingest(temp, workspace_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        temp.unlink(missing_ok=True)


@app.get("/api/workspaces/{workspace_id}/artifacts")
def list_artifacts(workspace_id: str) -> list[dict[str, Any]]:
    workspace_id = resource_id(workspace_id, "ws")
    if memory_store.get_workspace(workspace_id) is None:
        raise HTTPException(404, "Workspace not found")
    return memory_store.list_artifacts(workspace_id)


@app.post("/api/conversations/{conversation_id}/turns")
def create_turn(conversation_id: str, request: TurnRequest) -> dict[str, Any]:
    conversation_id = resource_id(conversation_id, "conv")
    conversation = memory_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    if conversation["mode"] == "strict_excel":
        raise HTTPException(400, "strict_excel conversation must use the existing Excel analysis APIs")
    artifact_ids = request.artifact_ids or conversation.get("active_artifacts", [])
    for artifact_id in artifact_ids:
        artifact_id = resource_id(artifact_id, "artifact")
        if memory_store.get_artifact(artifact_id) is None:
            raise HTTPException(404, f"Artifact not found: {artifact_id}")
    try:
        return document_agent.answer(conversation_id, request.message, artifact_ids or None)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/conversations/{conversation_id}/excel-turns")
def record_excel_turn(conversation_id: str, request: ExcelTurnRequest) -> dict[str, Any]:
    """Persist a completed strict-lane run as conversation memory.

    This endpoint records context only; it never executes or mutates the Excel
    fact layer. The next strict run still starts from the newly supplied workbook.
    """
    conversation_id = resource_id(conversation_id, "conv")
    conversation = memory_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    if conversation["mode"] != "strict_excel":
        raise HTTPException(400, "This conversation is not a strict Excel conversation")
    current = read_state(request.run_id)
    if current.get("status") != "completed":
        raise HTTPException(409, "Only completed Excel runs can be saved as conversation turns")
    if current.get("run_id") != request.run_id:
        raise HTTPException(409, "Run identity mismatch")
    if conversation["current_state"].get("last_excel_run_id") == request.run_id:
        turns = memory_store.recent_turns(conversation_id, 50)
        existing = next((turn for turn in reversed(turns) if turn.get("plan", {}).get("run_id") == request.run_id), None)
        if existing:
            return {"turn": existing, "reused": True}

    turn = memory_store.add_turn(
        conversation_id,
        request.message,
        request.answer,
        "completed",
        intent=request.intent,
        plan={**request.plan, "run_id": request.run_id, "lane": "strict_excel"},
        user_id="admin",
    )
    trace = current.get("insight_agent_trace", [])
    event_ids = []
    for event in trace[-40:]:
        event_ids.append(memory_store.add_tool_event(
            turn["turn_id"], event.get("tool") or event.get("action") or event.get("step") or "excel_insight",
            "completed Excel insight context", json.dumps(event, ensure_ascii=False)[:2000],
            event.get("status") or "success", [], model_version=event.get("model"),
        ))
    memory_store.finish_turn(turn["turn_id"], request.answer, "completed", event_ids, [])
    memory_store.update_conversation(
        conversation_id,
        active_goal=request.message,
        active_artifacts=request.artifact_ids,
        current_state={
            "last_excel_run_id": request.run_id,
            "last_answer": request.answer[:12000],
            "summary": request.summary,
            "fact_layer": "duckdb_canonical_records",
        },
    )
    return {"turn": memory_store.get_turn(turn["turn_id"]), "tool_event_ids": event_ids, "reused": False}


@app.get("/api/turns/{turn_id}")
def get_turn(turn_id: str) -> dict[str, Any]:
    turn_id = resource_id(turn_id, "turn")
    result = memory_store.get_turn(turn_id)
    if result is None:
        raise HTTPException(404, "Turn not found")
    return result


@app.get("/api/conversations/{conversation_id}/findings")
def list_findings(conversation_id: str) -> list[dict[str, Any]]:
    conversation_id = resource_id(conversation_id, "conv")
    if memory_store.get_conversation(conversation_id) is None:
        raise HTTPException(404, "Conversation not found")
    return memory_store.list_findings(conversation_id)


@app.post("/api/conversations/{conversation_id}/outputs")
def create_output(conversation_id: str, request: OutputRequest) -> dict[str, Any]:
    conversation_id = resource_id(conversation_id, "conv")
    conversation = memory_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    turns = memory_store.recent_turns(conversation_id, 50)
    turn_id = request.turn_id or (turns[-1]["turn_id"] if turns else None)
    if not turn_id:
        raise HTTPException(400, "No completed turn is available")
    turn = memory_store.get_turn(resource_id(turn_id, "turn"))
    if not turn or turn["conversation_id"] != conversation_id:
        raise HTTPException(404, "Turn not found")
    output_id = memory_store.add_output(conversation_id, turn_id, "markdown", "pending")
    output_path = memory_store.root / "outputs" / f"{output_id}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    findings = memory_store.list_findings(conversation_id)
    lines = [f"# {conversation.get('title', 'Analysis')}", "", turn.get("answer", ""), "", "## Findings"]
    lines.extend(f"- {item['statement']} ({item['finding_type']}, {item['confidence']})" for item in findings)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    with memory_store._lock, memory_store._connect() as db:
        db.execute("UPDATE generated_output SET storage_key=? WHERE output_id=?", [str(output_path.relative_to(memory_store.root)), output_id])
    return {"output_id": output_id, "output_type": "markdown", "download_url": f"/api/outputs/{output_id}/download"}


@app.get("/api/outputs/{output_id}/download")
def download_output(output_id: str) -> FileResponse:
    output_id = resource_id(output_id, "output")
    record = memory_store.get_output(output_id)
    if not record:
        raise HTTPException(404, "Output not found")
    path = memory_store.root / record["storage_key"]
    if not path.exists():
        raise HTTPException(404, "Output file not found")
    return FileResponse(path, filename=path.name, media_type="text/markdown")


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
        result = pipeline.run(workbook, intent, request.confirmed_mappings, semantic_labels_confirmed=request.semantic_labels_confirmed, prompt=request.prompt, plan_approved=request.proto_l3_approved)
    except Exception as exc:
        failure = contract_error(exc)
        error = {"status": "failed", "run_id": run_id, "error": failure["message"], "error_code": failure["code"], "details": failure["details"]}
        write_state(run_id, error)
        raise HTTPException(422, error) from exc
    state = {**result, "run_id": run_id, "file_id": request.file_id, "prompt": request.prompt, "extraction_reviewed": request.human_reviewed, "semantic_labels_confirmed": request.semantic_labels_confirmed, "proto_l3_enabled": proto_l3_enabled(), "plan_approved": request.proto_l3_approved}
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
        result = pipeline.run(workbook, intent, request.confirmed_mappings, semantic_labels_confirmed=bool(current.get("semantic_labels_confirmed")), prompt=current.get("prompt", ""), plan_approved=bool(current.get("proto_l3_enabled") and current.get("plan_approved")), analysis_plan=AnalysisPlan.model_validate(current["analysis_plan"]) if current.get("analysis_plan") else None)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    state = {**result, "run_id": run_id, "file_id": current["file_id"], "prompt": current["prompt"], "semantic_labels_confirmed": bool(current.get("semantic_labels_confirmed")), "proto_l3_enabled": proto_l3_enabled(), "plan_approved": bool(current.get("plan_approved"))}
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
        result = pipeline.run(workbook, intent, semantic_labels_confirmed=True, prompt=current.get("prompt", ""), plan_approved=bool(current.get("plan_approved")), analysis_plan=AnalysisPlan.model_validate(current["analysis_plan"]) if current.get("analysis_plan") else None)
    except Exception as exc:
        failure = contract_error(exc)
        raise HTTPException(422, failure) from exc
    state = {**result, "run_id": run_id, "file_id": current["file_id"], "prompt": current["prompt"], "semantic_labels_confirmed": True, "proto_l3_enabled": proto_l3_enabled(), "plan_approved": bool(current.get("plan_approved"))}
    write_state(run_id, state)
    return state


@app.post("/api/analysis-runs/{run_id}/confirm-plan")
def confirm_plan(run_id: str, request: ConfirmPlanRequest) -> dict[str, Any]:
    current = read_state(run_id)
    if current.get("status") != "awaiting_plan_approval":
        raise HTTPException(409, "This run is not awaiting plan approval")
    if not request.approved:
        raise HTTPException(422, "Analysis plan was not approved")
    workbook = uploaded_workbook(current["file_id"])
    intent = AnalysisIntent.model_validate(current["intent"])
    try:
        result = pipeline.run(workbook, intent, prompt=current.get("prompt", ""), plan_approved=True, analysis_plan=AnalysisPlan.model_validate(current["analysis_plan"]))
    except Exception as exc:
        failure = contract_error(exc)
        raise HTTPException(422, failure) from exc
    state = {**result, "run_id": run_id, "file_id": current["file_id"], "prompt": current["prompt"], "proto_l3_enabled": True, "plan_approved": True}
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

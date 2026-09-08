from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artifact_service import ArtifactService
from memory_store import MemoryStore
from pipeline import AgnesClient
from tools import ToolExecutor
from tools.contracts import ToolContext
from tools.errors import ToolExecutionError
from tools.executor import stable_hash
from runtime.orchestrator import LocalOrchestrator


class DocumentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=8000)
    findings: list[str] = Field(default_factory=list, max_length=10)
    caveats: list[str] = Field(default_factory=list, max_length=10)


class ContextBuilder:
    def __init__(self, store: MemoryStore, artifacts: ArtifactService) -> None:
        self.store, self.artifacts = store, artifacts

    def build(self, conversation_id: str, user_message: str) -> dict[str, Any]:
        conversation = self.store.get_conversation(conversation_id)
        if conversation is None:
            raise ValueError("Conversation not found")
        artifact_records = [self.store.get_artifact(item) for item in conversation["active_artifacts"]]
        artifact_records = [item for item in artifact_records if item]
        evidence = [ref for artifact in artifact_records for ref in self.artifacts.evidence(artifact)]
        findings = self.store.list_findings(conversation_id)
        payload = {
            "current_request": user_message,
            "conversation": {"mode": conversation["mode"], "active_goal": conversation["active_goal"], "current_state": conversation["current_state"]},
            "recent_turns": self.store.recent_turns(conversation_id, 8),
            "active_artifacts": [{key: item[key] for key in ("artifact_id", "file_name", "media_type", "source_sha256", "extraction_status", "manifest")} for item in artifact_records],
            "confirmed_findings": [item for item in findings if item.get("status") == "confirmed"],
            "findings": findings[-20:],
            "recent_tool_events": self.store.list_conversation_tool_events(conversation_id, limit=40),
            "evidence": evidence[:40],
        }
        # Keep the ordering explicit: current artifact evidence is authoritative,
        # while older turns and findings are useful context rather than facts.
        payload["context_policy"] = {
            "priority": ["current_request", "current_artifact_evidence", "confirmed_findings", "recent_tool_events", "recent_turns", "historical_findings"],
            "history_window": 8,
            "evidence_limit": 40,
        }
        payload["context_hash"] = stable_hash(payload)
        return payload


class DocumentAgent:
    def __init__(self, root: Path, store: MemoryStore, artifacts: ArtifactService, agnes: AgnesClient, tools: ToolExecutor | None = None) -> None:
        self.store, self.artifacts, self.agnes = store, artifacts, agnes
        self.orchestrator = LocalOrchestrator(tools) if tools else None
        self.context = ContextBuilder(store, artifacts)

    def answer(self, conversation_id: str, message: str, artifact_ids: list[str] | None = None, user_id: str = "admin") -> dict[str, Any]:
        conversation = self.store.get_conversation(conversation_id, user_id)
        if conversation is None:
            raise ValueError("Conversation not found")
        if artifact_ids:
            self.store.update_conversation(conversation_id, active_artifacts=artifact_ids, active_goal=message)
        context = self.context.build(conversation_id, message)
        turn_stub = self.store.add_turn(conversation_id, message, "", "running", user_id=user_id)
        turn_id = turn_stub["turn_id"]
        event_ids: list[str] = []
        event_ids.append(self.store.add_tool_event(turn_id, "inspect_artifact", f"conversation={conversation_id}", f"inspected {len(context['active_artifacts'])} active artifacts", "success", context["evidence"][:4]))
        if self.orchestrator:
            tool_context = ToolContext(conversation_id=conversation_id, turn_id=turn_id, mode=conversation["mode"], user_id=user_id, store=self.store, artifacts=self.artifacts, metadata={"context_hash": stable_hash(context), "model_version": self.agnes.model if self.agnes.enabled else None, "source_refs": context["evidence"]})
            brands = sorted({brand for brand in ("BRAUN", "PANASONIC", "FLYCO", "YOOSE") if re.search(rf"\b{brand}\b", message, re.I)})
            if os.getenv("LOCAL_TOOLS_ENABLED", "false").strip().lower() in {"1", "true", "yes"} and "竞品" in message and not brands:
                brands = [brand for brand in ("BRAUN", "PANASONIC", "FLYCO") if any(brand in str(item) for item in context["active_artifacts"])]
            for brand in brands[:3] if os.getenv("LOCAL_TOOLS_ENABLED", "false").strip().lower() in {"1", "true", "yes"} else []:
                try:
                    result, event_id = self.orchestrator.run_tool("search_competitor_official_updates", {"brand": brand, "model": ""}, tool_context)
                    event_ids.append(event_id)
                    context.setdefault("tool_results", []).append(result.model_dump(mode="json"))
                except ToolExecutionError as exc:
                    event_ids.append(self.store.add_tool_event(turn_id, "search_competitor_official_updates", brand, str(exc), "failed", [], error_type=exc.error_type, context_hash=tool_context.metadata["context_hash"]))
            try:
                result, event_id = self.orchestrator.run_tool("calculate_summary", {"metric": "summary"}, tool_context)
                event_ids.append(event_id); context.setdefault("tool_results", []).append(result.model_dump(mode="json"))
            except ToolExecutionError as exc:
                event_ids.append(self.store.add_tool_event(turn_id, "calculate_summary", "document context", str(exc), "failed", [], error_type=exc.error_type, context_hash=tool_context.metadata["context_hash"]))
        answer = self._generate(context)
        finding_ids = []
        for statement in answer.findings:
            finding_ids.append(self.store.add_finding(conversation_id, turn_id, statement, "document_claim", "medium", context["evidence"][:3]))
        if answer.caveats:
            event_ids.append(self.store.add_tool_event(turn_id, "reflect", "generated answer", " | ".join(answer.caveats), "success"))
        self._finish_turn(turn_id, message, answer.answer, event_ids, finding_ids)
        state = {"last_answer": answer.answer, "last_finding_ids": finding_ids, "open_questions": answer.caveats}
        self.store.update_conversation(conversation_id, active_goal=message, current_state=state)
        return {"turn": self.store.get_turn(turn_id, user_id), "turn_id": turn_id, "answer": answer.answer, "findings": finding_ids, "tool_events": event_ids, "tool_trace": self.store.list_tool_events(turn_id, user_id), "caveats": answer.caveats, "context": {"artifact_count": len(context["active_artifacts"]), "evidence_count": len(context["evidence"])} }

    def _generate(self, context: dict[str, Any]) -> DocumentAnswer:
        if self.agnes.enabled:
            system = """You are a document analysis assistant. Answer in concise Simplified Chinese. Use only the supplied document excerpts and conversation context. Every finding must be a document claim unless supported by an explicit verified Excel fact. Do not invent numbers, causes, sources, pages, or file contents. Mention conflicts and missing evidence. Return JSON only."""
            try:
                return self.agnes._chat_model(system, json.dumps(context, ensure_ascii=False), DocumentAnswer, "document_analysis", max_attempts=2)
            except Exception:
                pass
        artifacts = ", ".join(item["file_name"] for item in context["active_artifacts"]) or "当前文件"
        excerpts = [item["excerpt"].replace("\n", " ")[:300] for item in context["evidence"][:5] if item.get("excerpt")]
        answer = f"已读取 {artifacts}。当前文档分析模式已建立证据上下文。可继续指定页码、幻灯片或比较对象。\n\n" + ("\n".join(f"- {item}" for item in excerpts) if excerpts else "当前文件暂未提取到可用文本；如果是扫描件或图片型图表，需要视觉/OCR处理。")
        return DocumentAnswer(answer=answer, findings=[], caveats=["当前回答来自文档提取结果，尚未形成可验证的业务事实。"])

    def _finish_turn(self, turn_id: str, message: str, answer: str, event_ids: list[str], finding_ids: list[str]) -> None:
        self.store.finish_turn(turn_id, answer, "completed", event_ids, finding_ids)

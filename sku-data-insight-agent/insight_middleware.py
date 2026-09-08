from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from tools import LocalToolRegistry, ToolExecutor
from tools.analytics import DeterministicAnalyticsTool
from tools.contracts import ToolContext
from tools.errors import ToolExecutionError
from tools.official_search import OfficialSearchTool


class _TraceStore:
    """Run-local event sink so Excel insight runs do not need a conversation row."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add_tool_event(self, turn_id: str, action: str, input_summary: str, output_summary: str, status: str, source_refs: list[dict[str, Any]], **metadata: Any) -> str:
        event_id = f"event-{uuid.uuid4().hex[:12]}"
        self.events.append({"event_id": event_id, "turn_id": turn_id, "action": action, "input_summary": input_summary, "output_summary": output_summary, "status": status, "source_refs": source_refs, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **metadata})
        return event_id


class InsightMiddleware:
    """Mandatory, bounded bridge between deterministic Excel facts and Insight generation."""

    def __init__(self, root: Path) -> None:
        registry = LocalToolRegistry()
        registry.register(OfficialSearchTool(root))
        registry.register(DeterministicAnalyticsTool())
        registry.register(DeterministicAnalyticsTool("analyze_price_trend", "price", "Analyze authorized price movement."))
        registry.register(DeterministicAnalyticsTool("analyze_metric_movement", "sales", "Analyze authorized sales movement."))
        registry.register(DeterministicAnalyticsTool("compare_competitors", "summary", "Compare authorized same-channel competitor records."))
        self.executor = ToolExecutor(registry, max_calls=8)

    def _call(self, name: str, payload: dict[str, Any], context: ToolContext) -> tuple[Any, str | None]:
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                result, event_id = self.executor.execute(name, payload, context)
                if attempt > 1:
                    context.store.add_tool_event(context.turn_id, name, f"retry {attempt}", "recovered", "retry_succeeded", [], parent_event_id=event_id, error_type=None, context_hash=context.metadata.get("context_hash"))
                return result, event_id
            except Exception as exc:
                last_error = exc
                error_type = getattr(exc, "error_type", "TOOL_EXECUTION_ERROR")
                context.store.add_tool_event(context.turn_id, name, f"attempt {attempt}", str(exc), "retrying" if attempt < 2 else "failed", [], error_type=error_type, context_hash=context.metadata.get("context_hash"))
        raise ToolExecutionError(f"Mandatory insight tool {name} failed after bounded retries: {last_error}", "MANDATORY_INSIGHT_TOOL_FAILED")

    def run(self, *, run_id: str, channel: str, sku: str, periods: list[str], mappings: list[Any], records: list[Any], source_hash: str) -> dict[str, Any]:
        trace = _TraceStore()
        turn_id = f"excel-insight-{run_id}"
        record_dicts = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in records]
        refs = [{"artifact_id": f"excel-{source_hash[:16]}", "locator_type": "duckdb_fact", "locator": f"{channel}/{sku}", "excerpt": "authorized canonical records", "content_sha256": source_hash}]
        context = ToolContext(conversation_id=f"excel-run-{run_id}", turn_id=turn_id, mode="strict_excel", user_id="system", store=trace, artifacts=[], metadata={"records": record_dicts, "source_refs": refs, "context_hash": hashlib.sha256(f"{source_hash}:{channel}:{sku}".encode()).hexdigest()})
        analytics: dict[str, Any] = {}
        for name, metric in (("calculate_summary", "summary"), ("analyze_price_trend", "price"), ("analyze_metric_movement", "sales"), ("compare_competitors", "summary")):
            result, _ = self._call(name, {"metric": metric}, context)
            analytics[name] = result.model_dump(mode="json")
        evidence: list[Any] = []
        competitor_count = 0
        for mapping in mappings:
            if getattr(mapping, "role", None) != "Competitor":
                continue
            if competitor_count >= 3:
                break
            competitor_count += 1
            result, _ = self._call("search_competitor_official_updates", {"brand": mapping.brand, "model": mapping.model, "periods": periods, "topics": ["product launch", "promotion", "technology"]}, context)
            from pipeline import EvidenceRecord
            evidence.extend(EvidenceRecord(evidence_id="", title=item.title, url=item.url, published_at=item.published_at, retrieved_at=item.retrieved_at, source_domain=item.source_domain, snippet=item.summary, content_sha256=item.content_sha256) for item in result.items)
        unique: list[Any] = []
        seen: set[str] = set()
        from dataclasses import replace
        for item in evidence:
            if item.content_sha256 in seen:
                continue
            seen.add(item.content_sha256)
            unique.append(replace(item, evidence_id=f"EVENT-{len(unique)+1:03d}"))
        return {"analytics": analytics, "evidence": unique, "trace": trace.events}

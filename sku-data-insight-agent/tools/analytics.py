from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .contracts import ToolContext, ToolSpec


class AnalyticsRequest(BaseModel):
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    metric: str = Field(default="summary", pattern=r"^(summary|price|sales|sales_value)$")


class AnalyticsResponse(BaseModel):
    status: str
    metric: str
    summary: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    message: str | None = None


class DeterministicAnalyticsTool:
    def __init__(self, name: str = "calculate_summary", default_metric: str = "summary", description: str | None = None) -> None:
        self.default_metric = default_metric
        self.spec = ToolSpec(
            name=name,
            version="1.0",
            description=description or "Calculate a deterministic summary from already-authorized structured records.",
            input_model=AnalyticsRequest,
            output_model=AnalyticsResponse,
            allowed_modes=frozenset({"strict_excel", "document_analysis", "mixed_analysis"}),
            read_only=True,
            source_refs_required=False,
            max_calls_per_turn=2,
            timeout_seconds=10,
        )

    def execute(self, request: AnalyticsRequest, context: ToolContext) -> AnalyticsResponse:
        records = context.metadata.get("records", [])
        metric = request.metric if request.metric != "summary" else self.default_metric
        if request.artifact_ids:
            allowed = set(request.artifact_ids)
            records = [item for item in records if item.get("artifact_id") in allowed]
        field_map = {"price": ("price", "asp"), "sales": ("sales", "qty"), "sales_value": ("sales_value", "gmv")}
        if metric == "summary":
            return AnalyticsResponse(status="success", metric=metric, summary={"record_count": len(records)})
        keys = field_map[metric]
        values = [float(item[key]) for item in records for key in keys[:1] if item.get(key) is not None]
        if not values:
            return AnalyticsResponse(status="no_data", metric=metric, message="No authorized numeric records are available.")
        refs = [item for item in context.metadata.get("source_refs", []) if not request.artifact_ids or item.get("artifact_id") in request.artifact_ids]
        return AnalyticsResponse(status="success", metric=metric, summary={"record_count": len(values), "min": min(values), "max": max(values), "average": sum(values) / len(values)}, source_refs=refs[:20])

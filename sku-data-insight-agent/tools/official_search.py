from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pipeline import OfficialEvidenceProvider

from .contracts import ToolContext, ToolSpec


class OfficialUpdatesRequest(BaseModel):
    brand: str = Field(min_length=2, max_length=80)
    model: str = Field(default="", max_length=120)
    date_from: str | None = None
    date_to: str | None = None
    topics: list[str] = Field(default_factory=list, max_length=5)
    periods: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("brand")
    @classmethod
    def normalize_brand(cls, value: str) -> str:
        return value.strip().upper()


class OfficialUpdateItem(BaseModel):
    title: str
    url: str
    published_at: str | None = None
    retrieved_at: str
    source_domain: str
    summary: str
    content_sha256: str
    evidence_type: str = "official_update"


class OfficialUpdatesResponse(BaseModel):
    status: str
    items: list[OfficialUpdateItem] = Field(default_factory=list, max_length=15)
    source_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=15)
    message: str | None = None


class OfficialSearchTool:
    spec = ToolSpec(
        name="search_competitor_official_updates",
        version="1.0",
        description="Search allow-listed competitor official updates and return dated evidence.",
        input_model=OfficialUpdatesRequest,
        output_model=OfficialUpdatesResponse,
        allowed_modes=frozenset({"strict_excel", "document_analysis", "mixed_analysis"}),
        read_only=True,
        source_refs_required=False,
        max_calls_per_turn=5,
        timeout_seconds=20,
    )

    def __init__(self, root, cache_seconds: int = 21600) -> None:
        self.provider = OfficialEvidenceProvider(root / "official_sources.json")
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, OfficialUpdatesResponse]] = {}

    def execute(self, request: OfficialUpdatesRequest, context: ToolContext) -> OfficialUpdatesResponse:
        key = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_seconds:
            return cached[1]
        periods = request.periods or [item for item in (request.date_from, request.date_to) if item]
        periods = periods or [datetime.now(timezone.utc).date().isoformat()]
        evidence = self.provider.search(request.brand, request.model, periods, request.topics)
        start = date.fromisoformat(request.date_from) if request.date_from else None
        end = date.fromisoformat(request.date_to) if request.date_to else None
        filtered = []
        for item in evidence:
            if item.published_at and (start or end):
                try:
                    published = datetime.fromisoformat(str(item.published_at).replace("Z", "+00:00")).date()
                    if (start and published < start) or (end and published > end):
                        continue
                except ValueError:
                    pass
            filtered.append(item)
        evidence = filtered
        items: list[OfficialUpdateItem] = []
        refs: list[dict[str, Any]] = []
        for item in evidence[:15]:
            content_hash = item.content_sha256
            items.append(OfficialUpdateItem(title=item.title, url=item.url, published_at=item.published_at, retrieved_at=item.retrieved_at, source_domain=item.source_domain, summary=item.snippet, content_sha256=content_hash))
            refs.append({"artifact_id": f"web-{hashlib.sha256(item.url.encode()).hexdigest()[:32]}", "locator_type": "url", "locator": item.url, "excerpt": item.snippet, "content_sha256": content_hash})
        result = OfficialUpdatesResponse(status="success" if items else "no_verified_evidence", items=items, source_refs=refs, message=None if items else "No verified official updates were found for the allow-listed domains.")
        self._cache[key] = (time.time(), result)
        return result

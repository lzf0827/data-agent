"""Cross-run experience reuse for the SKU Data Insight Agent (L2->L3 extension).

Reuses (a) human-approved semantic plans and (b) human-confirmed mapping decisions
across runs that share the same structural fingerprint. Reuse is allowed only after
re-validating against the current upload; any fingerprint drift invalidates the cache
and forces normal review. This never bypasses LABEL_REVIEW_REQUIRED or
MAPPING_CONFIRMATION_REQUIRED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from semantic import WorkbookSemanticPlan


class ExperienceStore:
    """Caches approved semantic plans and confirmed mappings by structural fingerprint."""

    def __init__(self, root: Path, semantic_cache: Any | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.semantic_cache = semantic_cache  # optional; reused if the pipeline already owns one
        self._mapping_root = self.root / "confirmed-mappings"
        self._mapping_root.mkdir(parents=True, exist_ok=True)

    # ---- approved semantic plan reuse (delegates to SemanticPlanCache when available) ----

    def read_approved_plan(self, fingerprint: str, *, prompt_version: str, recognizer_model: str | None) -> WorkbookSemanticPlan | None:
        if self.semantic_cache is None:
            return None
        plan = self.semantic_cache.read(fingerprint, prompt_version=prompt_version, recognizer_model=recognizer_model)
        if plan is not None and (plan.human_approved or not plan.review_required):
            return plan
        return None

    # ---- confirmed mapping reuse ----

    def _mapping_path(self, fingerprint: str, channel: str, primary_sku: str, brand: str) -> Path:
        key = self._slug(fingerprint, channel, primary_sku, brand)
        return self._mapping_root / f"{key}.json"

    @staticmethod
    def _slug(*parts: str) -> str:
        joined = "_".join(parts)
        return "".join(character if character.isalnum() else "_" for character in joined)[:160]

    def confirmed_model(self, fingerprint: str, channel: str, primary_sku: str, brand: str) -> str | None:
        path = self._mapping_path(fingerprint, channel, primary_sku, brand)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        model = payload.get("model")
        return str(model) if model else None

    def put_confirmed_model(self, fingerprint: str, channel: str, primary_sku: str, brand: str, model: str) -> None:
        path = self._mapping_path(fingerprint, channel, primary_sku, brand)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(
            {"fingerprint": fingerprint, "channel": channel, "primary_sku": primary_sku,
             "brand": brand, "model": model, "confirmed": True},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        temporary.replace(path)

    def resolve_approved(self, fingerprint: str, channel: str, primary_sku: str, brands: list[str]) -> dict[str, str]:
        """Return a {brand: model} map of previously confirmed mappings for this structure.

        Only entries for the requested brands on the exact fingerprint are returned.
        The caller must still validate against the current snapshot before applying.
        """
        approved: dict[str, str] = {}
        for brand in brands:
            model = self.confirmed_model(fingerprint, channel, primary_sku, brand)
            if model:
                approved[brand] = model
        return approved
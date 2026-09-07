"""Automatic context carry-over for the SKU Data Insight Agent (L2->L3 extension).

Builds a bounded prior-context payload from recent session records for the same
SKU / structural fingerprint. Only summaries and previously approved decisions are
injected; numbers absent from the current run's observations are stripped so prior
conclusions cannot introduce ungrounded metrics into insight generation.
"""

from __future__ import annotations

import math
import re
from typing import Any


class ContextProvider:
    """Injects grounded, bounded prior context into insight generation."""

    MAX_CONTEXT_CHARS = 1200
    MAX_RECORDS = 3

    def __init__(self, session_store=None, *, max_context_chars: int = MAX_CONTEXT_CHARS,
                 max_records: int = MAX_RECORDS) -> None:
        self.session_store = session_store
        self.max_context_chars = max_context_chars
        self.max_records = max_records

    def prior_context(self, *, fingerprint: str, primary_sku: str, session_id: str | None = None) -> list[dict[str, Any]]:
        """Return bounded prior-context items for the same SKU/session."""
        if self.session_store is None:
            return []
        records = self.session_store.recent(session_id=session_id, limit=self.max_records + 2)
        items: list[dict[str, Any]] = []
        for record in records:
            if not record:
                continue
            if fingerprint and record.get("semantic_fingerprint") and record["semantic_fingerprint"] != fingerprint:
                continue
            sku = (record.get("intent") or {}).get("primary_sku") or ""
            if primary_sku and sku and primary_sku.upper() != str(sku).upper():
                continue
            items.append(self._summarize(record))
            if sum(len(item.get("text", "")) for item in items) >= self.max_context_chars:
                break
        return items[: self.max_records]

    @staticmethod
    def _grounded_numbers(allowed: list[str]) -> set[float]:
        result: set[float] = set()
        token = re.compile(r"-?\d+(?:\.\d+)?")
        for label in allowed:
            for match in token.finditer(str(label)):
                try:
                    value = float(match.group(0))
                    if math.isfinite(value):
                        result.add(value)
                except ValueError:
                    continue
        return result

    @classmethod
    def _strip_ungrounded(cls, text: str, allowed_numbers: set[float]) -> str:
        """Replace numbers not grounded in the given label set with a redaction token."""
        def repl(match: "re.Match[str]") -> str:
            value = float(match.group(0))
            grounded = any(abs(value - allowed) <= max(0.11, abs(allowed) * 0.0006) for allowed in allowed_numbers)
            return match.group(0) if grounded else "<prior>"
        token = re.compile(r"-?\d+(?:\.\d+)?")
        return token.sub(repl, text)

    def _summarize(self, record) -> dict[str, Any]:
        result = record.get("result") or {}
        claims = result.get("claims") or []
        # Ground only on meta-identifiers (fingerprint + SKU), never on the claim text
        # itself, so numbers introduced in prior conclusions are treated as ungrounded.
        allowed = [
            str(record.get("semantic_fingerprint", "")),
            str((record.get("intent") or {}).get("primary_sku", "")),
        ]
        for record_item in claims:
            if isinstance(record_item, dict):
                allowed.append(str(record_item.get("subject", "")))
        text = " ".join(str(item.get("text", "")) for item in claims if isinstance(item, dict))
        bounded = self._strip_ungrounded(text, self._grounded_numbers(allowed))[: self.max_context_chars]
        return {
            "run_id": record.get("run_id"),
            "session_id": record.get("session_id"),
            "source": "prior_session",
            "text": bounded,
        }
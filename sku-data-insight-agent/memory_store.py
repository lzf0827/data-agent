"""Session memory for the SKU Data Insight Agent (L2->L3 extension).

Stores per-run/session records so multi-turn follow-up can carry prior context
(previous intent, confirmed mappings, reviewed labels, result summaries) without
the employee restating it. The store is deliberately thin: it persists validated
facts only and never overrides a fresh snapshot.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}(-[A-Z]+)?", run_id):
        raise ValueError("Invalid run_id")


class SessionRecord(dict):
    """A persisted session/run record.

    Subclass of dict for straightforward JSON round-trips while keeping the
    documented field contract discoverable.
    """

    REQUIRED = {
        "run_id",
        "session_id",
        "prompt",
        "intent",
        "semantic_fingerprint",
        "confirmed_mappings",
        "reviewed_labels",
        "result",
        "created_at",
    }

    def __init__(self, **kwargs: Any) -> None:
        missing = self.REQUIRED - set(kwargs)
        if missing:
            raise ValueError(f"SessionRecord missing required fields: {sorted(missing)}")
        super().__init__(kwargs)


class SessionStore:
    """Persist session records under a root directory (typically `.work/sessions`)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, run_id: str) -> Path:
        _validate_run_id(run_id)
        return self.root / f"{run_id}.json"

    def create(self, *, prompt: str, intent: dict[str, Any] | None = None,
               semantic_fingerprint: str = "", confirmed_mappings: list[dict[str, Any]] | None = None,
               reviewed_labels: list[dict[str, Any]] | None = None, result: dict[str, Any] | None = None,
               session_id: str | None = None) -> str:
        run_id = uuid.uuid4().hex
        record = SessionRecord(
            run_id=run_id,
            session_id=session_id or run_id,
            prompt=prompt,
            intent=intent or {},
            semantic_fingerprint=semantic_fingerprint,
            confirmed_mappings=confirmed_mappings or [],
            reviewed_labels=reviewed_labels or [],
            result=result or {},
            created_at=None,  # filled below to avoid import-time clock work
        )
        from datetime import datetime, timezone
        record["created_at"] = datetime.now(timezone.utc).isoformat()
        self.write(record)
        return run_id

    def write(self, record: SessionRecord) -> None:
        path = self._path_for(record["run_id"])
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(dict(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def read(self, run_id: str) -> SessionRecord | None:
        path = self._path_for(run_id)
        if not path.exists():
            return None
        try:
            return SessionRecord(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def recent(self, *, session_id: str | None = None, limit: int = 5) -> list[SessionRecord]:
        """Return the most recent records, optionally filtered by session."""
        records: list[SessionRecord] = []
        if not self.root.exists():
            return records
        candidates = list(self.root.glob("*.json"))
        for path in candidates:
            if path.name.endswith(".tmp"):
                continue
            try:
                records.append(SessionRecord(**json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        if session_id is not None:
            records = [item for item in records if item.get("session_id") == session_id]
        records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return records[:limit]
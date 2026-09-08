from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """Small local-first persistence layer; DATABASE_URL can later point to a Postgres adapter."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "memory.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace (
                    workspace_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation (
                    conversation_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    mode TEXT NOT NULL, title TEXT NOT NULL, active_goal TEXT NOT NULL DEFAULT '',
                    active_artifacts_json TEXT NOT NULL DEFAULT '[]', current_state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turn (
                    turn_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    user_message TEXT NOT NULL, intent_json TEXT NOT NULL DEFAULT '{}', plan_json TEXT NOT NULL DEFAULT '{}',
                    tool_event_ids_json TEXT NOT NULL DEFAULT '[]', finding_ids_json TEXT NOT NULL DEFAULT '[]',
                    answer TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifact (
                    artifact_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    file_name TEXT NOT NULL, media_type TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                    storage_key TEXT NOT NULL, extraction_status TEXT NOT NULL, manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(workspace_id, source_sha256)
                );
                CREATE TABLE IF NOT EXISTS tool_event (
                    event_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, action TEXT NOT NULL,
                    input_summary TEXT NOT NULL, output_summary TEXT NOT NULL, status TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL DEFAULT 0, tool_version TEXT NOT NULL DEFAULT '1.0',
                    input_hash TEXT, output_hash TEXT, parent_event_id TEXT, error_type TEXT,
                    model_version TEXT, context_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS finding (
                    finding_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    statement TEXT NOT NULL, finding_type TEXT NOT NULL, confidence TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_ref (
                    evidence_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, locator_type TEXT NOT NULL,
                    locator TEXT NOT NULL, excerpt TEXT, content_sha256 TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generated_output (
                    output_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    output_type TEXT NOT NULL, storage_key TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )
            existing_columns = {row[1] for row in db.execute("PRAGMA table_info(tool_event)")}
            for name, declaration in {
                "sequence_no": "INTEGER NOT NULL DEFAULT 0", "tool_version": "TEXT NOT NULL DEFAULT '1.0'",
                "input_hash": "TEXT", "output_hash": "TEXT", "parent_event_id": "TEXT", "error_type": "TEXT",
                "model_version": "TEXT", "context_hash": "TEXT",
            }.items():
                if name not in existing_columns:
                    db.execute(f"ALTER TABLE tool_event ADD COLUMN {name} {declaration}")

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def create_workspace(self, title: str, user_id: str = "admin") -> dict[str, Any]:
        workspace_id, stamp = self._id("ws"), now_iso()
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO workspace VALUES (?, ?, ?, ?, ?)", [workspace_id, user_id, title, stamp, stamp])
        return self.get_workspace(workspace_id, user_id)  # type: ignore[return-value]

    def list_workspaces(self, user_id: str = "admin") -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM workspace WHERE user_id=? ORDER BY updated_at DESC", [user_id])]

    def get_workspace(self, workspace_id: str, user_id: str = "admin") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM workspace WHERE workspace_id=? AND user_id=?", [workspace_id, user_id]).fetchone()
            return dict(row) if row else None

    def create_conversation(self, workspace_id: str, mode: str, title: str = "New analysis", user_id: str = "admin") -> dict[str, Any]:
        conversation_id, stamp = self._id("conv"), now_iso()
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO conversation VALUES (?, ?, ?, ?, ?, '', '[]', '{}', ?, ?)", [conversation_id, workspace_id, user_id, mode, title, stamp, stamp])
        return self.get_conversation(conversation_id, user_id)  # type: ignore[return-value]

    def get_conversation(self, conversation_id: str, user_id: str = "admin") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM conversation WHERE conversation_id=? AND user_id=?", [conversation_id, user_id]).fetchone()
            if not row:
                return None
            result = dict(row)
            result["active_artifacts"] = json.loads(result.pop("active_artifacts_json"))
            result["current_state"] = json.loads(result.pop("current_state_json"))
            return result

    def update_conversation(self, conversation_id: str, *, active_goal: str | None = None, active_artifacts: list[str] | None = None, current_state: dict[str, Any] | None = None, user_id: str = "admin") -> None:
        values: list[Any] = []
        updates: list[str] = []
        if active_goal is not None:
            updates.append("active_goal=?"); values.append(active_goal)
        if active_artifacts is not None:
            updates.append("active_artifacts_json=?"); values.append(json.dumps(active_artifacts, ensure_ascii=False))
        if current_state is not None:
            updates.append("current_state_json=?"); values.append(json.dumps(current_state, ensure_ascii=False))
        if not updates:
            return
        updates.append("updated_at=?"); values.append(now_iso()); values.extend([conversation_id, user_id])
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE conversation SET {', '.join(updates)} WHERE conversation_id=? AND user_id=?", values)

    def add_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO artifact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [record["artifact_id"], record["workspace_id"], record.get("user_id", "admin"), record["file_name"], record["media_type"], record["source_sha256"], record["storage_key"], record["extraction_status"], json.dumps(record["manifest"], ensure_ascii=False), record["created_at"]])
        return record

    def get_artifact(self, artifact_id: str, user_id: str = "admin") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM artifact WHERE artifact_id=? AND user_id=?", [artifact_id, user_id]).fetchone()
            if not row:
                return None
            result = dict(row); result["manifest"] = json.loads(result.pop("manifest_json")); return result

    def list_artifacts(self, workspace_id: str, user_id: str = "admin") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM artifact WHERE workspace_id=? AND user_id=? ORDER BY created_at", [workspace_id, user_id]).fetchall()
            result = []
            for row in rows:
                item = dict(row); item["manifest"] = json.loads(item.pop("manifest_json")); result.append(item)
            return result

    def add_tool_event(self, turn_id: str, action: str, input_summary: str, output_summary: str, status: str, source_refs: list[dict[str, Any]] | None = None, *, tool_version: str = "1.0", input_hash: str | None = None, output_hash: str | None = None, parent_event_id: str | None = None, error_type: str | None = None, model_version: str | None = None, context_hash: str | None = None) -> str:
        event_id = self._id("event")
        with self._lock, self._connect() as db:
            sequence_no = db.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM tool_event WHERE turn_id=?", [turn_id]).fetchone()[0]
            db.execute("INSERT INTO tool_event (event_id, turn_id, action, input_summary, output_summary, status, source_refs_json, created_at, sequence_no, tool_version, input_hash, output_hash, parent_event_id, error_type, model_version, context_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [event_id, turn_id, action, input_summary[:1000], output_summary[:2000], status, json.dumps(source_refs or [], ensure_ascii=False), now_iso(), sequence_no, tool_version, input_hash, output_hash, parent_event_id, error_type, model_version, context_hash])
        return event_id

    def add_finding(self, conversation_id: str, turn_id: str, statement: str, finding_type: str, confidence: str, source_refs: list[dict[str, Any]] | None = None) -> str:
        finding_id = self._id("finding")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO finding VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [finding_id, conversation_id, turn_id, statement, finding_type, confidence, json.dumps(source_refs or [], ensure_ascii=False), "unconfirmed", now_iso()])
        return finding_id

    def list_tool_events(self, turn_id: str, user_id: str = "admin") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT e.* FROM tool_event e JOIN turn t ON t.turn_id=e.turn_id WHERE e.turn_id=? AND t.user_id=? ORDER BY e.sequence_no", [turn_id, user_id]).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["source_refs"] = json.loads(item.pop("source_refs_json"))
                result.append(item)
            return result

    def list_conversation_tool_events(self, conversation_id: str, user_id: str = "admin", limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT e.* FROM tool_event e JOIN turn t ON t.turn_id=e.turn_id "
                "WHERE t.conversation_id=? AND t.user_id=? ORDER BY e.created_at DESC LIMIT ?",
                [conversation_id, user_id, limit],
            ).fetchall()
            result = []
            for row in reversed(rows):
                item = dict(row)
                item["source_refs"] = json.loads(item.pop("source_refs_json"))
                result.append(item)
            return result

    def list_findings(self, conversation_id: str, user_id: str = "admin") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT f.* FROM finding f JOIN conversation c ON c.conversation_id=f.conversation_id WHERE f.conversation_id=? AND c.user_id=? ORDER BY f.created_at", [conversation_id, user_id]).fetchall()
            return [dict(row) | {"source_refs": json.loads(row["source_refs_json"])} for row in rows]

    def add_turn(self, conversation_id: str, user_message: str, answer: str, status: str, *, intent: dict[str, Any] | None = None, plan: dict[str, Any] | None = None, tool_event_ids: list[str] | None = None, finding_ids: list[str] | None = None, user_id: str = "admin") -> dict[str, Any]:
        turn_id = self._id("turn")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO turn VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [turn_id, conversation_id, user_id, user_message, json.dumps(intent or {}, ensure_ascii=False), json.dumps(plan or {}, ensure_ascii=False), json.dumps(tool_event_ids or []), json.dumps(finding_ids or []), answer, status, now_iso()])
        return {"turn_id": turn_id, "conversation_id": conversation_id, "user_message": user_message, "answer": answer, "status": status, "tool_event_ids": tool_event_ids or [], "finding_ids": finding_ids or []}

    def recent_turns(self, conversation_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM turn WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?", [conversation_id, limit]).fetchall()
            result = []
            for row in reversed(rows):
                item = dict(row)
                for key in ("intent_json", "plan_json", "tool_event_ids_json", "finding_ids_json"):
                    item[key.removesuffix("_json")] = json.loads(item.pop(key))
                result.append(item)
            return result

    def get_turn(self, turn_id: str, user_id: str = "admin") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT t.* FROM turn t WHERE t.turn_id=? AND t.user_id=?", [turn_id, user_id]).fetchone()
            if not row:
                return None
            result = dict(row)
            for key in ("intent_json", "plan_json", "tool_event_ids_json", "finding_ids_json"):
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
            return result

    def finish_turn(self, turn_id: str, answer: str, status: str, tool_event_ids: list[str], finding_ids: list[str]) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE turn SET answer=?, status=?, tool_event_ids_json=?, finding_ids_json=? WHERE turn_id=?",
                [answer, status, json.dumps(tool_event_ids), json.dumps(finding_ids), turn_id],
            )

    def add_output(self, conversation_id: str, turn_id: str, output_type: str, storage_key: str) -> str:
        output_id = self._id("output")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO generated_output VALUES (?, ?, ?, ?, ?, ?)", [output_id, conversation_id, turn_id, output_type, storage_key, now_iso()])
        return output_id

    def get_output(self, output_id: str, user_id: str = "admin") -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT o.* FROM generated_output o JOIN conversation c ON c.conversation_id=o.conversation_id WHERE o.output_id=? AND c.user_id=?", [output_id, user_id]).fetchone()
            return dict(row) if row else None

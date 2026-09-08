from pathlib import Path

import pytest

from memory_store import MemoryStore
from tools import LocalToolRegistry, ToolExecutor
from tools.analytics import AnalyticsRequest, AnalyticsResponse, DeterministicAnalyticsTool
from tools.contracts import ToolContext, ToolSpec
from tools.errors import ToolPolicyError


def test_registry_exposes_schema_and_rejects_wrong_mode() -> None:
    registry = LocalToolRegistry()
    registry.register(DeterministicAnalyticsTool())
    assert registry.catalog("document_analysis")[0]["name"] == "calculate_summary"
    with pytest.raises(ToolPolicyError):
        registry.get("calculate_summary", "unknown")


def test_local_executor_records_hashes_and_sequence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    workspace = store.create_workspace("Tools")
    conversation = store.create_conversation(workspace["workspace_id"], "document_analysis")
    turn = store.add_turn(conversation["conversation_id"], "summary", "", "running")
    registry = LocalToolRegistry(); registry.register(DeterministicAnalyticsTool())
    executor = ToolExecutor(registry, max_calls=2)
    context = ToolContext(conversation["conversation_id"], turn["turn_id"], "document_analysis", "admin", store, None)
    result, event_id = executor.execute("calculate_summary", {"metric": "summary"}, context)
    assert isinstance(result, AnalyticsResponse)
    assert event_id.startswith("event-")
    with store._connect() as db:
        row = db.execute("SELECT sequence_no, input_hash, output_hash, tool_version FROM tool_event WHERE event_id=?", [event_id]).fetchone()
    assert tuple(row) == (1, row[1], row[2], "1.0")
    assert row[1] and row[2]

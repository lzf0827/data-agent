from pathlib import Path

from artifact_service import ArtifactService
from memory_store import MemoryStore


def test_artifact_registry_deduplicates_and_creates_evidence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    workspace = store.create_workspace("Documents")
    source = tmp_path / "brief.txt"
    source.write_text("Braun price risk is rising.\n", encoding="utf-8")
    service = ArtifactService(tmp_path, store)

    first = service.ingest(source, workspace["workspace_id"])
    second = service.ingest(source, workspace["workspace_id"])

    assert first["artifact_id"] == second["artifact_id"]
    assert first["extraction_status"] == "completed"
    refs = service.evidence(first)
    assert refs[0]["locator_type"] == "document"
    assert refs[0]["content_sha256"]


def test_turn_round_trip_decodes_context_fields(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    workspace = store.create_workspace("Documents")
    conversation = store.create_conversation(workspace["workspace_id"], "document_analysis")
    turn = store.add_turn(
        conversation["conversation_id"],
        "Summarize",
        "",
        "running",
        intent={"kind": "document"},
        plan={"steps": ["inspect_artifact"]},
        tool_event_ids=["event-1"],
    )
    store.finish_turn(turn["turn_id"], "Done", "completed", ["event-2"], [])
    restored = store.get_turn(turn["turn_id"])
    assert restored["answer"] == "Done"
    assert restored["intent"] == {"kind": "document"}
    assert restored["plan"] == {"steps": ["inspect_artifact"]}
    assert restored["tool_event_ids"] == ["event-2"]

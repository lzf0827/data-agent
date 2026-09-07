from __future__ import annotations

from pathlib import Path

import pytest

from memory_store import SessionRecord, SessionStore
from experience_store import ExperienceStore
from context import ContextProvider


def test_session_store_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    run_id = store.create(
        prompt="分析 Philips S1115/02 在京东的价格销量",
        intent={"primary_sku": "S1115/02", "channels": ["JD"]},
        semantic_fingerprint="a" * 64,
        confirmed_mappings=[{"brand": "FLYCO", "model": "FS903"}],
    )
    record = store.read(run_id)
    assert record is not None
    assert record["semantic_fingerprint"] == "a" * 64
    assert record["confirmed_mappings"][0]["brand"] == "FLYCO"


def test_session_store_missing_returns_none(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    assert store.read("0" * 32) is None


def test_session_record_requires_fields() -> None:
    with pytest.raises(ValueError):
        SessionRecord(run_id="x")  # missing required fields


def test_experience_reuse_on_exact_fingerprint(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experience")
    fp = "9" * 64
    store.put_confirmed_model(fp, "JD", "S1115/02", "FLYCO", "FS903")
    assert store.confirmed_model(fp, "JD", "S1115/02", "FLYCO") == "FS903"
    assert store.confirmed_model("0" * 64, "JD", "S1115/02", "FLYCO") is None


def test_experience_resolve_approved_only_requested_brands(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experience")
    fp = "7" * 64
    store.put_confirmed_model(fp, "JD", "S1115/02", "FLYCO", "FS903")
    store.put_confirmed_model(fp, "JD", "S1115/02", "BRAUN", "3000")
    approved = store.resolve_approved(fp, "JD", "S1115/02", ["FLYCO", "PANASONIC"])
    assert approved == {"FLYCO": "FS903"}


def test_context_provider_strips_ungrounded_numbers(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path / "sessions")
    sessions.create(
        prompt="prior run",
        intent={"primary_sku": "S1115/02"},
        semantic_fingerprint="b" * 64,
        result={"claims": [{"subject": "PHILIPS", "text": "最新月 ASP 环比变化 1.5%，销量改善"}]},
    )
    provider = ContextProvider(sessions)
    context = provider.prior_context(fingerprint="b" * 64, primary_sku="S1115/02")
    assert len(context) == 1
    # ungrounded numbers (other than the SKU/fingerprint/allowed labels) are redacted
    assert "<prior>" in context[0]["text"]


def test_context_provider_ignores_other_fingerprint(tmp_path: Path) -> None:
    sessions = SessionStore(tmp_path / "sessions")
    sessions.create(
        prompt="other", intent={"primary_sku": "S1115/02"},
        semantic_fingerprint="c" * 64, result={},
    )
    provider = ContextProvider(sessions)
    assert provider.prior_context(fingerprint="d" * 64, primary_sku="S1115/02") == []
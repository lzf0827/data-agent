from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

import pipeline as pipeline_module
from adapters import WorkbookAdapter
from pipeline import AgnesClient, AnalysisIntent, DecisionInsightSection, ExternalInsightSection, InsightPackage, IntegratedInsightSection, InternalInsightSection, build_observations, build_pricing_analysis_framework, deterministic_claims, deterministic_decision, load_agnes_api_key, rule_based_intent
from tests.fixture_factory import make_fixture


ROOT = Path(__file__).resolve().parents[1]


def open_adapter(path: Path) -> WorkbookAdapter:
    return WorkbookAdapter(path, ROOT / "data_contract.yaml")


def test_variable_competitor_count_is_discovered_per_channel(tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "dynamic-brands.xlsx")
    book = openpyxl.load_workbook(path)
    sheet = book["Key SKUs List"]
    # ALI starts on row 7 in the synthetic fixture. A blank fifth header means
    # this snapshot declares three competitor brands for ALI, while JD has four.
    sheet["E8"] = None
    book.save(path)
    book.close()

    adapter = open_adapter(path)
    try:
        profiler = adapter.semantic_profiler()
        manifest = profiler.build_manifest()
        plan = profiler.validate_plan(profiler.deterministic_plan(manifest), manifest)
        assert len(plan.group_for("JD").competitor_headers) == 4
        assert len(plan.group_for("ALI").competitor_headers) == 3
        assert len(adapter.resolve_mapping("JD", "S3203/08", semantic_plan=plan)[1]) == 4
        assert len(adapter.resolve_mapping("ALI", "S3203/08", semantic_plan=plan)[1]) == 3
    finally:
        adapter.close()


def test_semantic_plan_cannot_cite_a_missing_cell(tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "invalid-plan.xlsx")
    adapter = open_adapter(path)
    try:
        profiler = adapter.semantic_profiler()
        manifest = profiler.build_manifest()
        plan = profiler.deterministic_plan(manifest)
        group = plan.channel_groups[0]
        invalid_group = group.model_copy(
            update={"channel_label": group.channel_label.model_copy(update={"cell": "Z999"})}
        )
        invalid_plan = plan.model_copy(update={"channel_groups": [invalid_group, *plan.channel_groups[1:]]})
        with pytest.raises(ValueError, match="source mismatch"):
            profiler.validate_plan(invalid_plan, manifest)
    finally:
        adapter.close()


def test_per_channel_intent_keeps_skus_separate() -> None:
    intent = rule_based_intent("JD 分析 S1115/02，ALI 分析 S3203/08，最近12个月")
    assert intent.sku_for("JD") == "S1115/02"
    assert intent.sku_for("ALI") == "S3203/08"
    with pytest.raises(ValueError, match="每个渠道"):
        rule_based_intent("JD 和 ALI 分析 S1115/02 与 S3203/08 与 S5000/00")


def test_intent_normalizes_agnes_brand_prefix() -> None:
    intent = AnalysisIntent(analysis_targets=[{"channel": "JD", "primary_sku": "PHILIPS/S1115/02"}])
    assert intent.sku_for("JD") == "S1115/02"


def test_local_key_file_is_loaded_without_exposing_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.delenv("AGNES_DISABLE_KEY_FILE", raising=False)
    secret = "x" * 51
    (tmp_path / "api.txt").write_text(secret, encoding="utf-8")
    source = load_agnes_api_key(tmp_path)
    assert source == "local_key_file"
    assert len(__import__("os").environ["AGNES_API_KEY"]) == 51
    monkeypatch.delenv("AGNES_API_KEY", raising=False)


def test_agnes_uses_strict_schema_and_exposes_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "test-only")
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            content = AnalysisIntent(
                analysis_targets=[{"channel": "JD", "primary_sku": "S1115/02"}], months=12
            ).model_dump_json()
            return {"choices": [{"message": {"content": content}}]}

    def fake_post(url: str, **kwargs):
        captured.update(kwargs["json"])
        return Response()

    monkeypatch.setattr(pipeline_module.httpx, "post", fake_post)
    audit_path = tmp_path / "llm-audit.jsonl"
    client = AgnesClient(audit_path)
    intent = client.parse_intent("分析 JD S1115/02 最近12个月")
    assert intent.sku_for("JD") == "S1115/02"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert client.status()["last_status"] == "success"
    event = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["operation"] == "intent"
    assert event["response_sha256"]
    assert "test-only" not in audit_path.read_text(encoding="utf-8")


def test_agnes_fallback_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    client = AgnesClient()
    client.parse_intent("分析 JD S1115/02 最近12个月")
    status = client.status()
    assert status["configured"] is False
    assert status["last_status"] == "fallback"
    assert status["last_operation"] == "intent"


def test_intent_safe_local_fallback_is_scoped_to_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "test-only")
    monkeypatch.setenv("AGNES_ALLOW_FALLBACK", "false")
    client = AgnesClient()

    def unavailable(*args, **kwargs):
        assert kwargs["max_attempts"] == 1
        assert kwargs["request_timeout"] <= 20
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(client, "_chat_model", unavailable)
    intent = client.parse_intent("分析 JD S1115/02 最近12个月", safe_local_fallback=True)
    assert intent.sku_for("JD") == "S1115/02"
    assert client.status()["last_status"] == "fallback"
    assert client.allow_fallback is False


def test_novel_channel_label_requires_human_review(tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "novel-label.xlsx")
    original = open_adapter(path)
    try:
        profiler = original.semantic_profiler()
        old_manifest = profiler.build_manifest()
        old_plan = profiler.deterministic_plan(old_manifest)
    finally:
        original.close()
    book = openpyxl.load_workbook(path)
    book["Key SKUs List"]["A1"] = "Jingdong Marketplace"
    book.save(path)
    book.close()
    adapter = open_adapter(path)
    try:
        profiler = adapter.semantic_profiler()
        manifest = profiler.build_manifest()
        jd = old_plan.group_for("JD")
        changed_jd = jd.model_copy(
            update={"channel_label": jd.channel_label.model_copy(update={"raw_text": "Jingdong Marketplace", "novel": False})}
        )
        candidate = old_plan.model_copy(
            update={
                "layout_fingerprint": manifest.layout_fingerprint,
                "source": "agnes",
                "channel_groups": [changed_jd if item.channel == "JD" else item for item in old_plan.channel_groups],
            }
        )
        validated = profiler.validate_plan(candidate, manifest)
        assert validated.review_required is True
        assert any(item.cell == "A1" and item.novel for item in validated.unknown_labels)
    finally:
        adapter.close()


def test_insight_framework_follows_output_rules(tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "insight-rules.xlsx")
    adapter = open_adapter(path)
    try:
        mappings, _ = adapter.resolve_mapping("JD", "S3203/08")
        records = adapter.extract("JD", mappings, 12)
        observations = build_observations(records, mappings)
        facts = {"channel": "JD", "primary_sku": "S3203/08", "observations": observations, "external_evidence": [], "missing_driver_inputs": ["promotion", "traffic", "inventory", "gross margin"]}
        package = InsightPackage(claims=deterministic_claims(observations, []), decision=deterministic_decision(facts))
        framework = build_pricing_analysis_framework(observations, package, [])
        assert set(framework) >= {"level_1_descriptive_analysis", "level_2_price_elasticity", "level_3_competitor_analysis", "monthly_report"}
        assert [item["brand"] for item in framework["level_3_competitor_analysis"]] == ["BRAUN", "PANASONIC", "FLYCO"]
        assert len(framework["monthly_report"]["ai_generated_insights"]["top_10_claim_ids"]) == 10
        unsafe = package.model_copy(update={"decision": package.decision.model_copy(update={"proposed_range": "260-295 CNY", "timing": "未来3个月"})})
        safe = AgnesClient._conservatize_insight_package(unsafe, facts)
        assert safe.decision.proposed_range == "毛利和促销约束缺失，当前不设定具体价格区间"
        assert "260" not in safe.decision_claim.text
        safe_again = AgnesClient._conservatize_insight_package(safe, facts)
        assert [item.text for item in safe_again.claims] == [item.text for item in safe.claims]
    finally:
        adapter.close()


def test_insight_language_gate_rejects_english_narrative() -> None:
    with pytest.raises(ValueError, match="must be written in Chinese"):
        AgnesClient._require_chinese_narrative(
            "Panasonic shows a positive price and quantity association that needs further investigation.",
            "CLAIM-004.text",
        )
    AgnesClient._require_chinese_narrative("PANASONIC 的价格与销量同步变化，但仍需促销证据验证。", "CLAIM-004.text")


def test_insight_agent_runs_four_validated_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "four-stage-agent.xlsx")
    adapter = open_adapter(path)
    try:
        mappings, _ = adapter.resolve_mapping("JD", "S3203/08")
        records = adapter.extract("JD", mappings, 12)
        observations = build_observations(records, mappings)
        facts = {
            "channel": "JD",
            "primary_sku": "S3203/08",
            "period_scope": sorted({item.period_label for item in records}),
            "observations": observations,
            "external_evidence": [],
            "quality_warnings": [],
            "missing_driver_inputs": ["promotion", "traffic", "inventory", "gross margin"],
            "method_constraints": ["correlation is not causation"],
        }
        fallback = InsightPackage(claims=deterministic_claims(observations, []), decision=deterministic_decision(facts))
        monkeypatch.setenv("AGNES_API_KEY", "test-only")
        monkeypatch.setenv("AGNES_ALLOW_FALLBACK", "false")
        client = AgnesClient()
        operations: list[str] = []

        def fake_chat(system, user, response_model, operation, semantic_validator=None):
            operations.append(operation)
            values = {
                InternalInsightSection: InternalInsightSection(claims=fallback.internal_drivers),
                ExternalInsightSection: ExternalInsightSection(claims=fallback.external_drivers),
                IntegratedInsightSection: IntegratedInsightSection(claims=fallback.integrated_conclusion),
                DecisionInsightSection: DecisionInsightSection(claim=fallback.decision_claim, decision=fallback.decision),
            }
            result = values[response_model]
            return semantic_validator(result) if semantic_validator else result

        monkeypatch.setattr(client, "_chat_model", fake_chat)
        result = client.synthesize_insights(facts, fallback)
        assert operations == ["insights_internal", "insights_external", "insights_integrated", "insights_decision"]
        assert len(result.claims) == 10
        assert [item.subject for item in result.external_drivers] == ["BRAUN", "PANASONIC", "FLYCO", "OFFICIAL_EVENTS"]
        assert client.status()["last_operation"] == "insights"
    finally:
        adapter.close()


def test_claim_numeric_tokens_must_come_from_cited_observation(tmp_path: Path) -> None:
    path = make_fixture(tmp_path / "numeric-grounding.xlsx")
    adapter = open_adapter(path)
    try:
        mappings, _ = adapter.resolve_mapping("JD", "S3203/08")
        records = adapter.extract("JD", mappings, 12)
        observations = build_observations(records, mappings)
        facts = {"primary_sku": "S3203/08", "period_scope": sorted({item.period_label for item in records})}
        package = InsightPackage(claims=deterministic_claims(observations, []), decision=deterministic_decision({"channel": "JD", "primary_sku": "S3203/08"}))
        claim = package.internal_drivers[0].model_copy(update={"text": "ASP 变化为 123456。"})
        cited = [item for item in observations if item["observation_id"] in claim.observation_ids]
        with pytest.raises(ValueError, match="not grounded"):
            AgnesClient._validate_claim_numbers(claim, cited, facts)
    finally:
        adapter.close()


def test_missing_competitor_is_not_assessable_without_cross_brand_error(monkeypatch: pytest.MonkeyPatch) -> None:
    observations = [
        {
            "observation_id": "OBS-001",
            "brand": "PHILIPS",
            "model": "S1113",
            "role": "PH",
            "valid_months": 12,
            "latest_asp": 100.0,
            "latest_qty": 10.0,
            "latest_gmv": 1000.0,
            "asp_lm_change_pct": 0.0,
            "qty_lm_change_pct": 0.0,
            "gmv_lm_change_pct": 0.0,
            "pearson": 0.0,
            "elasticity_pattern": "Price stable / Qty stable",
            "anomaly": False,
        },
        {
            "observation_id": "OBS-002",
            "brand": "FLYCO",
            "model": "FS903",
            "role": "Competitor",
            "valid_months": 12,
            "latest_asp": 90.0,
            "latest_qty": 8.0,
            "latest_gmv": 720.0,
            "asp_lm_change_pct": 0.0,
            "qty_lm_change_pct": 0.0,
            "gmv_lm_change_pct": 0.0,
            "pearson": 0.0,
            "elasticity_pattern": "Price stable / Qty stable",
            "anomaly": False,
        },
    ]
    facts = {
        "channel": "ALI",
        "primary_sku": "S1113",
        "period_scope": [],
        "observations": observations,
        "external_evidence": [],
        "missing_driver_inputs": ["promotion", "traffic", "inventory", "gross margin"],
    }
    fallback = InsightPackage(claims=deterministic_claims(observations, []), decision=deterministic_decision(facts))
    monkeypatch.setenv("AGNES_API_KEY", "test-only")
    monkeypatch.setenv("AGNES_ALLOW_FALLBACK", "false")
    client = AgnesClient()

    def fake_chat(system, user, response_model, operation, semantic_validator=None):
        values = {
            InternalInsightSection: InternalInsightSection(claims=fallback.internal_drivers),
            ExternalInsightSection: ExternalInsightSection(claims=[
                fallback.external_drivers[0].model_copy(update={
                    "text": "BRAUN 价格与销量均发生变化。",
                    "evidence_level": "OBSERVED",
                    "observation_ids": [],
                    "missing_data": [],
                }),
                *fallback.external_drivers[1:],
            ]),
            IntegratedInsightSection: IntegratedInsightSection(claims=fallback.integrated_conclusion),
            DecisionInsightSection: DecisionInsightSection(claim=fallback.decision_claim, decision=fallback.decision),
        }
        result = values[response_model]
        return semantic_validator(result) if semantic_validator else result

    monkeypatch.setattr(client, "_chat_model", fake_chat)
    result = client.synthesize_insights(facts, fallback)
    braun = result.external_drivers[0]
    assert braun.subject == "BRAUN"
    assert braun.evidence_level == "NOT_ASSESSABLE"
    assert braun.observation_ids == []

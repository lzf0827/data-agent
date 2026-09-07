from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as web_app
from tests.fixture_factory import make_fixture


def configure_test_storage(monkeypatch, tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    states = tmp_path / "states"
    uploads.mkdir()
    states.mkdir()
    monkeypatch.setattr(web_app, "UPLOADS", uploads)
    monkeypatch.setattr(web_app, "STATES", states)


def test_review_endpoint_returns_mapping_and_source_cells(monkeypatch, tmp_path: Path) -> None:
    configure_test_storage(monkeypatch, tmp_path)
    workbook = make_fixture(tmp_path / "fixture.xlsx")
    client = TestClient(web_app.app)
    with workbook.open("rb") as handle:
        upload = client.post("/api/files", files={"file": ("fixture.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert upload.status_code == 200
    response = client.post("/api/reviews", json={"file_id": upload.json()["file_id"], "prompt": "分析 S3203/08 在 JD 最近12个月"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["workbook"]["adapter_version"] == "shaver-pricing-v1.3-dynamic-semantics"
    assert payload["semantic_plan"]["layout_fingerprint"]
    assert payload["llm_status"]["last_operation"] in {"intent", "semantic_plan"}
    assert payload["channels"]["JD"]["available_months"] == 12
    assert payload["channels"]["JD"]["records"][0]["source_cells"]["price"]["cell"]
    assert payload["channels"]["JD"]["mapping_resolutions"]


def test_report_generation_does_not_require_extraction_preview(monkeypatch, tmp_path: Path) -> None:
    configure_test_storage(monkeypatch, tmp_path)
    file_id = "0" * 32
    folder = web_app.UPLOADS / file_id
    folder.mkdir()
    make_fixture(folder / "raw.xlsx")
    monkeypatch.setattr(web_app.pipeline, "run", lambda workbook, intent, confirmed=None, **kwargs: {"status": "completed", "intent": intent.model_dump(), "results": []})
    client = TestClient(web_app.app)
    response = client.post("/api/analysis-runs", json={"file_id": "0" * 32, "prompt": "分析 S3203/08 在 JD 最近12个月", "human_reviewed": False})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["extraction_reviewed"] is False


def test_extracted_monthly_table_filters_to_philips_records() -> None:
    script = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data.records.filter((item) => item.role === "PH")' in script
    assert "const rows = primaryRecords.map" in script


def test_employee_downloads_expose_pdf_json_and_zip_only() -> None:
    script = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    download_block = script.split("const downloads = [", 1)[1].split("];", 1)[0]
    assert '{ kind: "pdf", label: "PDF" }' in download_block
    assert '{ kind: "json", label: "JSON" }' in download_block
    assert '{ kind: "zip", label: "ZIP" }' in download_block
    assert "xlsx" not in download_block.lower()
    assert "duckdb" not in download_block.lower()
    assert "analysis" not in download_block.lower()


def test_web_uses_grouped_insight_headings_and_single_channel_example() -> None:
    root = Path(__file__).parents[1]
    script = (root / "web" / "app.js").read_text(encoding="utf-8")
    page = (root / "web" / "index.html").read_text(encoding="utf-8")
    for heading in ("Internal Drivers", "External Drivers", "Online Research", "Integrated Cause Analysis", "Next-step Actions"):
        assert heading in script
    assert "JD、ALI 或 Offline" in page
    assert "一次仅选择一个渠道和一个 Philips 产品" in page
    assert "组合型号标签视为一个产品" in page


def test_web_analysis_package_orders_chart_insights_and_monthly_table() -> None:
    script = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    result_template = script.split('return `<div class="channel-output">', 1)[1].split("`;", 1)[0]
    assert result_template.index("${visualization}") < result_template.index("insight-sections")
    assert result_template.index("insight-sections") < result_template.index("${monthlyComparison}")
    assert "Sales (Columns, Left Axis) &amp; Price (Line) | Latest 12 Months" in script
    assert "PHILIPS &amp; Competitor Monthly Price &amp; Sales | Latest 12 Months" in script
    assert '.filter((item) => item.role === "PH")' in script

from __future__ import annotations

import json
from pathlib import Path

from pipeline import RENDER_PAYLOAD_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_python_and_node_share_one_render_contract() -> None:
    contract = json.loads((ROOT / "render_contract.json").read_text(encoding="utf-8"))
    renderer = (ROOT / "sku_insight_agent.mjs").read_text(encoding="utf-8")
    assert contract["current_payload_version"] == "1.2"
    assert contract["supported_payload_versions"] == ["1.1", "1.2"]
    assert RENDER_PAYLOAD_VERSION == contract["current_payload_version"]
    assert 'new URL("./render_contract.json", import.meta.url)' in renderer
    assert 'payload.payload_version !== "1.1"' not in renderer

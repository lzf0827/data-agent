from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adapters import WorkbookContractError
from pipeline import AnalysisIntent, ConfirmedMapping, InsightPipeline


def parse_confirmation(path: Path | None) -> dict[str, list[ConfirmedMapping]] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        channel.upper(): [ConfirmedMapping.model_validate(item) for item in items]
        for channel, items in payload.items()
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Generate validated SKU insight artifacts from a supported Pricing Analysis workbook.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--channels", nargs="+", default=["JD"], choices=["JD", "ALI", "OFFLINE"])
    parser.add_argument("--months", type=int, default=12, choices=range(3, 25), metavar="3..24")
    parser.add_argument("--confirmed-mappings", type=Path, help="Optional JSON mapping confirmations keyed by channel.")
    args = parser.parse_args()
    pipeline = InsightPipeline(Path(__file__).resolve().parent, args.template.resolve())
    intent = AnalysisIntent(primary_sku=args.sku, channels=args.channels, months=args.months)
    try:
        result = pipeline.run(args.input.resolve(), intent, parse_confirmation(args.confirmed_mappings))
    except WorkbookContractError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "error": str(exc), "details": exc.details}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "code": "PIPELINE_FAILED", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 3 if result.get("status") == "awaiting_mapping_confirmation" else 0


if __name__ == "__main__":
    raise SystemExit(main())

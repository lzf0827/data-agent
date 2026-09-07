# SKU Data Insight Agent

This project implements a fail-closed pipeline for the supported Philips Pricing Analysis workbook:

`Raw XLSX → bounded structure manifest → constrained semantic plan → deterministic channel adapter → validated canonical records → DuckDB → Excel / PDF`

Agnes AI is deliberately outside the data plane. It converts natural-language requests into a constrained intent object and produces evidence-bounded claims; it never reads Excel cells, chooses unconfirmed ambiguous mappings, or executes SQL.

## Metric definitions

- Sales volume: `Unit`
- Price: `ASP`
- Sales value: `Value`
- Default period: latest 12 complete months
- Channels: `JD`, `ALI`, `OFFLINE`
- Competitors: the channel-specific `Key SKUs List` row may contain zero, one, or several candidate models. Exactly one present model per competitor brand is published; ambiguous or missing mappings stop for confirmation.

## Reliability controls

- A versioned workbook contract and channel adapters locate both raw data and mapping blocks.
- Competitor-brand columns and Philips mapping blocks are discovered from each uploaded snapshot; brand count and mapping rows are not hard-coded.
- `AnalysisIntentV2` carries an explicit `(channel, Philips SKU)` target for every channel. JD, ALI, and Offline never alias or fall back to one another.
- Agnes may label manifest cells, but it cannot read metric cells or execute SQL. Every semantic plan must cite exact cells and pass deterministic bounds, header, fingerprint, inventory, and period-coverage checks.
- Every metric keeps source sheet, source cell, cached value, and formula provenance.
- Pandera validates canonical keys, month completeness, types, and non-negative values.
- `Value` is reconciled against `ASP × Unit` using configured scale factors.
- DuckDB is the single analytical fact layer; the Excel output is a human verification view of the same records.
- Output is written to a temporary run directory, read back, hashed in a manifest, and only then atomically published.
- External events are accepted only from configured official domains. With no verified evidence, causal statements remain hypotheses.

## Run from PowerShell

```powershell
.\run_sku_insight.ps1 `
  -InputWorkbook "C:\path\to\Pricing analysis.xlsx" `
  -TemplatePptx "C:\path\to\可视化模板.pptx" `
  -Sku "S3203/08" `
  -Channels JD,ALI,OFFLINE `
  -Months 12
```

For an ambiguous mapping, the CLI exits with code `3` and returns candidates. Save approved selections as JSON and rerun with `-ConfirmedMappings`.

## Employee web app

```powershell
.\run_agent_web.ps1 -Port 8765
```

Open `http://127.0.0.1:8765` in the Codex in-app browser or your approved local browser. Selecting an Excel file immediately uploads a validated snapshot and loads the current prompt's raw-data preview and mapping states. The flow is upload/auto-load → optional extraction review → label confirmation only for new/low-confidence structures → mapping confirmation when required → quality status → downloads.

Evaluation and local verification are defined in [EVALUATION_WORK_PLAN.md](EVALUATION_WORK_PLAN.md), [TEST_PLAN.md](TEST_PLAN.md), and [LOCAL_TEST_RESULTS.md](LOCAL_TEST_RESULTS.md).

## Outputs

Each channel produces three employee-facing downloads:

- `.pdf`: the only employee-facing report format. It contains the combined SKU trend chart with one consolidated `Summary & Next-step Actions` block directly below it, followed by the monthly comparison and category/brand/competitor tables. Two internal template-rendered pages are composed per PDF sheet where applicable.
- `.json`: inspectable analysis facts, observations, evidence, grounded claims, and decisions
- `.zip`: a convenience package containing only that channel's PDF and JSON

DuckDB and Excel remain internal validation artifacts for deterministic reconciliation and human audit; they are not exposed in the employee download area or included in ZIP packages. PowerPoint remains a temporary template-rendering intermediate and is removed before publication. `run_manifest.json` remains internal provenance metadata.

`LM Change` and `LY Change` are accompanied by separate numerical ASP/Qty/GMV fields. LY fields remain blank when the requested period does not contain the comparable prior-year month.

## Agnes configuration

The service accepts `AGNES_API_KEY` from the environment/`.env`, or an opaque token in `api.txt` one directory above the project. The token is loaded only into the process and is never copied into reports, manifests, audit logs, or browser responses. `/api/health` reports the credential source plus the last LLM operation, success/fallback state, latency, and error without exposing the key. For production fail-closed mode use `AGNES_REQUIRED=true` and `AGNES_ALLOW_FALLBACK=false`. Without an API key in test mode, the pipeline uses deterministic intent parsing and deterministic evidence-bounded claims. Optional official-site search uses `SEARXNG_URL`; allowed domains live in `official_sources.json`.

The Insight Agent follows `输出规则.md` only for Insight content: Level 1 ASP/Qty/GMV, Level 2 price-elasticity quadrant and anomaly, Level 3 Philips vs BRAUN/PANASONIC/FLYCO, then the Monthly Report executive summary, risks/opportunities, pricing performance, competitor watch, and Top 10. Extraction, mapping, storage, visualization, and PDF layout continue to follow `WORK_PLAN.md`.

Insight generation is a four-stage governed workflow: Philips internal drivers, competitor/external drivers, integrated conclusion, and decision recommendation. Each stage uses a strict schema. Local code fixes brand/evidence ownership, validates every observation/evidence identifier, rejects model-calculated numbers, and fails closed when a configured Agnes call cannot pass validation. Exact numeric metrics remain owned by the deterministic calculation and rendering layer; Agnes supplies grounded qualitative interpretation.

Prompt-level regressions are in `evals/dynamic-intent`; workbook and API invariants run with `python -m pytest -q`.

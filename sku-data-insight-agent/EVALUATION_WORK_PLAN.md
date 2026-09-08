# SKU Data Insight Agent — Evaluation Work Plan

Plan version: 1.0  
Baseline date: 2026-09-01  
Deployment target: local Windows pilot on `127.0.0.1`

## 1. Evaluation objective

Prove that the agent never silently changes a number, channel, SKU, mapping, evidence level, or published artifact. Evaluation is layered so a passing PDF cannot hide an extraction or mapping defect.

The project adopts the useful ideas from high-adoption open-source chains without deploying their full stacks locally:

- WrenAI pattern: versioned semantic/data contracts, governed planning, dry validation, structured errors.
- Spider/DB-GPT pattern: separate intent, executable query, and result-equivalence evaluation.
- Langfuse/Phoenix pattern: versioned cases, experiment/run traces, model/prompt comparisons.
- Promptfoo pattern: declarative regression and red-team cases in CI.
- Soda pattern: schema and data-quality contracts executed before publication.

## 2. Evaluation layers

### Layer A — File and workbook contract

Gold cases cover valid XLSX, wrong extension, malformed ZIP, macro payload, oversized expansion, missing sheet, renamed anchor, unknown metric columns, and locked input.

Gate: unsupported structures stop before extraction.

### Layer B — Extraction and provenance

Each Gold record stores channel, month, brand, SKU, Value, Unit, ASP, source sheet, and exact source cells. Tests cover all three channels, first/latest month, nulls, formulas, inserted blank rows, repeated competitor rows, and conflicting duplicates.

Gate: core Gold values and provenance must match exactly; identical repeated rows may collapse only with all source cells retained; conflicting repeats stop.

### Layer C — Competitor mapping

Cases cover exact single mapping, slash groups, continuation rows, one-to-many candidates, empty mapping, missing mapping row, declared model absent from raw data, approved override, and a model that exists in another channel only.

Gate: ambiguous candidates require human confirmation; empty mapping is not inferred; cross-channel selection is impossible.

### Layer D — Intent and query plan

Cases include Chinese and English requests, JD/ALI/Offline aliases, multiple channels, explicit/default periods, unknown SKU, unsupported periods, and prompt-injection text embedded in workbook cells.

Gate: output must validate against `AnalysisIntent`; no arbitrary SQL or extra fields enter the data plane.

### Layer E — Analytical claims

Cases distinguish observations, supported external evidence, hypotheses, and not-assessable results. Every generated number must already exist in an observation. Every causal statement must cite temporally aligned official evidence.

Gate: unsupported causal claims are zero; missing promotion, traffic, inventory, or margin data remains explicit.

### Layer F — Artifacts and employee workflow

Tests reconcile DuckDB, Excel, render payload, and PDF; exercise upload, intent review, extraction preview, mapping confirmation, generation, downloads, and actionable failure states.

Gate: a failed critical check publishes no employee PDF.

## 3. Dataset partitions

- `golden`: manually reviewed representative business cases.
- `challenge`: rare layouts, sparse months, repeated rows, and mapping ambiguity.
- `red_team`: unsafe files, prompt injection, SQL mutation requests, path traversal, and invented evidence.
- `shadow`: previously unseen SKUs/workbook versions used during the business pilot.

Splits are by SKU family, channel, time window, and workbook version—not random rows—to prevent leakage.

## 4. Metrics and release gates

| Metric | Pilot gate |
| --- | ---: |
| Core extraction exact match | 100% |
| Source-cell provenance match | 100% |
| Cross-channel records | 0 |
| Conflicting duplicates silently accepted | 0 |
| Ambiguous mappings silently selected | 0 |
| Unsafe SQL/write operations accepted | 0 |
| Unsupported causal claims | 0 |
| DuckDB/Excel/PDF reconciliation | 100% |
| Critical failure with published PDF | 0 |

Broader intent accuracy and mapping coverage are monitored separately; they cannot compensate for a failed safety invariant.

## 5. Human review protocol

The local web application must show, before report generation:

1. recognized explicit `(channel, Philips SKU)` targets and period;
2. workbook contract and adapter version;
3. month coverage and selected source sheets;
4. resolved and unresolved competitor mappings;
5. extracted monthly Value, Unit, ASP, and source cells;
6. an optional extraction review state recorded for audit;
7. mandatory label confirmation only for novel/low-confidence workbook structures;
8. mandatory confirmation only for ambiguous competitor mappings;
9. final data-quality and LLM-call status plus artifacts.

Extraction review is an optional diagnostic aid, not a publication gate. Ambiguous competitor selection remains an explicit human gate and does not replace automatic checks.

## 6. Exit criteria

Local pilot testing may start after unit/property/Gold/API tests pass and the supplied workbook can be previewed. Employee rollout remains blocked until 20–30 business-selected shadow SKUs have been reviewed with no silent critical error.
